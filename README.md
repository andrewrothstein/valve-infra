# Valve CI Infrastructure

This repository contains the source for the Valve CI infrastructure. Its main
purpose is to build a multi-service container that acts as a bare-metal CI
gateway service, responsible for the orchestration and management of devices
under test, or DUTs as we call them.

This container can in turn be run from a host OS, booted directly using
[boot2container](https://gitlab.freedesktop.org/mupuf/boot2container),
or netbooted over the internet using
[iPXE boot server](ipxe-boot-server/README.md).

## Requirements

The Valve Infra container is meant to be run on the gateway machine of
a CI farm, and comes with the following requirements:

 - Hardware: Two network interfaces, one connected to the internet while the other one is connected to a switch where
   all the test machines to be exposed by the gateway are connected.
 - Volumes: The container requires a volume to store persistent data (mounted at /mnt/permanent), and optionally a
   temporary volume which acts as a cache across reboots (mounted at /mnt/tmp).
 - Container: The container needs to be run as privileged, and using the host network

## Hacking on the infrastructure

Provided that you satisfy the hardware requirement, the container can thus be run like so:

    # podman volume create perm
    # podman volume create tmp
    # podman run --privileged --network=host -v tmp:/mnt/tmp -v perm:/mnt/permanent --tls-verify=false --entrypoint=/bin/init docker://registry.freedesktop.org/mupuf/valve-infra/valve-infra:latest

*NOTE:* This could do nasty things to your host environment, due to
its privileged status. It is recommended to keep reading for tips on
running it all in a virtual and production environment. This is
however the general idea of the deployment.

### Building

The container image is provisioned using Ansible recipes (see the
`ansible/` subproject).

*WARNING:* in order to *"ssh"* into the gateway container you will
need to provide your own public key. Make sure to add yours at
[ansible/gateway.yml](ansible/gateway.yml).

The following is a (likely incomplete) list of dependencies:

    - buildah
    - jq
    - make
    - podman
    - skopeo

Before building the container, we first need to start a local registry to
host it, as this will save round-trips to an external registry:

    make local-registry

You can then build the container:

	make valve-infra-container

Build options

  - `V=1` - Turn on more verbose logging messages in the build process
  - `EXTRA_ANSIBLE_FLAGS="-vvv ..."` - Pass any custom flags to
    `ansible-playbook`. Helpful for re-running only tagged roles in
    the ansible build, for example.
  - `EXTRA_ANSIBLE_VARS="private_interface=brian ..."` -
    The ansible playbook for the gateway container has a number of
    configuration variables. You may override/specify them using this
    Makefile argument.
  - `IMAGE_NAME=localhost:8088/my/image` -
    The container name to tag the image with. *WARNING:* The image
    will automatically be pushed to the registry that got tagged!
    Defaults to `localhost:8088/valve-infra/valve-infra-container:latest`.

Once completed, a container image will be generated, for example,

    Successfully tagged localhost:8088/valve-infra/valve-infra-container:latest
    60cc3db9bedd2a11d8d61a4433a2a8e8daf35a59d6229b80c1fdcf9ece73b7ab

Notice it defaults to a `localhost` registry. This is to save on
bandwidth (the valve-infra container is quite big).

### Running the infrastructure

Now that we have built our container, we need to start another component: a
virtual PDU that will spawn a virtual machine every time its virtual port turns
on. This can be done by running this simple command:

	make vpdu

*TODO:* This might make more sense to be pre-configured inside the
container, but then you need to bundle QEMU (not a huge deal), and
worry about X11 forwarding from QEMU to the host if you wish to see a
graphical QEMU window, which can be handy. WIP.

We are now ready to start our virtual gateway machine, which will boot
directly into the container we built in the previous section:

	make vivian [SSH_ID_KEY=~/.ssh/vivian] [GITLAB_REGISTRATION_TOKEN=...] [GITLAB_URL=https://gitlab.freedesktop.org]

Note: options to vivian can be passed by setting `VIVIAN_OPTS`, for example:

	make VIVIAN_OPTS="--ssh-port=50022" ... vivian

The virtual testing recipes will fetch a Linux kernel and a
boot2container ramdisk, and start the system. After the kernel boots
and loads the ramdisk, the ramdisk will then pull the valve-infra
container, and hand control to it.

**N.B:** Due to the stateful nature of the permanent partition in the
VM's tmp disk, it is wise to occasionally delete said disk and check
a fresh boot continues to work as expected.

You should now see a QEMU window, which will boot a Linux kernel, then
boot2container will download the container we built and boot into it.
When this is done, you should now see a dashboard which looks mostly green.
The same dashboard should also be present in the terminal you used to connect.

To get a shell on the gateway you can either create one from the dashboard
by pressing `Ctrl-b c`, or connect via SSH using `make vivian-connect`.

*TODO:* Drop vivian as a side-project, integrate its testing
dependencies directly into the container image.

### Spawning virtual DUTs

Right now, our gateway has no idea about any potential machine connected
to its private network interface. Let's boot one!

    python3 vivian/client.py --outlet 1 --on

This will open a new QEMU window, where the machine will get an IP from
the gateway, download iPXE then boot the kernel/initramfs which will in
turn register the machine using the machine_registration container.

If all went well, you should now see a machine appear in the "Machines"
column of the dashboard, with the state `WAIT_FOR_CONFIG`. This indicates
that the machine has been properly registered, but is missing information
about which PDU and PDU port it is connected to. To set these parameters,
you will need to SSH into the gateway using `make vivian-connect`, then edit
`/mnt/permanent/mars_db.yaml` to set the `pdu` field of the machine to `VPDU`,
and the `pdu_port` to `1`. While you are at it, you may also want to set the
`pdu_off_delay` to `1`s rather than 30 to speed up testing. For more
information about the MaRS DB, check out our
[executor's README](executor/server/README.md).

Once you save your changes, the state of the machine should switch to
`TRAINING` and the machine will go be booted in a loop for a set amount of
times in order to test the boot reliability. After the boot loop is complete,
the machine will be marked as ready for testing and its state should change to
`IDLE`.

Your first virtual test machine is now available for testing both locally, and
on your chosen Gitlab instance.

### Running a job on the virtual gateway

Now that you have at least one machine available, you may run jobs on it using
the following command:

	executorctl -e http://localhost:8000 run -t virtio:family:VIRTIO $JOB_FILE

If all went well, congratulations! You seem to have a functional
setup! Most of the steps above are amenable to further configuration.
You are now in a position to play around and modify defaults to your
testing requirements.

### Iterating on changes

*TODO:* partial updates are currently broken, and are being worked on.

After making changes to Ansible, it's useful to sync them to a running
VM and check the desired changes were made. To replay the entire
gateway playbook against the VM,

	make FARM_NAME=$(whoami)-farm vivian-provision

Or just the items tagged dashboard and minio,

	make FARM_NAME=$(whoami)-farm TAGS=dashboard,minio vivian-provision

## Production deployment

*TODO:* Revisit this when we complete the MVP.

--------------------

Running the infrastructure with the following command:

    docker run --privileged --network=host --rm -it -v $(pwd):/app -v /mnt:/mnt registry.freedesktop.org/mupuf/valve-infra

The project is voluntarily light on configuration options as it
strives for auto-configuration as much as possible. However, it is
possible to override the following parameters by setting the following
environment variables,

* TMP_MOUNT: The place where large, transient files can be
  stored. General scratch space. Defaults to `/mnt/tmp`. If you change
  this, make sure you pass the right mount point into the container.
* PERMANENT_MOUNT: The place to store files that should persist across reboots
  (configuration files, tiny databases, ...). Defaults to `/mnt/persistent`.
  If you change this, make sure you pass the right mount point into the container.
* PRIVATE_INTERFACE: The name of the network interface connected to private
  network. Defaults to `private`.
* FARM_NAME: A name unique to your farm installation. I recommend your IRC nick for now if you are running a local farm. Charlie's farm is `tchar`, Martin's is `mupuf`, and so on. The production farms will be named after the company hosting them, e.g. `igalia` or `valve`.
* VALVE_INFRA_NO_PULL: When this variable is set, the infra will not pull containers from the Gitlab CI, recommended for development. See the notes below on the development process. The default is to pull new changes automatically.

Additionally, you may add secrets to the environment file in `./config/private.env`, which will override those specified above,

* `GITLAB_REGISTRATION_TOKEN`: Token for registering new GitLab runners.
* `GITLAB_ACCESS_TOKEN`: Token needed to communicate with the configured GitLab instance.

## Running interactive session on test machines from your development machine

Assuming you already managed to deploy the infrastructure, and Gitlab can use
the runners, you may now want to reproduce issues happening there by getting
interactive access on the test machine that exhibits the issue.

To do so, your development machine will first need to connect to the wireguard
VPN installed on the gateway.

### Generate a public/private key for your development machine

The first step is for you to generate a key for your machine:

    $ wg genkey | (umask 0077 && tee wg-valve-ci.key) | wg pubkey > wg-valve-ci.pub

If you are a Valve CI user, you may then
[fill a request](https://gitlab.freedesktop.org/mupuf/valve-infra/-/issues/new?issue[title]=Wireguard%20peering%20request&issuable_template=Wireguard%20peer&issue[confidential]=true)
for the Valve CI admins to add it to the gateways. Otherwise, check the next sections.

### Add the peer on the gateway side

It is now time to create a merge request that adds the information about the peer in
`ansible/roles/network_setup/templates/wg0.conf.j2`, following this template:

    # <Full name> / <Nickname>: <Email address>
    [Peer]
    PublicKey = <public key>
    AllowedIPs = <next available IP address>/32

Once landed, make sure the changes have been deployed on all the relevant CI
farms, then we need to provide the following information back in the issue:

 * provide the IP address assigned to the client
 * provide the public key / endpoint to all the farms

### Set up the connection on the client side

Now that that the IP has been allocated on the server side, we may create the
wg-quick configuration files that will allow developers to access the CI
network.

For every farm that you want to access, you will need to create a configuration
file in `/etc/wireguard/$farm_name.conf` following this template:

    [Interface]
    Address = <the ip given to your machine by an admin>
    PrivateKey = <content of wg-valve-ci.key>

    [Peer]
    PublicKey = <the public wireguard key of the farm, as given by an admin>
    AllowedIPs = 10.42.0.0/16
    Endpoint = <the IP address / DNS of the farm>:51820

Once the files have been populated, you may connect to a farm by typing:

    $ wg-quick up $farm_name

Check out the output of `sudo wg`, then try pinging `10.42.0.1`. If all went
well, you can now use `executorctl` to run your jobs on any of the test
machines \o/.
