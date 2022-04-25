#!/bin/bash
set -ex

. .gitlab-ci/build_functions.sh

build() {
    buildcntr=$(buildah from --isolation=chroot docker://telegraf:alpine)
    buildmnt=$(buildah mount $buildcntr)

    cp -a .gitlab-ci/telegraf.conf $buildmnt/etc/telegraf/
    cp -a .gitlab-ci/telegraf-extra-inputs.sh $buildmnt/usr/local/bin/telegraf-extra-inputs.sh

    $buildah_run $buildcntr apk --no-cache add smartmontools nvme-cli

    buildah config --entrypoint '["telegraf"]' $buildcntr
}

build_and_push_container
