#!/bin/bash
set -ex

. .gitlab-ci/build_functions.sh

build() {
    buildcntr=$(buildah from --isolation=chroot $BASE_IMAGE)
    buildmnt=$(buildah mount $buildcntr)

    mkdir $buildmnt/valve-infra/
    cp -ar ./valvetraces ./gfxinfo $buildmnt/valve-infra/

    $buildah_run $buildcntr pacman -Suy git python python-pip apitrace gcc-libs cmake gcc automake make xcb-util-keysyms --noconfirm
    $buildah_run $buildcntr pip install /valve-infra/gfxinfo /valve-infra/valvetraces
    $buildah_run $buildcntr git clone --recurse-submodules https://github.com/LunarG/gfxreconstruct
    $buildah_run $buildcntr sh -c "cd gfxreconstruct && cmake . && make -j12 && make install"

    # Clean up
    $buildah_run $buildcntr rm -r /valve-infra gfxreconstruct/
    $buildah_run $buildcntr pacman -Rs cmake gcc automake make xcb-util-keysyms --noconfirm
    $buildah_run $buildcntr pacman -Scc --noconfirm

    buildah config --cmd '["valvetraces", "enroll-traces"]' $buildcntr
}

build_and_push_container
