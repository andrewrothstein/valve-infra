#!/bin/bash

container=${1:-all}
tag=${2:-latest}

case $container in
    executor|all)
	echo ">>> Building executor...."
	podman build -t "registry.freedesktop.org/mupuf/valve-infra/executor:$tag" -f executor/Dockerfile executor
	;;&
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
	podman build -t registry.freedesktop.org/mupuf/valve-infra/machine_registration -f machine_registration/Dockerfile .
	;;&
    valve-infra|all)
	echo ">>> Building valve-infra...."
	podman build -t registry.freedesktop.org/mupuf/valve-infra -f containers/valve-infra/Dockerfile containers/valve-infra
	;;
esac
