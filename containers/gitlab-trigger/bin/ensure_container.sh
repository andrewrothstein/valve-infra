#!/bin/bash

set -e
set -x

# TODO: Expose better through the environment?
B2C_PULL_THRU_REGISTRY=10.42.0.1:8002
B2C_NTP_PEER=10.42.0.1
__REGISTRY=10.42.0.1:8004

# This must be a host mounted directory so it's shared with other
# runners/jobs. By now, we abuse the containers volume.
__SHARED_CONTAINER_DIR="/var/lib/containers"
__COMMON_PATH="${CI_PIPELINE_ID}-${MESA_IMAGE_PATH/\//-}"

# runtime panics have happened within buildah, very rarely, try and
# catch one for a bit,
# https://github.com/containers/buildah/issues/3130
__BUILDAH="buildah"
# No https, since this is an internal service
__BUILDAH_COMMIT="$__BUILDAH commit --format docker --tls-verify=false"
__BUILDAH_PUSH="$__BUILDAH push --tls-verify=false"

__MESA_IMAGE_NAME=${MESA_IMAGE#${CI_REGISTRY_IMAGE}/}
# It's a bit opaque how image tagging happens in the Mesa CI, but
# basically the format of MESA_IMAGE is one of,
#
#  MESA_IMAGE: "$CI_REGISTRY_IMAGE/${MESA_IMAGE_PATH}:${MESA_IMAGE_TAG}--${MESA_TEMPLATES_COMMIT}"
#  MESA_IMAGE: "$CI_REGISTRY_IMAGE/${MESA_IMAGE_PATH}:${MESA_IMAGE_TAG}--${MESA_BASE_TAG}--${MESA_TEMPLATES_COMMIT}"
#
# The length of these tags can creep up to the spec limits of 128
# characters quite easily if extra cache tags are appeneded. In this
# use-case, it is needed to add a further level of cache tagging,
# namely the Mesa commit being internally bundled in the local
# container. For internal registry caching, MESA_TEMPLATES_COMMIT is
# not useful since it doesn't change as often as the Mesa commit,
# replace it with CI_PIPELINE_ID, to cache on the built Mesa and job
# environment instead. CI_COMMIT_SHA is not what you want, since
# multiple jobs for the same commit will overwrite the environment
# variables.
__PIPELINE_CONTAINER_NAME=${__MESA_IMAGE_NAME/%${MESA_TEMPLATES_COMMIT}/pipe-${CI_PIPELINE_ID}}
__PIPELINE_CONTAINER="${__REGISTRY}/${__PIPELINE_CONTAINER_NAME}"
__JOB_CONTAINER_NAME=${__MESA_IMAGE_NAME/%${MESA_TEMPLATES_COMMIT}/job-${CI_JOB_ID}}
__JOB_CONTAINER="${__REGISTRY}/${__JOB_CONTAINER_NAME}"

# The built Mesa artifact is uploaded to the upstream Minio instance,
# since it's in a previous stage and wasn't carried as an artifact to
# us, it must be fetched over the network rather than being in our
# build context.
__MESA_URL="https://${MINIO_HOST}/artifacts/${CI_PROJECT_PATH}/${CI_PIPELINE_ID}/mesa-${ARCH}.tar.gz"

env

echo "export B2C_PULL_THRU_REGISTRY=${B2C_PULL_THRU_REGISTRY@Q}" > envvars
echo "export B2C_NTP_PEER=${B2C_NTP_PEER@Q}" >> envvars
echo "export B2C_LOCAL_CONTAINER=${__JOB_CONTAINER@Q}" >> envvars

# Get the job submit template and generator
wget "$CI_PROJECT_URL/-/raw/$CI_COMMIT_SHA/.gitlab-ci/b2c/b2c.yml.jinja2.jinja2"
wget "$CI_PROJECT_URL/-/raw/$CI_COMMIT_SHA/.gitlab-ci/b2c/generate_b2c.py"
chmod +x generate_b2c.py


__SKOPEO_TIMEOUT=15

function check_container() {
    if skopeo inspect --format "Name: {{.Name}} Digest: {{.Digest}}" --command-timeout ${__SKOPEO_TIMEOUT}s --tls-verify=false "docker://$1" ; then

        echo "The container $1 has already been built and stored into" \
             "the local registry"

        return 0
    fi

    return 1
}

function pipeline_container() {
    # Fetch the Mesa artifacts and place them into the container so
    # that it becomes a self-contained test-workload.
    mkdir -p "${2}${CI_PROJECT_DIR}"
    pushd "${2}${CI_PROJECT_DIR}"
    wget -O - $__MESA_URL | tar xzf -
    popd
}

function job_container() {
    set +o xtrace
    for var in $B2C_ENV_VARS $B2C_FIXED_ENV_VARS; do
        if [ -n "${!var+x}" ]; then
            __CONTAINER_ENV_VARS="$__CONTAINER_ENV_VARS --env $var=${!var@Q}"
        fi
    done
    set -o xtrace

    eval $(
        echo $__BUILDAH config \
	     --workingdir $CI_PROJECT_DIR \
	     --env HOME=$CI_PROJECT_DIR \
	     $__CONTAINER_ENV_VARS \
	     "$1")

    # Setup the entrypoint based on the job variables
    $__BUILDAH config \
	     --cmd '['\"$B2C_TEST_SCRIPT\"']' \
	     "$1"
}

function build_container() {
    __TEST_CONTAINER=$($__BUILDAH from "docker://$1")
    __TEST_CONTAINER_MOUNT=$($__BUILDAH mount $__TEST_CONTAINER)

    $3 "$__TEST_CONTAINER" "$__TEST_CONTAINER_MOUNT"

    $__BUILDAH_COMMIT $__TEST_CONTAINER "$2"

    # Pushing may fail, apparently. I (cturner) have never seen it
    # fail, but I have seen other race conditions in these tools, so
    # be defensive. Approach taken from,
    # https://gitlab.freedesktop.org/freedesktop/ci-templates/-/blob/master/templates/debian.yml#L510
    # Podman isn't used because it's a heavy (~250MB) dependency for
    # the container and buildah seems to perform this task just fine.
    $__BUILDAH_PUSH "$2" || sleep 2 && $__BUILDAH_PUSH "$2"
    $__BUILDAH unmount $__TEST_CONTAINER
}

__LOCK_FILE="${__SHARED_CONTAINER_DIR}/${__COMMON_PATH}.lock"

while [ true ]; do
    __RESULT=0
    check_container "$__PIPELINE_CONTAINER" || __RESULT=$?
    if [ $__RESULT -eq 0 ]; then
        break
    fi

    # Locking mechanism to avoid race condition
    __TMP_FILE=$(mktemp -p "$__SHARED_CONTAINER_DIR" "${__COMMON_PATH}-${CI_JOB_ID}-XXXXXX.tmp")

    # If we cannot link, we were beaten by some other job. Skip
    # building the container ...
    if `ln "$__TMP_FILE" "$__LOCK_FILE"`; then
        # Make sure the lock will be cleaned.
        trap "`/usr/bin/printf %q \"rm -f ${__LOCK_FILE@Q}\"`" EXIT

        rm -f "$__TMP_FILE"

        build_container "$MESA_IMAGE" "$__PIPELINE_CONTAINER" pipeline_container
        # Before continuing, give enough time to all the opened skopeo
        # inspects to timeout and wait for the release of the lock.
        sleep $((__SKOPEO_TIMEOUT + 5))

        rm -f "$__LOCK_FILE"
        trap - EXIT
    else
        rm -f "$__TMP_FILE"

        # ... unless after 5min. waiting, the container has not been
        # built correctly.
        __RESULT=0
        inotifywait -e ATTRIB -t 300 "$__LOCK_FILE" || __RESULT=$?

        if [ $__RESULT -eq 2 ]; then
            # Timed out!
            # Let's clean the lock before trying again.
            rm -f "$__LOCK_FILE"
        elif [ $__RESULT -ne 0 ]; then
            # This shouldn't ever happen.
            exit 1
        fi
    fi
done

check_container "$__JOB_CONTAINER" && exit 0

build_container "$__PIPELINE_CONTAINER" "$__JOB_CONTAINER" job_container
