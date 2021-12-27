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

tmp/disk.img:
	[ -d tmp/ ] || mkdir tmp
	qemu-img create -f qcow2 tmp/disk.img 10G

ifeq ($(V), 1)
EXTRA_ANSIBLE_FLAGS := "-vvv"
else
EXTRA_ANSIBLE_FLAGS := ""
endif
EXTRA_ANSIBLE_VARS := "farm_name=cturner-ansible-test other_variable=foo"
container:
	podman build --dns=none -v $(shell pwd)/../..:/app/valve-infra --build-arg EXTRA_ANSIBLE_FLAGS=$(EXTRA_ANSIBLE_FLAGS) --build-arg EXTRA_ANSIBLE_VARS=$(EXTRA_ANSIBLE_VARS) --build-arg NOCACHE=$(shell date +%s)  --tag $(REGISTRY)/$(CONTAINER) -f Dockerfile . 2>&1 | tee container_build.log

push-container: container
	@# Todo, condition on local vs prod
	podman push --tls-verify=false $(REGISTRY)/$(CONTAINER)

vivian: tmp/boot2container-$(B2C_VERSION)-linux_amd64.cpio.xz tmp/linux-b2c-$(B2C_VERSION) tmp/disk.img
	$(TOOLS)/vivian --kernel-img=tmp/linux-b2c-$(B2C_VERSION) --ramdisk=tmp/boot2container-$(B2C_VERSION)-linux_amd64.cpio.xz --gateway-disk-img=tmp/disk.img --kernel-img=tmp/linux-b2c-$(B2C_VERSION) --ramdisk=tmp/boot2container-$(B2C_VERSION)-linux_amd64.cpio.xz --kernel-append='b2c.volume="tmp" b2c.volume="perm" b2c.container="--dns=none -v tmp:/mnt/tmp -v perm:/mnt/permanent --tls-verify=false --entrypoint=/bin/init docker://${REGISTRY}/${CONTAINER}" b2c.ntp_peer=auto b2c.pipefail b2c.cache_device=auto net.ifnames=0 quiet'  start

vivian-dut:
	$(TOOLS)/vivian --kernel-img=tmp/linux-b2c-$(B2C_VERSION) --ramdisk=tmp/boot2container-$(B2C_VERSION)-linux_amd64.cpio.xz --gateway-disk-img=tmp/disk.img --kernel-img=tmp/linux-b2c-$(B2C_VERSION) --ramdisk=tmp/boot2container-$(B2C_VERSION)-linux_amd64.cpio.xz --kernel-append='b2c.volume="tmp" b2c.volume="perm" b2c.container="--dns=none -v tmp:/mnt/tmp -v perm:/mnt/permanent --tls-verify=false --entrypoint=/bin/init docker://${REGISTRY}/${CONTAINER}" b2c.ntp_peer=auto b2c.pipefail b2c.cache_device=auto net.ifnames=0 quiet'  start

vivian-connect:
	for i in seq 1 30 ; do ssh root@${HOST} -p ${PORT} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null ; sleep 1 ; done

clean:
	-rm tmp/* container_build.log
