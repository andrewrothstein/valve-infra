#!/bin/bash

container=${1:-all}
tag=${2:-latest}

case $container in
    machine_registration|all)
	echo ">>> Building machine_registration...."
	if [ -z "$IMAGE_NAME" ]; then
	    echo "Set an IMAGE_NAME for the built container"
	    exit 1
	fi
	buildah unshare -- sh .gitlab-ci/machine-registration-container-build.sh
	;;&
esac
