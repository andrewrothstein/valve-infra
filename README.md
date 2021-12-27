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

## Working on the project

The infra is organised into separate components, expressed as containers. If you need to work on one component, it's the familiar workflow you'd use for any container-based project. Here's a crib sheet to help out.

To build the gitlab-sync container individually,

    ./local_build.sh <container_name>

To build all the containers used by the infrastrucuture,

    ./local_build.sh

To run the tests for a container, the process is not as automated as
we'd like, being project specific, but generally it's based on
docker-compose. For example, to run the executor tests,

    docker-compose --env ./config/prod.env run --rm --entrypoint=bash executor
    executor # pip install pytest
    executor # PYTHONPATH=. pytest -v

And so on...

If you wish to integration test the changes, start the whole infra, and then do `docker stop app_gitlab_sync_1`, for example. You may then bring up your in-development component to test it within the infra. Use `VALVE_INFRA_NO_PULL=1` to stop the default behaviour to pulling upstream containers from the CI.

The same pattern can be used for other containers in the project. See the `.gitlab-ci.yml` and `docker-compose.yml` for the per-component details.
