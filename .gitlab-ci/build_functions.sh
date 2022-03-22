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
}

tag_latest_when_applicable() {
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
		extra_skopeo_args=
		[[ $IMAGE_NAME =~ ^localhost.* ]] && extra_skopeo_args="$extra_skopeo_args --src-tls-verify=false"
		[[ $IMAGE_NAME_LATEST =~ ^localhost.* ]] && extra_skopeo_args="$extra_skopeo_args --dest-tls-verify=false"
		[ -n "$CI_JOB_TOKEN" ] && [ -n "$CI_REGISTRY" ] && skopeo login -u gitlab-ci-token -p $CI_JOB_TOKEN $CI_REGISTRY
		skopeo copy $extra_skopeo_args "docker://$IMAGE_NAME" "docker://$IMAGE_NAME_LATEST"
	fi
}

# This function requires a "build()" function to be defined by the caller ahead of calling this function
build_and_push_container() {
	# Only build the container if it does not already exist
	( skopeo inspect docker://$IMAGE_NAME || true ) | jq '[.Digest, .Layers]' > local_sha
	if [ -s local_sha ]; then
		echo "Container already built"
	else
		# Build the image
		build

		# Push it to the container registry
		if [ -n "$IMAGE_NAME" ]; then
			push_image
		fi

		cleanup
	fi

	# Make sure to tag the current container as latest on master
	if [ -n "$IMAGE_NAME_LATEST" ]; then
		tag_latest_when_applicable
	fi
}
