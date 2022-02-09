# Valve Traces

This tool allows allows downloading/running game traces on test machines
exposed using valve gfx ci's executor. Once execution is complete, the
resulting frames are uploading to the valvetraces website for review.

The tool can be run locally, but it is best run from a GitLab pipeline.

## Installing the tool

This should be as simple as:

    $ pip install --user valve-gfx-ci.valvetraces
    $ export PATH=~/.local/bin:$PATH

    $ valvetraces -h
    usage: Valve trace runner [-h] [-s VALVETRACES_URL] [-u VALVETRACES_USER] -r RUN_NAME [--mesa MESA] [--dxvk DXVK] {run,report} ...

    positional arguments:
    {run,report}
        run                 Run the traces and report
        report              Report an already-created run

    options:
    -h, --help            show this help message and exit
    -s VALVETRACES_URL, --valvetraces-url VALVETRACES_URL
    -u VALVETRACES_USER, --valvetraces-user VALVETRACES_USER
    -r RUN_NAME, --run-name RUN_NAME
    --mesa MESA           Path to the mesa repo
    --dxvk DXVK           Path to the dxvk repo

## How to run traces

There are a number of steps you need to take to setup the execution environment:

### Authenticate to the web service

First, you need to create an [account on the service](https://linux-perf.steamos.cloud/),
then set a username and password.

Set the following environment variables:

 - `VALVETRACES_USERNAME`: The username you set on the web service
 - `VALVETRACES_PASSWORD`: The password you set on the web service

You should now be able to list and download traces from the service.

### Create a MinIO bucket to host traces locally

The game traces will need to be downloaded by every single test machine in the
CI system. It is thus important to cache them locally.

Valvetraces will take care of downloading/caching traces for you, as part of
its normal operations, but it requires a MinIO address/bucket name/credentials:

 - `VALVETRACES_MINIO_URL` / `-m` / `--minio-url`: The URL to your MinIO server. Default: `http://localhost:9000`
 - `VALVETRACES_BUCKET` / `-b` / `--bucket`: The name of the bucket that you want to use
 - `VALVETRACES_BUCKET_USER` / `-u` / `--user`: The username to use to access the MinIO bucket
 - `VALVETRACES_BUCKET_PASSWORD` / `-p` / `--access-token`: The password to use to access the MinIO bucket

Finally, we need to give read access to the traces to the jobs running on the
test machines. This can be achieved by embedding the credentials specified
above in the job description yaml file specified using
`VALVETRACES_EXECUTOR_JOB` / `--executor-job-path`, or you could create a
MinIO group which would have read-only access and ask the executor to add
the MinIO user created for the job to be added to to this group.

If you are using the Valve-infra project for your gateway, the valvetraces-ro
group will be created and granted read access to the valvetraces bucket
automatically. If you are using another infrastructure or want to change the
name of the group the job user should be added to, you can set it using
`VALVETRACES_GROUP_NAME` / `--minio-valvetraces-group-name`.

### Creating a container for the test environment

Valvetraces will need to run game traces in a test environment which you need
to setup yourself. This gives you the most flexibility but may be a little
overwhelming, so let's review what are the actual dependencies:

 - Drivers: OpenGL / Vulkan
 - Tracing tools in $PATH: apitrace / apitrace.exe (use binfmt) / gfxreconstruct
 - A working desktop environment: Xorg / Wayland
 - Python packages: valve-gfx-ci.gfxinfo / valve-gfx-ci.executor.client
 - Debug tools: vulkaninfo / glxinfo
 - Call `$job_folder_mount_point/valvetraces-run.sh`

So, how would it look in practice? Let's check a script that would give you a
working test environment when run inside an Arch-linux based container:

    pacman --noconfirm -S python-pip
    pip install valve-gfx-ci.gfxinfo valve-gfx-ci.executor.client

    # Install the tracing tools
    pacman --noconfirm -S wget p7zip unzip apitrace
    cd /opt
    wget https://github.com/apitrace/apitrace/releases/download/10.0/apitrace-10.0-win64.7z
    7z x apitrace-10.0-win64.7z
    rm apitrace-10.0-win64.7z
    chmod +x apitrace-10.0-win64/bin/*.exe

    wget https://github.com/LunarG/gfxreconstruct/releases/download/v0.9.10/gfxreconstruct-v0.9.10-windows-msvc.zip
    unzip gfxreconstruct-v0.9.10-windows-msvc.zip
    rm gfxreconstruct-v0.9.10-windows-msvc.zip
    chmod +x gfxreconstruct-v0.9.10/*.exe

    # Setup Wine
    pacman --noconfirm -S wine pipewire-jack pipewire-media-session wine-mono wine-gecko
    export WINEPREFIX=/wineprefix
    cat >crashdialog.reg <<EOF
    Windows Registry Editor Version 5.00

    [HKEY_CURRENT_USER\Software\Wine\WineDbg]
    "ShowCrashDialog"=dword:00000000

    EOF
    wine regedit crashdialog.reg
    rm crashdialog.reg

    # Add all the graphics drivers and test environments we may possibly need
    pacman --noconfirm -S xorg-server xorg-xset xf86-video-amdgpu [...]
    pacman --noconfirm -S mesa vulkan-radeon vulkan-tools mesa-demos mesa-utils

    # Create a setup script which will set up the container
    cat <<EOT >> /entrypoint
    #!/bin/sh

    set -eux

    # Setup auto execution of Windows executables (and let it fail, in case we already did)
    mount binfmt_misc -t binfmt_misc /proc/sys/fs/binfmt_misc || /bin/true
    echo ':DOSWin:M::MZ::/usr/bin/wine:' > /proc/sys/fs/binfmt_misc/register || /bin/true
    echo 1 > /proc/sys/fs/binfmt_misc/status || /bin/true

    # environment variables
    export PATH="/opt/apitrace-10.0-win64/bin/:/opt/gfxreconstruct-v0.9.10/:$PATH"
    export PYTHONUNBUFFERED=1

    export WINEPREFIX=$WINEPREFIX
    export WINEDEBUG=-all
    export WINEESYNC=1

    # Disable vsync
    export MESA_VK_WSI_PRESENT_MODE=mailbox
    export vblank_mode=0

    # Wait for amdgpu to be fully loaded
    sleep 1

    # Start X, and wait 5 seconds for it to start
    /usr/bin/Xorg vt45 -noreset -s 0 -dpms -logfile /Xorg.0.log &
    export DISPLAY=:0
    for i in {50..0..-1}
    do
        xset s off -dpms 2> /dev/null && break
        if [ $i -eq 0 ]; then
            xset s off -dpms
            echo "Failed to wait for X to start"
            exit 1
        fi
        sleep 0.1
    done

    # Start the valvetraces
    exec ./valvetraces-run.sh
    EOT
    chmod +x /entrypoint

Finally, make sure that `/entrypoint` is set as the entrypoint of the
container, then push it to a container registry that is accessible to the test
machines.

### Create the job description for executorctl

Valvetraces has no idea about how to boot and manage the test machine, so it
requires this information in the form of a job description, compatible with
executorctl.

Of course, this is highly-dependent on your infrastructure, but here is an
example one, that would be targeted towards the valve-ci-gfx infra:

    version: 1
    # Rules to match for a machine to qualify
    tags:
        - amdgpu:codename:RENOIR
    timeouts:
    first_console_activity:  # This limits the time it can take to receive the first console log
        minutes: 5
        retries: 3
    console_activity:        # Reset every time we receive a message from the logs
        minutes: 1
        retries: 99
    boot_cycle:
        hours: 4
        retries: 3
    overall:                 # Maximum time the job can take, not overrideable by the "continue" deployment
        hours: 360
        retries: 0
        # no retries possible here
    console_patterns:
        session_end:
            regex: '^.*It''s now safe to turn off your computer\r$'
        session_reboot:
            regex: 'GPU hang detected!'
        job_success:
            regex: '\[.*\]: Execution is over, pipeline status: 0\r$'
    # Environment to deploy
    deployment:
    # Initial boot
    start:
        kernel:
        url: 'http://10.42.0.1:9000/boot/default_kernel'
        cmdline:
            - SALAD.machine_id={{ machine_id }}
            - console={{ local_tty_device }},115200 earlyprintk=vga,keep loglevel=6
            - b2c.ntp_peer=10.42.0.1 b2c.pipefail b2c.cache_device=auto b2c.poweroff_delay=15
            - b2c.minio="gateway,{{ minio_url }},{{ job_bucket_access_key }},{{ job_bucket_secret_key }}"
            - b2c.volume="{{ job_bucket }}-job,mirror=gateway/{{ job_bucket}},pull_on=pipeline_start,push_on=changes,overwrite,preserve,remove,expiration=pipeline_end"
            - b2c.volume=valvetraces,mirror=gateway/valvetraces,pull_on=pipeline_start,overwrite,preserve,remove,fscrypt_key=$FSCRYPT_KEY
            - b2c.container="-ti --tls-verify=false docker://{{ fdo_proxy_registry }}/mupuf/valve-infra/machine_registration:latest check"
            - b2c.container="-v {{ job_bucket }}-job:/job -w /job -v valvetraces:/traces --tls-verify=false -w /job docker://10.42.0.1:8002/$PATH_TO_YOUR_CONTAINER  /entrypoint-dxvk"
        initramfs:
        url: 'https://gitlab.freedesktop.org/mupuf/boot2container/-/releases/v0.9.4/downloads/initramfs.linux_amd64.cpio.xz'

### Running valvetraces

Now that we set up all the dependencies for Valvetraces, let's run it:

    $ valvetraces run job.yml

That being said, if we don't give any information about what project is being
tested and what is its version, then valvetraces will not be able to know if
a the produced frames are known to be stable or not. This means valvetraces
will never return with a `1` exit code.

If you would like to integrate valvetraces in your GitLab CI pipeline, you will
thus need to specify which component you are testing:

    $ valvetraces --mesa ~/src/mesa run job.yml
    or
    $ valvetraces --dxvk ~/src/dxvk run job.yml

If for some reason, you would like to locally re-report a valvetraces run, you
may do so by doing:

    $ valvetraces [--dxvk/--mesa] report <job folder>

That should be all!
