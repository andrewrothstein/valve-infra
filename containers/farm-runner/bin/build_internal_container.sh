#!/bin/bash

set -o errexit
set -o pipefail
set -o nounset
set -o xtrace

# runtime panics have happened within buildah, very rarely, try and catch one for a bit,
# https://github.com/containers/buildah/issues/3130
export BUILDAH="buildah --debug"
export BUILDAH_RUN="$BUILDAH run --isolation chroot"
# No https, since this is an internal service
export BUILDAH_COMMIT="$BUILDAH commit --format docker --tls-verify=false"
export BUILDAH_PUSH="$BUILDAH push --tls-verify=false"
export BUILDAH_FORMAT=docker

export MESA_IMAGE_NAME=${MESA_IMAGE#registry.freedesktop.org/}
export LOCAL_CONTAINER="10.42.0.1:8004/$MESA_IMAGE_NAME"
export MESA_URL="https://${MINIO_HOST}/artifacts/${CI_PROJECT_PATH}/${CI_PIPELINE_ID}/mesa-${ARCH}.tar.gz"

env

# TODO: Caching.
# We'll always need to at least change the container environment to
# match the job environment. For instance, changing DEQP_FRACTION
# after the container is built
# The fetch of Mesa and such can probably be saved by skopeo
# inspecting the local container, as below, and bailing early if it
# has already been built

CONTAINER_EXISTS=
if skopeo inspect --tls-verify=false docker://$LOCAL_CONTAINER ; then
     # If we require getting more fancy with the cache checks, consider
     # something along these lines,
     #   skopeo inspect docker://$LOCAL_CONTAINER | jq '[.Digest, .Layers]' > local_sha
     echo "LOCAL_CONTAINER ($LOCAL_CONTAINER) has already been built and stored into the local registry"
     CONTAINER_EXISTS=yes
     # Despite this, we still should fetch the job environment, since
     # this could have changed run to run, regardless of the SHAs.
fi

test_container=$($BUILDAH from "docker://$MESA_IMAGE")
test_container_mount=$($BUILDAH mount $test_container)

set +o xtrace
CONTAINER_ENV_PARAMS=""
# Pass through relevant env vars from the gitlab job to the test container
for var in \
    BARE_METAL_TEST_SCRIPT \
    BM_KERNEL_MODULES \
    BM_START_XORG \
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
    VK_CPU \
    VK_DRIVER \
    ; do
  if [ -n "${!var+x}" ]; then
    CONTAINER_ENV_PARAMS="$CONTAINER_ENV_PARAMS --env $var=${!var@Q}"
  fi
done
set -o xtrace

INSTALL=$CI_PROJECT_DIR/install

# Make the environment friendly to testing
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
	--cmd '['\"$TEST_ENTRYPOINT\"']' \
	$test_container

if [ -n "$CONTAINER_EXISTS" ]; then
    # Fetch the Mesa artifact and place it into the container so that
    # it becomes a self-contained test-workload.
    $BUILDAH_RUN $test_container env DEBIAN_FRONTEND=noninteractive apt-get update
    $BUILDAH_RUN $test_container env DEBIAN_FRONTEND=noninteractive apt-get install -y curl
    $BUILDAH_RUN $test_container bash -c "curl $MESA_URL | tar xzf -"
fi

$BUILDAH_COMMIT $test_container $LOCAL_CONTAINER

# Pushing may fail, apparently. I (cturner) have never seen it fail,
# but I have seen other race conditions in these tools, so be
# defensive. Approach taken from,
# https://gitlab.freedesktop.org/freedesktop/ci-templates/-/blob/master/templates/debian.yml#L510
# Podman isn't used because it's a heavy (~250MB) dependency for the
# container and buildah seems to perform this task just fine.
$BUILDAH_PUSH $LOCAL_CONTAINER || true
sleep 2
$BUILDAH_PUSH $LOCAL_CONTAINER

$BUILDAH unmount $test_container

