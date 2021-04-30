#!/bin/bash

set -o pipefail
set -o nounset
set -o xtrace

shopt -s extglob

D="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# TODO: Expose better through the environment?
export PULL_THRU_REGISTRY=10.42.0.1:8002
export REGISTRY=10.42.0.1:8004

# runtime panics have happened within buildah, very rarely, try and catch one for a bit,
# https://github.com/containers/buildah/issues/3130
export BUILDAH="buildah"
export BUILDAH_RUN="$BUILDAH run --isolation chroot"
# No https, since this is an internal service
export BUILDAH_COMMIT="$BUILDAH commit --format docker --tls-verify=false"
export BUILDAH_PUSH="$BUILDAH push --tls-verify=false"
export BUILDAH_FORMAT=docker

# The location of the extra Mesa build artifact
INSTALL=$CI_PROJECT_DIR/install

export MESA_IMAGE_NAME=${MESA_IMAGE#registry.freedesktop.org/}
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
# replace it with CI_JOB_ID, to cache on the built Mesa and job
# environment instead. CI_COMMIT_SHA is not what you want, since
# multiple jobs for the same commit will overwrite the environment
# variables.
export LOCAL_CONTAINER_NAME=${MESA_IMAGE_NAME/%${MESA_TEMPLATES_COMMIT}/${CI_JOB_ID}}
export LOCAL_CONTAINER="10.42.0.1:8004/${LOCAL_CONTAINER_NAME}"

# The built Mesa artifact is uploaded to the upstream Minio instance,
# since it's in a previous stage and wasn't carried as an artifact to
# us, it must be fetched over the network rather than being in our
# build context.
export MESA_URL="https://${MINIO_HOST}/artifacts/${CI_PROJECT_PATH}/${CI_PIPELINE_ID}/mesa-${ARCH}.tar.gz"

env

CONTAINER_EXISTS=
if skopeo inspect --tls-verify=false docker://$LOCAL_CONTAINER ; then
     # If we require getting more fancy with the cache checks, consider
     # something along these lines,
     #   skopeo inspect docker://$LOCAL_CONTAINER | jq '[.Digest, .Layers]' > local_sha
     echo "LOCAL_CONTAINER ($LOCAL_CONTAINER) has already been built and stored into the local registry"
     CONTAINER_EXISTS=yes
fi

test_container=$($BUILDAH from "docker://$MESA_IMAGE") || exit 1
test_container_mount=$($BUILDAH mount $test_container) || exit 1

# Collect up the environment from the job that is of use to the test
# payload. This would ideally be an environment file, sourced by the
# entrypoint before the test runs, instead it's attached somewhat
# oddly to the OCI environment, since the buildah tools don't support
# (at the time of writing) sourcing the environment from a file, only
# via command line arguments.
set +o xtrace
CONTAINER_ENV_PARAMS=""
# Pass through relevant env vars from the gitlab job to the test container
for var in \
    B2C_JOB_SUCCESS_REGEX \
    B2C_JOB_WARN_REGEX \
    B2C_START_XORG \
    B2C_TEST_SCRIPT \
    CI_COMMIT_BRANCH \
    CI_COMMIT_TITLE \
    CI_JOB_ID \
    CI_JOB_JWT \
    CI_JOB_URL \
    CI_MERGE_REQUEST_SOURCE_BRANCH_NAME \
    CI_MERGE_REQUEST_TITLE \
    CI_NODE_INDEX \
    CI_NODE_TOTAL \
    CI_PAGES_DOMAIN \
    CI_PIPELINE_ID \
    CI_PROJECT_NAME \
    CI_PROJECT_PATH \
    CI_PROJECT_ROOT_NAMESPACE \
    CI_RUNNER_DESCRIPTION \
    CI_SERVER_URL \
    DEQP_CASELIST_FILTER \
    DEQP_CONFIG \
    DEQP_EXPECTED_RENDERER \
    DEQP_FRACTION \
    DEQP_HEIGHT \
    DEQP_NO_SAVE_RESULTS \
    DEQP_PARALLEL \
    DEQP_RESULTS_DIR \
    DEQP_RUNNER_OPTIONS \
    DEQP_VARIANT \
    DEQP_VER \
    DEQP_WIDTH \
    DEVICE_NAME \
    DRIVER_NAME \
    EGL_PLATFORM \
    FDO_CI_CONCURRENT \
    FDO_UPSTREAM_REPO \
    FD_MESA_DEBUG \
    FLAKES_CHANNEL \
    GPU_VERSION \
    IR3_SHADER_DEBUG \
    MESA_GL_VERSION_OVERRIDE \
    MESA_GLSL_VERSION_OVERRIDE \
    MESA_GLES_VERSION_OVERRIDE \
    MINIO_HOST \
    NIR_VALIDATE \
    PIGLIT_HTML_SUMMARY \
    PIGLIT_JUNIT_RESULTS \
    PIGLIT_OPTIONS \
    PIGLIT_PLATFORM \
    PIGLIT_PROFILES \
    PIGLIT_REPLAY_ARTIFACTS_BASE_URL \
    PIGLIT_REPLAY_DESCRIPTION_FILE \
    PIGLIT_REPLAY_DEVICE_NAME \
    PIGLIT_REPLAY_EXTRA_ARGS \
    PIGLIT_REPLAY_REFERENCE_IMAGES_BASE_URL \
    PIGLIT_REPLAY_UPLOAD_TO_MINIO \
    PIGLIT_RESULTS \
    PIGLIT_TESTS \
    TEST_LD_PRELOAD \
    TU_DEBUG \
    VALVE_TRACES_FILTERS \
    VALVE_TRACES_OPTIONS \
    VK_CPU \
    VK_DRIVER \
    ; do
  if [ -n "${!var+x}" ]; then
    CONTAINER_ENV_PARAMS="$CONTAINER_ENV_PARAMS --env $var=${!var@Q}"
  fi
done
eval $(
    set +o xtrace
    echo $BUILDAH config \
	 --workingdir $CI_PROJECT_DIR \
	 $CONTAINER_ENV_PARAMS \
	 --env HOME=$CI_PROJECT_DIR \
	 --env LD_LIBRARY_PATH="$INSTALL/lib/" `# Set up the driver environment.` \
	 --env VK_ICD_FILENAMES="$INSTALL/share/vulkan/icd.d/${VK_DRIVER}_icd.x86_64.json" `# Set the Vulkan driver to use.` \
	 $test_container
    set -o xtrace)

# Setup the entrypoint based on the job variables
$BUILDAH config \
	--cmd '['\"$B2C_TEST_SCRIPT\"']' \
	$test_container || exit 1

if [ -z "$CONTAINER_EXISTS" ]; then
    # If this is first time building the internal container, fetch the
    # Mesa artifact and place it into the container so that it becomes
    # a self-contained test-workload.
    $BUILDAH_RUN $test_container env DEBIAN_FRONTEND=noninteractive apt-get update
    $BUILDAH_RUN $test_container env DEBIAN_FRONTEND=noninteractive apt-get install -y curl
    $BUILDAH_RUN $test_container bash -c "curl $MESA_URL | tar xzf -"
fi

$BUILDAH_COMMIT $test_container $LOCAL_CONTAINER || exit 1

# Pushing may fail, apparently. I (cturner) have never seen it fail,
# but I have seen other race conditions in these tools, so be
# defensive. Approach taken from,
# https://gitlab.freedesktop.org/freedesktop/ci-templates/-/blob/master/templates/debian.yml#L510
# Podman isn't used because it's a heavy (~250MB) dependency for the
# container and buildah seems to perform this task just fine.
$BUILDAH_PUSH $LOCAL_CONTAINER || sleep 2 && $BUILDAH_PUSH $LOCAL_CONTAINER || exit 1
$BUILDAH unmount $test_container || exit 1

# And now build and submit the test job
cat <<EOF > job.yml
version: 1

# Rules to match for a machine to qualify
target:
  tags: [$CI_RUNNER_TAGS]

timeouts:
  first_console_activity:  # This limits the time it can take to receive the first console log
    minutes: 5
    retries: 0
  console_activity:  # Reset every time we receive a message from the logs
    minutes: 1
    retries: 0
  overall:           # Maximum time the job can take, not overrideable by the "continue" deployment
    hours: 4
    retries: 0
    # no retries possible here

console_patterns:
    session_end:
        regex: "^.*It's now safe to turn off your computer\r$"
    job_success:
        regex: $B2C_JOB_SUCCESS_REGEX
    job_warn:
      regex: $B2C_JOB_WARN_REGEX

# Environment to deploy
deployment:
  # Initial boot
  start:
    kernel:
      url: "http://10.42.0.1:9000/boot/default_kernel"
      cmdline:
        - b2c.container="-ti --tls-verify=false docker://${PULL_THRU_REGISTRY}/mupuf/valve-infra/machine_registration:latest check"
        - b2c.ntp_peer="10.42.0.1" b2c.pipefail b2c.cache_device=auto b2c.poweroff_delay=15
        - b2c.container="-v ${CI_JOB_ID}-results:${CI_PROJECT_DIR}/results --tls-verify=false docker://$LOCAL_CONTAINER"
        - b2c.post_container="-v ${CI_JOB_ID}-results:/results -e CI_JOB_ID=${CI_JOB_ID} --tls-verify=false docker://${PULL_THRU_REGISTRY}/mupuf/valve-infra/artifact-reaper:latest"
        - console={{ local_tty_device }},115200 earlyprintk=vga,keep SALAD.machine_id={{ machine_id }}
        - loglevel=6

    initramfs:
      url: "http://10.42.0.1:9000/boot/default_boot2container.cpio.xz"
EOF

set +x
echo "=========== JOB YAML ================="
cat job.yml
echo "=========== END OF JOB YAML ==========="
set -x

python3 $D/client.py -w run job.yml
job_result=$?

mkdir -pv results
curl -o- http://10.42.0.1:9000/jobs/${CI_JOB_ID}-artifacts.tgz | tar zxf - -C results

exit $job_result
