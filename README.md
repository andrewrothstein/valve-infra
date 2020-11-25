# RADV CI Infrastructure

This repository is containing the source for the radv CI infrastructure. It is
meant to be run by using the [simple ci gateway]() component which simply
boots a docker container after setting up the network interfaces.

This project generates a container that will use docker-compose to run the
different services. The different services should be their own project, and
imported in this project using git submodules. This forces developers to think
about defining good interfaces, which simplifies pre-merge testing and
improvements in the farm.

## Requirements

To operate, this container requires:

 * two network interfaces, named:
   * public: connected to the internet;
   * private: connected to the devices under test, through a switch. No IP necessary.
 * to be run with the following command: `/usr/bin/docker run --privileged -v /var/run/docker.sock:/var/run/docker.sock --net host registry.freedesktop.org/mupuf/radv-infra`

## Building the container

If you intend to hack on the project, run the following commands:

    git clone --recurse-submodules git@gitlab.freedesktop.org:mupuf/radv-infra.git
    cd radv-infra
    docker build .

That's all for now!
