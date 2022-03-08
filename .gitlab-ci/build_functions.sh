#!/bin/bash
set -e

buildah_run="buildah run --isolation chroot"
buildah_commit="buildah commit --format docker"


cleanup() {
	buildah unmount $buildcntr
	buildah rm $buildcntr
}

push_image() {
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
}
