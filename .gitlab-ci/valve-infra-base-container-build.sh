#!/bin/bash

set -ex

buildah_run="buildah run --isolation chroot"
buildah_commit="buildah commit --format docker"

buildcntr=$(buildah from --dns=none --isolation=chroot $BASE_IMAGE)
buildmnt=$(buildah mount $buildcntr)

cat <<EOF >$buildmnt/etc/resolv.conf
nameserver 1.1.1.1
nameserver 8.8.8.8
nameserver 4.4.4.4
EOF
$buildah_run $buildcntr pacman -Syu --noconfirm
$buildah_run $buildcntr pacman -S --noconfirm \
	ansible-core ansible-lint yamllint \
	bash bash-completion \
	gcc \
	git \
	glances \
	htop \
	nano vim \
	net-snmp \
	podman-docker \
	python \
	python-pip \
	rsync \
	speedtest-cli \
	systemd \
	tcpdump \
	wget

# dnsmasq 2.86-1 has a bug in its signal handling, downgrade to 2.85-1 and pin
# Reported upstream: https://lists.thekelleys.org.uk/pipermail/dnsmasq-discuss/2022q1/016133.html
# Reported in Arch: https://bugs.archlinux.org/task/73684
$buildah_run $buildcntr pacman --noconfirm -U https://archive.archlinux.org/packages/d/dnsmasq/dnsmasq-2.85-1-x86_64.pkg.tar.zst
$buildah_run $buildcntr sed -i 's/^# *IgnorePkg =/IgnorePkg = dnsmasq/' /etc/pacman.conf

# Shame we can't get just the community.general.pacman role, need
# to whole 20MB of general packages. This is a lot better than
# installing Arch's ansible package however, which weighs 700MB!
# There's a tradeoff what to install in the base-container (this)
# and what to install in Ansible. The more Ansible installs from
# the network, the slower the CI gets. But the less that is
# managed by Ansible, the less consistent the declarative picture
# is... It's tempting to install everything we need in the base
# container and drop completely the requirement on
# community.general, that allows affords us more room to optimise
# the size of the base layer.
$buildah_run $buildcntr ansible-galaxy collection install community.general

$buildah_run $buildcntr wget -O /usr/bin/mcli https://dl.min.io/client/mc/release/linux-amd64/mc
$buildah_run $buildcntr chmod +x /usr/bin/mcli

$buildah_run $buildcntr sh -c 'find /usr /etc /root -name __pycache__ -type d | xargs rm -rf'

$buildah_run $buildcntr sh -c 'env LC_ALL=C pacman -Qi' | awk '/^Name/{name=$3} /^Installed Size/{print $4$5, name}' | sort -h
$buildah_run $buildcntr du -h -d 3 /usr /etc | sort -h
$buildah_run $buildcntr du -h /usr/lib/python3.10/site-packages | sort -h

if [ -n "$IMAGE_NAME" ]; then
    buildah config --entrypoint /bin/init $buildcntr
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
fi

buildah unmount $buildcntr
buildah rm $buildcntr
