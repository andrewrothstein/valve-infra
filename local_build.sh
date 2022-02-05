#!/bin/bash

container=${1:-all}
tag=${2:-latest}

case $container in
    gitlab-trigger|all)
	echo ">>> Building gitlab-trigger...."
	podman build -t registry.freedesktop.org/mupuf/valve-infra/gitlab-trigger -f containers/gitlab-trigger/Dockerfile .
	;;&
    salad|all)
	echo ">>> Building salad...."
	podman build -t registry.freedesktop.org/mupuf/valve-infra/salad salad/
	;;&
    machine_registration|all)
	echo ">>> Building machine_registration...."
	if [ -z "$IMAGE_NAME" ]; then
	    echo "Set an IMAGE_NAME for the built container"
	    exit 1
	fi
	buildah unshare -- sh .gitlab-ci/machine-registration-container-build.sh
	;;&
    valve-infra|all)
	echo ">>> Building valve-infra...."
	podman build -t registry.freedesktop.org/mupuf/valve-infra -f containers/valve-infra/Dockerfile containers/valve-infra
	;;
esac
