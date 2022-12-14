SHELL := /bin/bash
.ONESHELL:

# TODO: Integrate Vivian as a standard part of the container build process, rather than as a side-project.
VIVIAN := ./vivian/vivian
HOST ?= localhost
ifeq ($(HOST), localhost)
	SSH_PORT ?= 60022
else
	SSH_PORT ?= 22
endif
ifdef SSH_ID_KEY
	VIVIAN_SSH_KEY_OPT=--ssh-id=$(SSH_ID_KEY)
	SSH_KEY_OPT=-i $(SSH_ID_KEY) -o IdentitiesOnly=yes
	ANSIBLE_SSH_KEY_OPT=--private-key $(SSH_ID_KEY) --ssh-common-args "-o IdentitiesOnly=yes"
endif
V ?= 0
GITLAB_URL ?= "https://gitlab.freedesktop.org"
PRIV_MAC=$(shell printf "DE:AD:BE:EF:%02X:%02X\n" $$((RANDOM%256)) $$((RANDOM%256)))
PUBLIC_MAC=$(shell printf "DE:AD:BE:EF:%02X:%02X\n" $$((RANDOM%256)) $$((RANDOM%256)))
B2C_VERSION=v0.9.8

tmp/boot2container-$(B2C_VERSION)-linux_amd64.cpio.xz:
	[ -d tmp/ ] || mkdir tmp
	wget -O tmp/boot2container-$(B2C_VERSION)-linux_amd64.cpio.xz https://gitlab.freedesktop.org/mupuf/boot2container/-/releases/$(B2C_VERSION)/downloads/initramfs.linux_amd64.cpio.xz

tmp/linux-b2c-$(B2C_VERSION):
	[ -d tmp/ ] || mkdir tmp
	wget -O tmp/linux-b2c-$(B2C_VERSION) https://gitlab.freedesktop.org/mupuf/boot2container/-/releases/$(B2C_VERSION)/downloads/linux-x86_64-full

tmp/ipxe-disk.img tmp/disk.img:
	[ -d tmp/ ] || mkdir tmp
	qemu-img create -f qcow2 $@ 20G

.PHONY: local-registry
local-registry:
	@case "$(shell podman ps -a --format '{{.Status}}' --filter name=registry)" in
		Up*)
			echo "registry container already started"
			;;
		*)
			# clean up any existing version of the container and (re)create it
			@podman rm -fi registry
			@podman run --rm -d -p 8088:5000 --replace --name registry docker.io/library/registry:2
			;;
	esac

.PHONY: valve-infra-container
valve-infra-container: BASE_IMAGE ?= "registry.freedesktop.org/mupuf/valve-infra/valve-infra-base-container:latest"
valve-infra-container: local-registry
	env \
	   IMAGE_NAME=localhost:8088/valve-infra/valve-infra-container:latest \
	   BASE_IMAGE=$(BASE_IMAGE) \
	   ANSIBLE_EXTRA_ARGS='--extra-vars service_mgr_override=inside_container -e development=true' \
	   buildah unshare -- .gitlab-ci/valve-infra-container-build.sh

.PHONY: valve-infra-base-container
valve-infra-base-container: BASE_IMAGE ?= "archlinux:base-devel-20220731.0.71623"
valve-infra-base-container: local-registry
ifndef IMAGE_NAME
	$(error "IMAGE_NAME is a required parameter (e.g. localhost:8088/mupuf/valve-infra/valve-infra-base-container:latest)")
endif
	env \
	   IMAGE_NAME=$(IMAGE_NAME) \
	   BASE_IMAGE=$(BASE_IMAGE) \
	   buildah unshare -- .gitlab-ci/valve-infra-base-container-build.sh

.PHONY: machine-registration-container
machine-registration-container:
ifndef IMAGE_NAME
	$(error "IMAGE_NAME is a required parameter (e.g. localhost:8088/mupuf/valve-infra/machine_registration:latest)")
endif
	env \
	   IMAGE_NAME=$(IMAGE_NAME) \
	   buildah unshare -- .gitlab-ci/machine-registration-container-build.sh

.PHONY: telegraf-container
telegraf-container:
ifndef IMAGE_NAME
	$(error "IMAGE_NAME is a required parameter (e.g. localhost:8088/mupuf/valve-infra/telegraf-container:latest)")
endif
	env \
	   IMAGE_NAME=$(IMAGE_NAME) \
	   buildah unshare -- .gitlab-ci/telegraf-container-build.sh


.PHONY: valvetraces-enrollment-container
valvetraces-enrollment-container: BASE_IMAGE ?= "archlinux:base-devel-20220130.0.46058"
valvetraces-enrollment-container:
ifndef IMAGE_NAME
	$(error "IMAGE_NAME is a required parameter (e.g. localhost:8088/mupuf/valve-infra/valvetraces-enrollment-container:latest)")
endif
	env \
	   IMAGE_NAME=$(IMAGE_NAME) \
	   BASE_IMAGE=$(BASE_IMAGE) \
	   buildah unshare -- .gitlab-ci/valvetraces-enrollment-container-build.sh

# Run the valve-infra multi-service container inside a VM for local testing.
.PHONY: vivian
vivian: FARM_NAME ?= "vivian-$(USER)"
vivian: tmp/boot2container-$(B2C_VERSION)-linux_amd64.cpio.xz tmp/linux-b2c-$(B2C_VERSION) tmp/disk.img local-registry
	podman image exists localhost:8088/valve-infra/valve-infra-container:latest || $(MAKE) -j1 valve-infra-container
	@env \
	   FARM_NAME=$(FARM_NAME) \
	   GITLAB_URL=$(GITLAB_URL) \
	   GITLAB_REGISTRATION_TOKEN=$(GITLAB_REGISTRATION_TOKEN) \
	   $(VIVIAN) $(VIVIAN_OPTS) $(VIVIAN_SSH_KEY_OPT) --kernel-img=tmp/linux-b2c-$(B2C_VERSION) --ramdisk=tmp/boot2container-$(B2C_VERSION)-linux_amd64.cpio.xz --gateway-disk-img=tmp/disk.img --kernel-append='b2c.volume="tmp" b2c.volume="perm" b2c.hostname=vivian b2c.container="-ti --dns=none -v tmp:/mnt/tmp -v perm:/mnt/permanent --tls-verify=false --entrypoint=/bin/init docker://10.0.2.2:8088/valve-infra/valve-infra-container:latest" b2c.ntp_peer=auto b2c.pipefail b2c.cache_device=auto net.ifnames=0 quiet' start

# Start a production test of the virtual gateway. It will retrieve
# boot configuration from an external PXE server, booting from the
# production ISOs.
.PHONY: vivian-ipxe
vivian-ipxe: tmp/ipxe-disk.img
ifndef IPXE_ISO
	$(error "IPXE_ISO needs to point at the installer image")
endif
	$(VIVIAN) $(VIVIAN_OPTS) test-installer --iso=$(IPXE_ISO) --gateway-disk-img=tmp/ipxe-disk.img

# Create/add a new virtual DUT on the gateway's private network
.PHONY: vivian-add-dut
vivian-add-dut: OUTLET ?= 0
vivian-add-dut:
	curl -X POST localhost:8000/api/v1/machine/discover -H 'Content-Type: application/json' -d '{"pdu": "VPDU", "port_id": "${OUTLET}"}'

# Connect to a locally running virtual gateway.
.PHONY: vivian-connect
vivian-connect:
ifndef SSH_KEY_OPT
	$(warning "You might find helpful to define SSH_KEY_OPT (or SSH_ID_KEY) for this target.")
endif
	ssh root@$(HOST) $(SSH_KEY_OPT) -p $(SSH_PORT) -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null

.PHONY: vivian-provision
vivian-provision:
	if [ -n "$(TAGS)" ]; then _TAGS="-t $(TAGS)" ; else _TAGS="" ; fi
	cd ansible
	ansible-playbook gateway.yml $(ANSIBLE_SSH_KEY_OPT) $$_TAGS -e valve_infra_root=$(CURDIR) -e development=true -l vivian

.PHONY: live-provision
live-provision:
ifndef TARGET
	$(error "TARGET needs to point to the host you want to deploy to")
endif
	if [ -n "$(TAGS)" ]; then _TAGS="-t $(TAGS)" ; else _TAGS="" ; fi
	cd ansible
	ansible-playbook gateway.yml $(ANSIBLE_SSH_KEY_OPT) $$_TAGS -e valve_infra_root=$(CURDIR) -e target=$(TARGET) -l live

TMP_DIR := $(PWD)/tmp
IPXE_DIR := $(TMP_DIR)/ipxe
$(IPXE_DIR):
	-mkdir -p $(TMP_DIR)
	git clone git://git.ipxe.org/ipxe.git $(IPXE_DIR)


.PHONY: ipxe-dut-clients
ipxe-dut-clients: $(IPXE_DIR)
	@# Tidy up the ipxe folder (overkill, but safety first)
	make -C $(IPXE_DIR)/src clean
	(cd $(IPXE_DIR) && git clean -fdx && git fetch && git reset --hard HEAD)

	cat <<'EOF'> $(IPXE_DIR)/src/config/general.h
	#ifndef CONFIG_GENERAL_H
	#define CONFIG_GENERAL_H

	FILE_LICENCE ( GPL2_OR_LATER_OR_UBDL );

	#include <config/defaults.h>

	#define BANNER_TIMEOUT		0
	#define ROM_BANNER_TIMEOUT	( 2 * BANNER_TIMEOUT )

	#define	NET_PROTO_IPV4		/* IPv4 protocol */

	#undef	DOWNLOAD_PROTO_TFTP	/* Trivial File Transfer Protocol */
	#define	DOWNLOAD_PROTO_HTTP	/* Hypertext Transfer Protocol */
	#undef	DOWNLOAD_PROTO_HTTPS	/* Secure Hypertext Transfer Protocol */
	#undef	DOWNLOAD_PROTO_FTP	/* File Transfer Protocol */
	#undef	DOWNLOAD_PROTO_SLAM	/* Scalable Local Area Multicast */
	#undef	DOWNLOAD_PROTO_NFS	/* Network File System Protocol */
	#undef	DOWNLOAD_PROTO_FILE	/* Local filesystem access */

	#undef	SANBOOT_PROTO_ISCSI	/* iSCSI protocol */
	#undef	SANBOOT_PROTO_AOE	/* AoE protocol */
	#undef	SANBOOT_PROTO_IB_SRP	/* Infiniband SCSI RDMA protocol */
	#undef	SANBOOT_PROTO_FCP	/* Fibre Channel protocol */
	#undef	SANBOOT_PROTO_HTTP	/* HTTP SAN protocol */

	#define	DNS_RESOLVER		/* DNS resolver */

	#define	NVO_CMD			/* Non-volatile option storage commands */
	#define	CONFIG_CMD		/* Option configuration console */
	#define CONSOLE_CMD		/* Console command */
	#define IMAGE_CMD		/* Image management commands */
	#define DHCP_CMD		/* DHCP management commands */
	#define IMAGE_ARCHIVE_CMD	/* Archive image management commands */

	#undef	ERRMSG_80211		/* All 802.11 error descriptions (~3.3kb) */

	#undef	BUILD_SERIAL
	#undef	BUILD_ID
	#undef	NULL_TRAP
	#undef	GDBSERIA
	#undef	GDBUDP

	#include <config/named.h>
	#include NAMED_CONFIG(general.h)
	#include <config/local/general.h>
	#include LOCAL_NAMED_CONFIG(general.h)

	#endif /* CONFIG_GENERAL_H */
	EOF

	cat <<'EOF'>$(IPXE_DIR)/src/config/console.h
	#ifndef CONFIG_CONSOLE_H
	#define CONFIG_CONSOLE_H

	FILE_LICENCE ( GPL2_OR_LATER_OR_UBDL );

	#include <config/defaults.h>

	#undef	CONSOLE_SERIAL		/* Serial port console */
	#define	CONSOLE_SYSLOG		/* Syslog console */
	#define	KEYBOARD_MAP	us
	#define	LOG_LEVEL	LOG_ALL

	#include <config/named.h>
	#include NAMED_CONFIG(console.h)
	#include <config/local/console.h>
	#include LOCAL_NAMED_CONFIG(console.h)

	#endif /* CONFIG_CONSOLE_H */
	EOF

	@# Generate the iPXE init script
	cat <<'EOF'>$(IPXE_DIR)/boot.ipxe
	#!ipxe

	echo Welcome to Valve infra's iPXE boot script

	:retry
	echo Acquiring an IP...
	dhcp || goto retry
	echo SALAD.machine_id=$${netX/mac}
	echo Got the IP: $${netX/ip} / $${netX/netmask}

	echo

	echo Downloading the boot configuration...
	chain http://ci-gateway/boot/$${netX/mac}/boot.ipxe?platform=$${platform}&buildarch=$${buildarch} || goto retry

	sleep 1
	goto retry
	EOF

	@# Compile the binaries
	make -C $(IPXE_DIR)/src -j`nproc` EMBED=$(IPXE_DIR)/boot.ipxe bin-x86_64-efi/ipxe.efi bin/undionly.kpxe NO_WERROR=1 || exit 1

	echo
	echo "########################################################################"
	echo
	echo "The compilation is now complete, you will find your binaries at:"
	echo
	echo " - PCBIOS: $(IPXE_DIR)/src/bin/undionly.kpxe"
	echo " - EFI: $(IPXE_DIR)/src/bin-x86_64-efi/ipxe.efi"
	echo
	echo "Upload them to https://downloads.gfx-ci.steamos.cloud/ipxe-dut-client/"
	echo
	echo "########################################################################"

.PHONY: clean
clean:
	-rm -rf tmp $(TMP_DIR) container_build.log
	# Stop registry container if it's running
	container=$(shell podman ps -a --format '{{.Names}}' | grep ^registry)
	if [ ! -z "$$container" ]; then
		podman stop registry
	fi
