#!/bin/bash

docker build -t registry.freedesktop.org/mupuf/valve-infra/executor -f executor/Dockerfile .

docker build -t registry.freedesktop.org/mupuf/valve-infra/gitlab-trigger containers/gitlab-trigger

docker build -t registry.freedesktop.org/mupuf/valve-infra/salad salad/

docker build -t registry.freedesktop.org/mupuf/valve-infra/valve-infra .
