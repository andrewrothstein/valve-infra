IPXE_DIR := $(PWD)/ipxe
IPXE_TARGET := bin-x86_64-efi/ipxe.efi bin/ipxe.lkrn

CERTS_DIR := $(PWD)/ca_cert
CA_CERT := $(CERTS_DIR)/ca.crt
CA_KEY := $(CERTS_DIR)/ca.key
CA_IDX := $(CERTS_DIR)/ca.idx
CA_SRL := $(CERTS_DIR)/ca.srl
CA_CNF := $(CERTS_DIR)/ca.cnf

TMP_DIR := $(PWD)/tmp

OUTPUT_ISO_FOLDER := $(PWD)/infra_isos
OUTPUT_ISO := $(OUTPUT_ISO_FOLDER)/ci-gateway-$(CLIENT_NAME).iso
CLIENT_CERT_KEY := $(OUTPUT_ISO).key
CLIENT_CERT_REQ := $(OUTPUT_ISO).req
CLIENT_CERT_CRT := $(OUTPUT_ISO).crt
CLIENT_CERT_FINGERPRINT := $(OUTPUT_ISO).fingerprint

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
	openssl req -nodes -x509 -newkey rsa:2048 -out $(CA_CERT) -keyout $(CA_KEY) -subj "/CN=$(IPXE_SERVER_FQDN)" -days 3650
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
	new_certs_dir          = $(TMP_DIR)
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


$(CLIENT_CERT_KEY) $(CLIENT_CERT_REQ): $(CA_CERT)
ifndef CLIENT_NAME
	$(error CLIENT_NAME is not set)
endif
	mkdir $(OUTPUT_ISO_FOLDER)

	openssl req -newkey rsa -nodes -keyout $(CLIENT_CERT_KEY) -out $(CLIENT_CERT_REQ) -subj "/CN=$(CLIENT_NAME)"


$(CLIENT_CERT_CRT) $(CLIENT_CERT_FINGERPRINT): $(CA_CERT) $(CLIENT_CERT_REQ)
	@# Create a temporary directory for the generation of the client certificate
	-rm -rf $(TMP_DIR)
	mkdir $(TMP_DIR)

	openssl ca -batch -config $(CA_CNF) -in $(CLIENT_CERT_REQ) -out $(CLIENT_CERT_CRT) -days 3650
	openssl verify -verbose -CAfile $(CA_CERT) $(CLIENT_CERT_CRT) || exit 1

	CLIENT_FINGERPRINT=`openssl x509 -in $(CLIENT_CERT_CRT) -noout -fingerprint | sed 's/^SHA1 Fingerprint=\(.*\)/\1/' | tr '[:upper:]' '[:lower:]' | tr -d ':'`
	echo "$$CLIENT_FINGERPRINT" > $(CLIENT_CERT_FINGERPRINT)

	rm -rf $(TMP_DIR)


$(OUTPUT_ISO): $(IPXE_DIR) $(CA_CERT) $(CLIENT_CERT_KEY) $(CLIENT_CERT_CRT)
ifndef CLIENT_NAME
	$(error CLIENT_NAME is not set)
endif

ifndef IPXE_SERVER_FQDN
	$(error IPXE_SERVER_FQDN is not set)
endif

	@# Create a temporary directory for the generation of the client certificate
	-rm -rf $(TMP_DIR)
	mkdir $(TMP_DIR)

	@# Enable HTTPS
	sed -i 's/#undef\tDOWNLOAD_PROTO_HTTPS/#define\tDOWNLOAD_PROTO_HTTPS/' $(IPXE_DIR)/src/config/general.h

	@# Enable the NTP command
	sed -i 's/\/\/#define NTP_CMD/#define NTP_CMD/' $(IPXE_DIR)/src/config/general.h

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

	echo Updating the current time using NTP
	ntp pool.ntp.org || goto retry
	echo Current unixtime: $${unixtime} (use `date --date=@$$(($${unixtime}))` to decode it)

	echo

	echo Chainloading from the iPXE server...
	chain https://${IPXE_SERVER_FQDN}/boot/ipxe?mac=$${netX/mac} || goto retry

	# The above command may "succeed" but we actually fail to
	# boot. This could happen if the iPXE boot file is
	# successfully returned, but the URLs to the kernel and
	# ramdisk are invalid, for example. In cases like these,
	# continuously retry the netboot, rather than exiting iPXE and
	# potentially getting stuck indefinitely in the firmware's next
	# boot method. The sleep acts as a simple rate limiter.
	sleep 60
	goto retry
	EOF

	@# Generate the iPXE ISO
	@# Overkill, but safety first.
	make -C $(IPXE_DIR)/src clean
	make -C $(IPXE_DIR)/src -j`nproc` $(IPXE_TARGET) EMBED=$(TMP_DIR)/ipxescript PRIVKEY=$(CLIENT_CERT_KEY) CERT=$(CLIENT_CERT_CRT) DEBUG=x509 || exit 1

	$(IPXE_DIR)/src/util/genfsimg -o $(OUTPUT_ISO) $(IPXE_DIR)/src/bin-x86_64-efi/ipxe.efi $(IPXE_DIR)/src/bin/ipxe.lkrn || exit 1

	@echo "Generated the bootable image '$(OUTPUT_ISO)' (fingerprint `cat $(CLIENT_CERT_FINGERPRINT)`)"
	sha256sum $(OUTPUT_ISO) > $(OUTPUT_ISO).sha256sum

	@# Remove the temporary directory
	@-rm -rf $(TMP_DIR)

build: $(OUTPUT_ISO)

run: $(OUTPUT_ISO)
	./qemu-run.sh $(OUTPUT_ISO) MBR $(SSH_LOCAL_PORT)

auto-boot-test: $(OUTPUT_ISO)
	./qemu-run.sh $(OUTPUT_ISO) MBR
	./qemu-run.sh $(OUTPUT_ISO) UEFI

clean-ipxe:
	make -C $(IPXE_DIR)/src clean

flash: $(OUTPUT_ISO)
ifndef DEVICE
	$(error DEVICE must be set the to flash device, e.g. /dev/sdb)
endif
	@if grep -q $(DEVICE) /etc/mtab ; then \
		echo "'$(DEVICE)' is mounted"; \
		exit 1; \
	fi
	sudo dd if=$(OUTPUT_ISO) of=$(DEVICE) bs=1M conv=fsync status=progress

connect:
	ssh root@${HOST} -p ${SSH_LOCAL_PORT} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null
