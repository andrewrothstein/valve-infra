#!/bin/bash
set -ex

. .gitlab-ci/build_functions.sh

build() {
    buildcntr=$(buildah from --isolation=chroot docker://telegraf:alpine)
    buildmnt=$(buildah mount $buildcntr)

    cp -ar .gitlab-ci/telegraf.conf $buildmnt/etc/telegraf/

    $buildah_run $buildcntr apk --no-cache add smartmontools nvme-cli

    buildah config --entrypoint '["telegraf"]' $buildcntr
}

build_and_push_container
