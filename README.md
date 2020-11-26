# Valve CI Infrastructure

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
 * A suitably large *temporary* disk (5G should be enough for a test
     drive), mounted in `/mnt/tmp`.
 * to be start with a provided executable entrypoint script (`entrypoint`)

These settings are configured in the `config/prod.env` file.

## Building the container

If you intend to hack on the project, run the following commands:

    git clone --recurse-submodules git@gitlab.freedesktop.org:mupuf/radv-infra.git
    cd radv-infra
    docker build .

## Working on the project

Update the submodules if external dependencies have changes
    git submodule update --remote --init --recursive

If the submodules get completely messed up (a bit too easy if you're
new to submodules!), follow the steps outlined in https://stackoverflow.com/questions/19508849/how-to-fix-broken-submodule-config-in-git

The follow settings make one persons use of submodules less
error-prone, YMMV,

    git config --global submodule.recurse true
    git config --global push.recurseSubmodules on-demand

And then bring up the services

    docker compose --env-file config/prod.env pull
    docker compose --env-file config/prod.env up

To stop, Ctrl-C, or return to this directory and run `docker compose
--env-file config/prod.env down`.

That's all for now!
