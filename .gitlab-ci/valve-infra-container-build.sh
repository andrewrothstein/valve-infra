#!/bin/bash

set -ex

buildah_run="buildah run --isolation chroot"
buildah_commit="buildah commit --format docker"

buildcntr=$(buildah from -v `pwd`:/app/valve-infra --dns=none --isolation=chroot $BASE_IMAGE)
buildmnt=$(buildah mount $buildcntr)

buildah config --workingdir /app/valve-infra/ansible $buildcntr

$buildah_run $buildcntr sh -c 'env LC_ALL=C pacman -Qi' | awk '/^Name/{name=$3} /^Installed Size/{print $4$5, name}' | sort -h
$buildah_run $buildcntr du -h -d 3 /usr /etc /app | sort -h
$buildah_run $buildcntr du -h /usr/lib/python3.10/site-packages | sort -h

# The Gitlab runner cache deliberately chmod 777's all
# directories. This upsets ansible and there's nothing we can
# really do about it in our repo. See
# https://gitlab.com/gitlab-org/gitlab-runner/-/issues/4187
$buildah_run $buildcntr chmod -R o-w /app/valve-infra/ansible
$buildah_run $buildcntr ansible-lint --version
$buildah_run $buildcntr ansible-lint -f plain
$buildah_run $buildcntr ansible-playbook --syntax-check gateway.yml
$buildah_run $buildcntr ansible-playbook $ANSIBLE_EXTRA_ARGS ./gateway.yml -l localhost

if [ -n "$IMAGE_NAME" ]; then
    buildah config --entrypoint /bin/init $buildcntr
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
