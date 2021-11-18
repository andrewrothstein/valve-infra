IPXE_DIR := $(PWD)/ipxe
IPXE_TARGET := bin/ipxe.iso
IPXE_ISO := $(IPXE_DIR)/src/$(IPXE_TARGET)

CERTS_DIR := $(PWD)/ca_cert
CA_CERT := $(CERTS_DIR)/ca.crt
CA_KEY := $(CERTS_DIR)/ca.key
CA_IDX := $(CERTS_DIR)/ca.idx
CA_SRL := $(CERTS_DIR)/ca.srl
CA_CNF := $(CERTS_DIR)/ca.cnf

TMP_DIR := $(PWD)/tmp

OUTPUT_ISO_FOLDER := infra_isos/
OUTPUT_ISO := $(OUTPUT_ISO_FOLDER)/ci-gateway-$(CLIENT_NAME).iso

PRIV_MAC=$(shell printf "DE:AD:BE:EF:%02X:%02X\n" $$((RANDOM%256)) $$((RANDOM%256)))
PUBLIC_MAC=$(shell printf "DE:AD:BE:EF:%02X:%02X\n" $$((RANDOM%256)) $$((RANDOM%256)))
SSH_LOCAL_PORT := 5555

.DEFAULT_GOAL := build

.ONESHELL:

$(CA_CERT):
ifndef IPXE_SERVER_FQDN
	$(error IPXE_SERVER_FQDN is not set)
endif

	@mkdir "$(CERTS_DIR)" 2> /dev/null
	openssl req -nodes -x509 -newkey rsa:2048 -out $(CA_CERT) -keyout $(CA_KEY) -subj "/CN=$(IPXE_SERVER_FQDN)"
	touch $(CERTS_DIR)/ca.idx
	echo 00 > $(CERTS_DIR)/ca.srl

	@# Generate the ca configuration
	@cat <<'EOF'>$(CA_CNF)
	default_ca             = ca_default

	[ ca_default ]
	certificate            = $(CA_CERT)
	private_key            = $(CA_KEY)
	serial                 = $(CA_SRL)
	database               = $(CA_IDX)
	new_certs_dir          = tmp
	default_md             = default
	policy                 = policy_anything
	preserve               = yes
	default_days           = 3650
	unique_subject         = no

	[ policy_anything ]
	countryName            = optional
	stateOrProvinceName    = optional
	localityName           = optional
	organizationName       = optional
	organizationalUnitName = optional
	commonName             = optional
	emailAddress           = optional

	[ cross ]
	basicConstraints       = critical,CA:true
	keyUsage               = critical,cRLSign,keyCertSign

	[ codesigning ]
	keyUsage                = digitalSignature
	extendedKeyUsage        = codeSigning
	EOF

	echo "The CA certificates have been written to $(CERTS_DIR)"
ca: $(CA_CERT)


$(IPXE_DIR):
	git clone git://git.ipxe.org/ipxe.git $(IPXE_DIR)


$(OUTPUT_ISO): $(IPXE_DIR) $(CA_CERT)
ifndef CLIENT_NAME
	$(error CLIENT_NAME is not set)
endif

ifndef IPXE_SERVER_FQDN
	$(error IPXE_SERVER_FQDN is not set)
endif

	@# Create a temporary directory for the generation of the client certificate
	-rm -rf $(TMP_DIR)
	mkdir $(TMP_DIR)
	mkdir $(OUTPUT_ISO_FOLDER)

	openssl req -newkey rsa -nodes -keyout $(TMP_DIR)/client.key -out $(TMP_DIR)/client.req -subj "/CN=$(CLIENT_NAME)"
	openssl ca -batch -config $(CA_CNF) -in $(TMP_DIR)/client.req -out $(TMP_DIR)/client.crt
	openssl verify -verbose -CAfile $(CA_CERT) $(TMP_DIR)/client.crt || exit 1
	CLIENT_FINGERPRINT=`openssl x509 -in "$(TMP_DIR)/client.crt" -noout -fingerprint | sed 's/^SHA1 Fingerprint=\(.*\)/\1/' | tr '[:upper:]' '[:lower:]' | tr -d ':'`
	echo "$$CLIENT_FINGERPRINT" > $(OUTPUT_ISO).fingerprint

	@# Enable HTTPS
	sed -i 's/#undef\tDOWNLOAD_PROTO_HTTPS/#define\tDOWNLOAD_PROTO_HTTPS/' $(IPXE_DIR)/src/config/general.h

	@# Enable the serial console
	sed -i 's/\/\/#define\tCONSOLE_SERIAL/#define\tCONSOLE_SERIAL/' $(IPXE_DIR)/src/config/console.h

	@# Generate the iPXE init script
	cat <<'EOF'>$(TMP_DIR)/ipxescript
	#!ipxe

	echo Welcome to Valve infra's iPXE boot script

	:retry
	echo Acquiring an IP
	dhcp || goto retry # Keep retrying indefinitely
	echo Got the IP: $${netX/ip} / $${netX/netmask}

	echo

	echo Chainloading from the iPXE server...
	chain https://${IPXE_SERVER_FQDN}/boot/ipxe?mac=$${netX/mac} || goto retry
	EOF

	@# Generate the iPXE ISO
	-rm "$(IPXE_ISO)"
	make -C $(IPXE_DIR)/src -j`nproc` $(IPXE_TARGET) EMBED=$(TMP_DIR)/ipxescript PRIVKEY=$(TMP_DIR)/client.key CERT=$(TMP_DIR)/client.crt || exit 1

	cp "$(IPXE_ISO)" "$(OUTPUT_ISO)" || exit 1
	@echo "Generated the bootable image '$(OUTPUT_ISO)' (fingerprint $$CLIENT_FINGERPRINT)"
	sha256sum $(OUTPUT_ISO) > $(OUTPUT_ISO).sha256sum

	@# Remove the temporary directory
	@-rm -rf $(TMP_DIR)

build: $(OUTPUT_ISO)

test: $(OUTPUT_ISO)
	qemu-system-x86_64 -m size=4096 -k en -device virtio-scsi-pci,id=scsi0 -device scsi-cd,bus=scsi0.0,drive=cdrom0 -drive id=cdrom0,if=none,format=raw,media=cdrom,readonly=on,file=$(OUTPUT_ISO) -display gtk -vga std -device virtio-net-pci,romfile=,netdev=net0,mac=$(PUBLIC_MAC) -netdev user,id=net0,hostfwd=tcp::$(SSH_LOCAL_PORT)-:22 -net nic,macaddr=$(PRIV_MAC),model=virtio-net-pci -enable-kvm -serial stdio -boot d -no-reboot

connect:
	ssh root@${HOST} -p ${SSH_LOCAL_PORT} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null
