# Valve infra container

The Valve infra container is meant to run on the gateway of a CI infrastructure, and comes with the following
requirements:

 - Hardware: Two network interfaces, one connected to the internet while the other one is connected to a switch where
   all the test machines to be exposed by the gateway are connected.
 - Volumes: The container requires a volume to store persistent data (mounted at /mnt/permanent), and optionally a
   temporary volume which acts as a cache across reboots (mounted at /mnt/tmp).
 - Container: The container needs to be run as privileged, and using the host network

Provided that you satisfy the hardware requirement, the container can thus be run like so:

    # podman volume create perm
    # podman volume create tmp
    # podman run --privileged --network=host -v tmp:/mnt/tmp -v perm:/mnt/permanent --tls-verify=false --entrypoint=/bin/init docker://registry.freedesktop.org/mupuf/valve-infra/valve-infra:latest

For development purposes, it is advised to run the container in a virtual machine. The infrastructure for virtual testing is called Vivian. To get started quickly and check everything is working as expected on your device, run,

 - `./tools/vivian-tmux.sh`

This will start a tmux dashboard with several panes showing the status
of the virtual infrastrcuture. Pane 1 contains a shell to the virtual
gateway. You can now validate a couple things,

  1. Check in pane 0 that all the services are looking healthy. This
  is simply the system journal being followed.

  2. Check in vPDU status that all ports are OFF, this is the starting
  configuration.

  3. Check there is on virtual PDU registered in pane 4.

  4. Check there are no DUTs currently registered in the gateway under pane 5.

  5. Open a shell and manually power on a virtual test device,

     valve-infra $ python ./vivian/client.py --outlet 3 --on

  6. Check the machine boots and registers with the executor
  correctly, pane 5 will now show the newly registered machine (from
  the internal machine DB)

  7. Notice the newly created machine is not registered remotely yet,
  this is because it hasn't completed the pre-service checks
  (Sgt. Hartman)

  8. Navigate to http://localhost:8001/admin/ to modify the machine
  configuration. The default username and password is =admin= and
  =password=.

  9. Set the PDU port for this machine, in our example the port ID is
  3 and the PDU is vpdu1. These data are not auto-discovered
  currently.

  10. Check the local TTY device, it should be autoconfigured as
  =ttyS1=.

  11. Check the "Ready for service" box and click save.

  12. Go to Gitlab and check that the new runner has been registered.

Congratulations! You seem to have a functional setup! Most of the
steps above are amenable to further configuration. You are now in a
position to play around and modify defaults to your testing
requirements.

NOTE: Systemd will try to take over the current console at boot. To see the infrastructure's dashboard, just press
CTRL+F2. This will be addressed in a future series.

## Walk through

The valve-infra container is systemd-based. You will find the following services:

 - infra.service: The main service, which calls /app/entrypoint.
 - sshd.service: For allowing ssh connections. Make sure to add your ssh key to rootfs/root/.ssh/authorized_keys and get
   the container rebuilt/pushed.
 - podman.service: For docker-compose emulation, which will soon be made irrelevant.

## Local testing

To build the container,

   make CONTAINER=mupuf/valve-infra/valve-infra-cturner:latest -C containers/valve-infra/ container

By default it will tagged with the fd.o registry,

   podman inspect registry.freedesktop.org/mupuf/valve-infra/valve-infra-cturner:latest

To force a rebuild, ignoring the container build cache,

   make IGNORE_CACHE=1 CONTAINER=mupuf/valve-infra/valve-infra-cturner:latest -C containers/valve-infra/ container

To build and push the container to local registry for faster debugging,

   podman run --rm -p 8088:5000  --name registry registry:2
   make IGNORE_CACHE=1 REGISTRY=localhost:8088 CONTAINER=mupuf/valve-infra/valve-infra-cturner:latest -C containers/valve-infra/  push-container
   podman inspect localhost:8088/mupuf/valve-infra/valve-infra-cturner:latest

(Use make V=1 ... for extra logging in the various build components we use)

To test this container in a virtualized environment (assuming the
local registry case above, adjust as necessary),

   make REGISTRY=10.0.2.2:8088 CONTAINER=mupuf/valve-infra/valve-infra-$USER:latest -C containers/valve-infra/ vivian

You may SSH into the VM using this,

    make -C containers/valve-infra/ vivian-connect

Test iterate on changes to the ansible configuration, start Vivian as
above, and then treat it like a typical remote target with playbook
commands,

    cd ansible ; ansible-playbook gateway.yml --extra-vars "farm_name=$FARM_NAME gitlab_registration_token=$GITLAB_REGISTRATION_TOKEN"  -l vivian

Other notes,

 - In the QEMU window that got created, wait for the login screen
 - Press Alt,-> or CTRL+F2 to switch to tty2, a dashboard should show the current state of the infra
 - Press Ctrl-b c to start a new shell in the dashboard, or press
   CRTL+F3 to switch to tty3, type root, and you should be ready to
   work!
 - `make clean`: removes all the files created for the test environment.

WARNING: powering off the machine does not currently work, for reasons that are still being investigated. Just kill
qemu when you are done!
