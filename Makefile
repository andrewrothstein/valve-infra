SHELL := /bin/bash
.ONESHELL:

# TODO: Integrate Vivian as a standard part of the container build process, rather than as a side-project.
VIVIAN := ./vivian/vivian
PYTHON := $(shell command -v python3)
HOST ?= localhost
ifeq ($(HOST), localhost)
	PORT ?= 60022
else
	PORT ?= 22
endif
V ?= 0
REGISTRY ?= registry.freedesktop.org
CONTAINER ?= mupuf/valve-infra/valve-infra:latest
PRIV_MAC=$(shell printf "DE:AD:BE:EF:%02X:%02X\n" $$((RANDOM%256)) $$((RANDOM%256)))
PUBLIC_MAC=$(shell printf "DE:AD:BE:EF:%02X:%02X\n" $$((RANDOM%256)) $$((RANDOM%256)))
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

.PHONY: valve-infra-container
valve-infra-container:
ifeq ($(V),1)
	$(eval EXTRA_ANSIBLE_FLAGS += -vvv)
endif
ifdef IGNORE_CACHE
	$(eval EXTRA_PODMAN_BUILD_ARGS += --build-arg NOCACHE=$(shell date +%s))
endif
ifndef FARM_NAME
	$(error "FARM_NAME is a required parameter")
endif
	$(eval EXTRA_ANSIBLE_VARS += farm_name=$(FARM_NAME))
	podman build --dns=none -v $(shell pwd):/app/valve-infra --build-arg EXTRA_ANSIBLE_FLAGS="$(ANSIBLE_EXTRA_FLAGS)" --build-arg EXTRA_ANSIBLE_VARS="$(EXTRA_ANSIBLE_VARS)" $(EXTRA_PODMAN_BUILD_ARGS) --tag $(REGISTRY)/$(CONTAINER) -f containers/valve-infra/Dockerfile

# Run the valve-infra multi-service container inside a VM for local testing.
.PHONY: vivian
vivian: tmp/boot2container-$(B2C_VERSION)-linux_amd64.cpio.xz tmp/linux-b2c-$(B2C_VERSION) tmp/disk.img
	$(VIVIAN) --kernel-img=tmp/linux-b2c-$(B2C_VERSION) --ramdisk=tmp/boot2container-$(B2C_VERSION)-linux_amd64.cpio.xz --gateway-disk-img=tmp/disk.img --kernel-img=tmp/linux-b2c-$(B2C_VERSION) --ramdisk=tmp/boot2container-$(B2C_VERSION)-linux_amd64.cpio.xz --kernel-append='b2c.volume="tmp" b2c.volume="perm" b2c.container="--dns=none -v tmp:/mnt/tmp -v perm:/mnt/permanent --tls-verify=false --entrypoint=/bin/init docker://${REGISTRY}/${CONTAINER}" b2c.ntp_peer=auto b2c.pipefail b2c.cache_device=auto net.ifnames=0 quiet'  start

# Start a production test of the virtual gateway. It will retrieve
# boot configuration from an external PXE server, booting from the
# production ISOs.
.PHONY: vivian-ipxe
vivian-ipxe: tmp/ipxe-disk.img
ifndef IPXE_ISO
	$(error "IPXE_ISO needs to point at the installer image")
endif
	$(VIVIAN) test-installer --iso=$(IPXE_ISO) --gateway-disk-img=tmp/ipxe-disk.img

# Simulate a DUT booting on the gateway's private network.
.PHONY: vivian-dut
vivian-dut:
	$(VIVIAN) --kernel-img=tmp/linux-b2c-$(B2C_VERSION) --ramdisk=tmp/boot2container-$(B2C_VERSION)-linux_amd64.cpio.xz --gateway-disk-img=tmp/disk.img --kernel-img=tmp/linux-b2c-$(B2C_VERSION) --ramdisk=tmp/boot2container-$(B2C_VERSION)-linux_amd64.cpio.xz --kernel-append='b2c.volume="tmp" b2c.volume="perm" b2c.container="--dns=none -v tmp:/mnt/tmp -v perm:/mnt/permanent --tls-verify=false --entrypoint=/bin/init docker://$(REGISTRY)/$(CONTAINER)" b2c.ntp_peer=auto b2c.pipefail b2c.cache_device=auto net.ifnames=0 quiet'  start

# Connect to a locally running virtual gateway.
.PHONY: vivian-connect
vivian-connect:
	ssh root@$(HOST) -p $(PORT) -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null

.PHONY: vivian-provision
vivian-provision:
ifndef FARM_NAME
	$(error "FARM_NAME is a required parameter")
endif
	if [ -n "$(TAGS)" ]; then _TAGS="-t $(TAGS)" ; else _TAGS="" ; fi
	cd ansible
	ansible-playbook gateway.yml --extra-vars "farm_name=$(FARM_NAME)" $$_TAGS -l vivian

.PHONY: vpdu
vpdu:
	$(PYTHON) ./vivian/vpdu.py --port $(PORT)

.PHONY: clean
clean:
	-rm -rf tmp vpdu_tmp container_build.log
