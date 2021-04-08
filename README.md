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

    git clone --recurse-submodules git@gitlab.freedesktop.org:mupuf/valve-infra.git
    cd valve-infra
    docker build -t registry.freedesktop.org/mupuf/valve-infra .

## Deploying the infrastructure

Running the infrastructure with the following command:

    docker run --privileged --network=host --rm -it -v $(pwd):/app -v /var/run/docker.sock:/var/run/docker.sock -v /mnt:/mnt registry.freedesktop.org/mupuf/valve-infra

The project is voluntarily light on configuration options as it
strives for auto-configuration as much as possible. However, it is
possible to override the following parameters by setting the following
environment variables (which all have good defaults),

* DNS_SERVER: Needed by the power cutter to resolve the PDUs' IP address. This
  requirement will soon disapear. Defaults to `10.0.0.6`;
* TMP_MOUNT: The place where large, transient files can be stored. NFS roots
  use this area. General scratch space. Defaults to `/mnt/tmp`. If you change
  this, make sure you pass the right mount point into the container.
* PERMANENT_MOUNT: The place to store files that should persist across reboots
  (configuration files, tiny databases, ...). Defaults to `/mnt/persistent`.
  If you change this, make sure you pass the right mount point into the container.
* PRIVATE_INTERFACE: The name of the network interface connected to private
  network. Defaults to `private`.

Additionally, you may add secrets to the environment file in `./config/private.env`, which will override those specified above,

* `GITLAB_REGISTRATION_TOKEN`: Token for registering new GitLab runners.
* `GITLAB_ACCESS_TOKEN`: Token needed to communicate with the configured GitLab instance.

## Working on the project

To build the gitlab-sync container individually,

docker buildx build -t registry.freedesktop.org/mupuf/valve-infra/gitlab-sync containers/gitlab-sync  --load

To run from a shell:

    docker run --env-file ./config/prod.env --rm -it -v $(pwd)/containers/gitlab-sync:/app -v /mnt/tmp/gitlab-runner:/etc/gitlab-runner --entrypoint=bash registry.freedesktop.org/mupuf/valve-infra/gitlab-sync
	
The same pattern can be used for other containers in the project. See the `.gitlab-ci.yml` for the details.
