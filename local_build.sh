#!/bin/bash

container=${1:-all}

case $container in
    executor|all)
	echo ">>> Building executor...."
	docker build -t registry.freedesktop.org/mupuf/valve-infra/executor -f executor/Dockerfile .
	;;&
    gitlab-trigger|all)
	echo ">>> Building gitlab-trigger...."
	docker build -t registry.freedesktop.org/mupuf/valve-infra/gitlab-trigger containers/gitlab-trigger
	;;&
    salad|all)
	echo ">>> Building salad...."
	docker build -t registry.freedesktop.org/mupuf/valve-infra/salad salad/
	;;&
    valve-infra|all)
	echo ">>> Building valve-infra...."
	docker build -t registry.freedesktop.org/mupuf/valve-infra/valve-infra .
	;;
esac
