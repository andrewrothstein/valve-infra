#!/bin/bash
set -ex

# (2022-02) Will be nice to use ci-templates, but we need --entrypoint
# overrides in the container image, which we can't do with that
# project. Couldn't push changes through the CI, and couldn't find
# help from the developer in time, so just hand-roll it until those
# issues are resolved.

buildah_run="buildah run --isolation chroot"
buildah_commit="buildah commit --format docker"

buildcntr=$(buildah from --isolation=chroot debian:bullseye-slim)
buildmnt=$(buildah mount $buildcntr)

mkdir -v $buildmnt/app
cp -ar machine_registration gfxinfo $buildmnt/app/

buildah config --workingdir /app $buildcntr

echo 'path-exclude=/usr/share/doc/*' > $buildmnt/etc/dpkg/dpkg.cfg.d/99-exclude-cruft
echo 'path-exclude=/usr/share/locale/*' >> $buildmnt/etc/dpkg/dpkg.cfg.d/99-exclude-cruft
echo 'path-exclude=/usr/share/man/*' >> $buildmnt/etc/dpkg/dpkg.cfg.d/99-exclude-cruft
echo 'APT::Install-Recommends "false";' > $buildmnt/etc/apt/apt.conf
echo '#!/bin/sh' > $buildmnt/usr/sbin/policy-rc.d
echo 'exit 101' >> $buildmnt/usr/sbin/policy-rc.d
chmod +x $buildmnt/usr/sbin/policy-rc.d

$buildah_run $buildcntr sh -c 'apt update -qyy && apt dist-upgrade -qyy && apt install -qyy python3 python3-pip python3-dev libvulkan-dev mesa-vulkan-drivers gcc'
$buildah_run $buildcntr pip3 install --no-cache-dir -r machine_registration/requirements.txt
$buildah_run $buildcntr pip3 install --no-cache-dir ./gfxinfo
# For production, cache the known PCI devices for into the container
# to avoid external network requirements.
$buildah_run $buildcntr python3 machine_registration/machine_registration.py cache
$buildah_run $buildcntr sh -c 'apt remove -y gcc && apt autoremove -y && apt clean -y && rm -f /var/lib/apt/lists/*.lz4'

if [ -n "$IMAGE_NAME" ]; then
    buildah config --entrypoint '["/app/machine_registration/machine_registration.py"]' --cmd 'register' $buildcntr
    $buildah_commit $buildcntr $IMAGE_NAME
    [ -n "$CI_JOB_TOKEN" ] && [ -n "$CI_REGISTRY" ] && podman login -u gitlab-ci-token -p $CI_JOB_TOKEN $CI_REGISTRY
    extra_podman_args=
    [[ $IMAGE_NAME =~ ^localhost.* ]] && extra_podman_args='--tls-verify=false'
    podman push $extra_podman_args $IMAGE_NAME || true
    sleep 2
    podman push $extra_podman_args $IMAGE_NAME
    if [ -n "$IMAGE_NAME_LATEST" ]; then
        extra_podman_args=
        [[ $IMAGE_NAME_LATEST =~ ^localhost.* ]] && extra_podman_args='--tls-verify=false'
        podman tag "$IMAGE_NAME" "$IMAGE_NAME_LATEST"
        podman push $extra_podman_args $IMAGE_NAME_LATEST || true
        sleep 2
        podman push $extra_podman_args $IMAGE_NAME_LATEST
    fi
fi

buildah unmount $buildcntr
buildah rm $buildcntr
