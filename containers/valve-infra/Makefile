SHELL := /bin/bash

TOOLS := ../../vivian

HOST ?= localhost
ifeq ($(HOST), localhost)
	PORT ?= 60022
else
	PORT ?= 22
endif

V ?= 0

# 10.0.2.2:8088 can be very useful inside QEMU ;)
REGISTRY ?= registry.freedesktop.org
CONTAINER ?= mupuf/valve-infra/valve-infra:latest

PRIV_MAC=$(shell printf "DE:AD:BE:EF:%02X:%02X\n" $$((RANDOM%256)) $$((RANDOM%256)))
PUBLIC_MAC=$(shell printf "DE:AD:BE:EF:%02X:%02X\n" $$((RANDOM%256)) $$((RANDOM%256)))

.DEFAULT_GOAL := vivian

B2C_VERSION=v0.9.3

tmp/boot2container-$(B2C_VERSION)-linux_amd64.cpio.xz:
	[ -d tmp/ ] || mkdir tmp
	wget -O tmp/boot2container-$(B2C_VERSION)-linux_amd64.cpio.xz https://gitlab.freedesktop.org/mupuf/boot2container/-/releases/$(B2C_VERSION)/downloads/initramfs.linux_amd64.cpio.xz

tmp/linux-b2c-$(B2C_VERSION):
	[ -d tmp/ ] || mkdir tmp
	wget -O tmp/linux-b2c-$(B2C_VERSION) https://gitlab.freedesktop.org/mupuf/boot2container/-/releases/$(B2C_VERSION)/downloads/bzImage

tmp/ipxe-disk.img tmp/disk.img:
	[ -d tmp/ ] || mkdir tmp
	qemu-img create -f qcow2 $@ 20G

ifeq ($(V),1)
EXTRA_ANSIBLE_FLAGS += -vvv
endif
ifdef IGNORE_CACHE
EXTRA_PODMAN_BUILD_ARGS += --build-arg NOCACHE=$(shell date +%s)
endif
container:
	podman build --dns=none -v $(shell pwd)/../..:/app/valve-infra --build-arg EXTRA_ANSIBLE_FLAGS=$(EXTRA_ANSIBLE_FLAGS) --build-arg EXTRA_ANSIBLE_VARS="$(EXTRA_ANSIBLE_VARS)" $(EXTRA_PODMAN_BUILD_ARGS) --tag $(REGISTRY)/$(CONTAINER) -f Dockerfile

push-container: container
	@# Todo, condition on local vs prod
	podman push --tls-verify=false $(REGISTRY)/$(CONTAINER)

vivian: tmp/boot2container-$(B2C_VERSION)-linux_amd64.cpio.xz tmp/linux-b2c-$(B2C_VERSION) tmp/disk.img
	$(TOOLS)/vivian --kernel-img=tmp/linux-b2c-$(B2C_VERSION) --ramdisk=tmp/boot2container-$(B2C_VERSION)-linux_amd64.cpio.xz --gateway-disk-img=tmp/disk.img --kernel-img=tmp/linux-b2c-$(B2C_VERSION) --ramdisk=tmp/boot2container-$(B2C_VERSION)-linux_amd64.cpio.xz --kernel-append='b2c.volume="tmp" b2c.volume="perm" b2c.container="--dns=none -v tmp:/mnt/tmp -v perm:/mnt/permanent --tls-verify=false --entrypoint=/bin/init docker://${REGISTRY}/${CONTAINER}" b2c.ntp_peer=auto b2c.pipefail b2c.cache_device=auto net.ifnames=0 quiet'  start

vivian-ipxe: tmp/ipxe-disk.img
ifndef IPXE_ISO
	$(error "IPXE_ISO needs to point at the installer image")
endif
	$(TOOLS)/vivian test-installer --iso=$(IPXE_ISO) --gateway-disk-img=tmp/ipxe-disk.img

vivian-dut:
	$(TOOLS)/vivian --kernel-img=tmp/linux-b2c-$(B2C_VERSION) --ramdisk=tmp/boot2container-$(B2C_VERSION)-linux_amd64.cpio.xz --gateway-disk-img=tmp/disk.img --kernel-img=tmp/linux-b2c-$(B2C_VERSION) --ramdisk=tmp/boot2container-$(B2C_VERSION)-linux_amd64.cpio.xz --kernel-append='b2c.volume="tmp" b2c.volume="perm" b2c.container="--dns=none -v tmp:/mnt/tmp -v perm:/mnt/permanent --tls-verify=false --entrypoint=/bin/init docker://${REGISTRY}/${CONTAINER}" b2c.ntp_peer=auto b2c.pipefail b2c.cache_device=auto net.ifnames=0 quiet'  start

vivian-connect:
	ssh root@${HOST} -p ${PORT} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null

clean:
	-rm tmp/* container_build.log
