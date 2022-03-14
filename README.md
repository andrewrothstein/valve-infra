# Valve CI Infrastructure

This repository contains the source for the Valve CI
infrastructure. Its main purpose is to build a multi-service
container that acts as a bare-metal CI gateway service, responsible
for the orchestration and management of devices under test, or DUTs as
we call them. *NOTE:* We plan to move away from a nested-container
approach, instead of the services running as containers within the
parent valve-infra container, they will run as systemd managed
daemons. The churn is due to a long-running move away from a
multi-service architecture. This will simplify deployment and
maintenance further.

## Requirements (TODO)
The Valve Infra container is meant to be run on the gateway machine of
a CI farm, and comes with the following requirements:

 - Hardware: Two network interfaces, one connected to the internet while the other one is connected to a switch where
   all the test machines to be exposed by the gateway are connected.
 - Volumes: The container requires a volume to store persistent data (mounted at /mnt/permanent), and optionally a
   temporary volume which acts as a cache across reboots (mounted at /mnt/tmp).
 - Container: The container needs to be run as privileged, and using the host network

*TODO:* we now boot in production indirectly via an iPXE boot server
(see the `ipxe-boot-server/` subproject). The following is
out-of-date. Explain.

## Hacking on the infrastructure

Provided that you satisfy the hardware requirement, the container can thus be run like so:

    # podman volume create perm
    # podman volume create tmp
    # podman run --privileged --network=host -v tmp:/mnt/tmp -v perm:/mnt/permanent --tls-verify=false --entrypoint=/bin/init docker://registry.freedesktop.org/mupuf/valve-infra/valve-infra:latest

*NOTE:* This could do nasty things to your host environment, due to
its privileged status. It is recommended to keep reading for tips on
running it all in a virtual and production environment. This is
however the general idea of the deployment.

## Building

The container image is provisioned using Ansible recipes (see the
`ansible/` subproject).

To build the container,

	make IMAGE_NAME=localhost:8088/mupuf/valve-infra/valve-infra-$(whoami):latest valve-infra-container

Build options

  - `V=1` - Turn on more verbose logging messages in the build process
  - `EXTRA_ANSIBLE_FLAGS="-vvv ..."` - Pass any custom flags to
    `ansible-playbook`. Helpful for re-running only tagged roles in
    the ansible build, for example.
  - `EXTRA_ANSIBLE_VARS="private_interface=brian ..."` -
    The ansible playbook for the gateway container has a number of
    configuration variables. You may override/specify them using this
    Makefile argument. TODO: We may be better served using Ansible to
    build the container directly, rather than using Podman to build
    from a Dockerfile, which indirectly uses ansible.
  - `IMAGE_NAME=localhost:8088/mupuf/valve-infra/valve-infra-$(whoami):latest` -
    The container name to tag the image with. *WARNING:* The image
    will automatically be pushed to the registry that got tagged!

Once completed, a container image will be generated, for example,

    Successfully tagged localhost:8088/mupuf/valve-infra/valve-infra-cturner:latest
    60cc3db9bedd2a11d8d61a4433a2a8e8daf35a59d6229b80c1fdcf9ece73b7ab

Notice it defaults to a `localhost` registry. This is to save on
bandwidth (the valve-infra container is too big).

# Virtual deployment (for local testing)

To test a built container image, first start a local registry to host
it, this will save round-trips to an external registry, the container
is too big,

    podman run --rm -p 8088:5000  --name registry docker.io/library/registry:2

The other testing dependency we need a virtual PDU, start that service
on the host like so,

	make PORT=9191 vpdu

*TODO:* This might make more sense to be pre-configured inside the
container, but then you need to bundle QEMU (not a huge deal), and
worry about X11 forwarding from QEMU to the host if you wish to see a
graphical QEMU window, which can be handy. WIP.

Push the container for validation,

    podman push --tls-verify=false localhost:8088/mupuf/valve-infra/valve-infra-$(whoami):latest

Now, run a virtual gateway machine, which will boot directly into this container,

	make REGISTRY=10.0.2.2:8088 CONTAINER=mupuf/valve-infra/valve-infra-$(whoami):latest FARM_NAME=$(whoami)-test GITLAB_REGISTRATION_TOKEN=... GITLAB_URL=https://gitlab.freedesktop.org vivian

*TODO: make GITLAB_REGISTRATION_TOKEN/GITLAB_URL optional*

Note: options to vivian can be passed by setting `VIVIAN_OPTS`, for example:

	make VIVIAN_OPTS="--ssh-id=~/.ssh/foo" ... vivian

The virtual testing recipes will fetch a Linux kernel and a
boot2container ramdisk, and start the system. After the kernel boots
and loads the ramdisk, the ramdisk will then pull the valve-infra
container, and hand control to it.

**N.B:** The `REGISTRY` is given as `10.0.2.2`, this is the "slirp"
interface provided by QEMU, through which host services can be
contacted inside the VM.

**N.B:** Due to the stateful nature of the permanent partition in the
VM's tmp disk, it is wise to occasionally delete said disk and check
a fresh boot continues to work as expected.

*TODO:* Drop vivian as a side-project, integrate its testing
dependencies directly into the container image.

Once the VM is up, open SSH connections like so,

	make vivian-connect

A good place to start for now is to watch `journalctl -f` and check
everything looks OK. A dashboard is WIP.

After making changes to Ansible, it's useful to sync them to a running
VM and check the desired changes were made. To replay the entire
gateway playbook against the VM,

	make FARM_NAME=$(whoami)-farm vivian-provision

Or just the items tagged dashboard and minio,

	make FARM_NAME=$(whoami)-farm TAGS=dashboard,minio vivian-provision

*TODO:* There is a script to setup a `tmux` session, with all the
service dependencies started and a personal development environment,

 - `./tools/vivian-tmux.sh`

This will start a tmux dashboard with several panes showing the status
of the virtual infrastructure. Pane 1 contains a shell to the virtual
gateway. Switch to it using `Ctrl+b 1` (or whatever your tmux prefix
key is). You can now validate a couple of things,

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

Finally, you may queue jobs in Vivian using:

	executorctl -e http://localhost:8000 run -t virtio:family:VIRTIO $JOB_FILE

Congratulations! You seem to have a functional setup! Most of the
steps above are amenable to further configuration. You are now in a
position to play around and modify defaults to your testing
requirements.

Other notes,

 - Press `Ctrl-b c` to start a new shell in the dashboard.
 - `make clean` removes all the files created for the test environment.


## Production deployment

*TODO:* Revisit this when we complete the MVP.

--------------------

Running the infrastructure with the following command:

    docker run --privileged --network=host --rm -it -v $(pwd):/app -v /var/run/docker.sock:/var/run/docker.sock -v /mnt:/mnt registry.freedesktop.org/mupuf/valve-infra

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
