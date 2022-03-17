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
		# Pushing a new :latest tag should only happen when:
		# 1) when running locally (where $CI is unset)
		# 2) CI pipelines on the "default" branch of the project ($CI_COMMIT_BRANCH is set AND equal to CI_DEFAULT_BRANCH)
		tag_latest=false

		if [ -z "$CI" ]; then
			# running locally
			tag_latest=true
		elif [ -n "$CI_COMMIT_BRANCH" ] && [ "$CI_COMMIT_BRANCH" = "$CI_DEFAULT_BRANCH" ]; then
			# running on the default branch. CI_COMMIT_BRANCH is *not* set in MRs
			tag_latest=true
		fi

		if $tag_latest; then
			extra_podman_args=
			[[ $IMAGE_NAME_LATEST =~ ^localhost.* ]] && extra_podman_args='--tls-verify=false'
			podman tag "$IMAGE_NAME" "$IMAGE_NAME_LATEST"
			podman push $extra_podman_args $IMAGE_NAME_LATEST || true
			sleep 2
			podman push $extra_podman_args $IMAGE_NAME_LATEST
		fi
	fi
}
