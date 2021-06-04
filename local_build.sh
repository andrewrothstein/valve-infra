#!/bin/bash

container=${1:-all}

case $container in
    executor|all)
	echo ">>> Building executor...."
	docker build -t registry.freedesktop.org/mupuf/valve-infra/executor -f executor/Dockerfile .
	;;&
    gitlab-trigger|all)
	echo ">>> Building gitlab-trigger...."
	docker build -t registry.freedesktop.org/mupuf/valve-infra/gitlab-trigger -f containers/gitlab-trigger/Dockerfile .
	;;&
    salad|all)
	echo ">>> Building salad...."
	docker build -t registry.freedesktop.org/mupuf/valve-infra/salad salad/
	;;&
    machine_registration|all)
	echo ">>> Building machine_registration...."
	docker build -t registry.freedesktop.org/mupuf/valve-infra/machine_registration -f machine_registration/Dockerfile .
	;;&
    valve-infra|all)
	echo ">>> Building valve-infra...."
	docker build -t registry.freedesktop.org/mupuf/valve-infra .
	;;
esac
