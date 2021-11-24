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
    # podman run --privileged --network=host -v tmp:/mnt/tmp -v perm:/mnt/permanent --tls-verify=false --entrypoint=/bin/init docker://registry.freedesktop.org/mupuf/valve-infra/valve-infra-containerized:latest

For development purposes, it is advised to run the container in a virtual machine. For ease of use, a Makefile is
provided to set up your test environment:

 - `make` or `make test`: start the qemu instance
 - `make connect`: Connect via SSH (requires the public key to be already known)
 - `make clean`: removes all the files created for the test environment

NOTE: Systemd will try to take over the current console at boot. To see the infrastructure's dashboard, just press
CTRL+F2. This will be addressed in a future series.

## Walk through

The valve-infra container is systemd-based. You will find the following services:

 - infra.service: The main service, which calls /app/entrypoint.
 - sshd.service: For allowing ssh connections. Make sure to add your ssh key to rootfs/root/.ssh/authorized_keys and get
   the container rebuilt/pushed.
 - podman.service: For docker-compose emulation, which will soon be made irrelevant.

## Local testing

To test this container, follow the following steps:

 - $ podman login registry.freedesktop.org
 - $ cd containers/valve-infra
 - $ podman build -t registry.freedesktop.org/mupuf/valve-infra/valve-infra-$USER .
 - $ podman push registry.freedesktop.org/mupuf/valve-infra/valve-infra-$USER
 - $ make test CONTAINER=valve-infra-$USER
 - In the QEMU window that got created, wait for the login screen
 - Press CTRL+F2 to switch to tty2, a dashboard should show the current state of the infra
 - Press CRTL+F3 to switch to tty3, type root, and you should be ready to work!

WARNING: powering off the machine does not currently work, for reasons that are still being investigated. Just kill
qemu when you are done!
