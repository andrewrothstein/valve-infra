#!/bin/bash

set -ex

. .gitlab-ci/build_functions.sh

build() {
    buildcntr=$(buildah from -v `pwd`:/app/valve-infra --dns=none --isolation=chroot $BASE_IMAGE)
    buildmnt=$(buildah mount $buildcntr)

    buildah config --workingdir /app/valve-infra/ansible $buildcntr

    $buildah_run $buildcntr sh -c 'env LC_ALL=C pacman -Qi' | awk '/^Name/{name=$3} /^Installed Size/{print $4$5, name}' | sort -h

    # The Gitlab runner cache deliberately chmod 777's all
    # directories. This upsets ansible and there's nothing we can
    # really do about it in our repo. See
    # https://gitlab.com/gitlab-org/gitlab-runner/-/issues/4187
    $buildah_run $buildcntr chmod -R o-w /app/valve-infra/ansible
    $buildah_run $buildcntr ansible-lint --version
    $buildah_run $buildcntr ansible-lint -f plain -x yaml[line-length] -x yaml[commas] -x name[casing]
    $buildah_run $buildcntr ansible-galaxy collection install -r requirements.yml
    $buildah_run $buildcntr ansible-playbook --syntax-check gateway.yml
    $buildah_run $buildcntr ansible-playbook $ANSIBLE_EXTRA_ARGS ./gateway.yml -l localhost

    buildah config --entrypoint /bin/init $buildcntr
}

build_and_push_container
