FROM archlinux:latest

# Make a standalone container, bootable with b2c
RUN pacman -Suy --noconfirm podman-docker bash rsync wget systemd glances nano htop speedtest-cli tcpdump ansible git \
    && systemctl enable podman.service \
    && pacman -Scc --noconfirm
COPY rootfs /
COPY minio_policies/ /app/minio_policies/

# plugin needed to build dnsmasq-nftset from AUR
# TODO: remove when building dnsmasq-nftset is no longer necessary:
RUN ansible-galaxy collection install kewlfft.aur
RUN pacman --noconfirm -S base-devel

# allows disabling cache on build for anything after this point, for re-running ansible config without rebuilding base OS install layers
# to use: podman build --build-arg NOCACHE=$(date +%s) ...
ARG NOCACHE=0
ARG EXTRA_ANSIBLE_FLAGS=0

# TODO: it's more convenient to just build and push from the pwd, but I get the safety of pulling from a URI instead...
# not sure how to parameterize this in the Dockerfile,
# if [ "$FOR_PRODUCTION" ]
#   RUN  git clone ...
# else
#  COPY . /app/valve-infra  (or assume volume mounted in podman run)
# fi
#
# You can paramterize RUN if [ "$FOR_PRODUCTION" ]; then git clone ..., but didn't see anything similar for COPY.
#
# For now the follow is commented, assuming a correct volume mount, for user-flexibiility
#
# RUN git clone --single-branch --branch cturner/ansible https://gitlab.freedesktop.org/mupuf/valve-infra.git /app/valve-infra

WORKDIR /app/valve-infra/ansible
RUN ansible-playbook ${EXTRA_ANSIBLE_FLAGS} ./gateway.yml

# TODO: remove when building dnsmasq-nftset is no longer necessary:
# This is "pacman -Rns base-devel" without packages that are dependencies for
# things:
RUN pacman --noconfirm -Rns autoconf automake binutils bison diffutils elfutils fakeroot flex gc gcc groff guile libmpc libtool m4 make patch pkgconf sudo texinfo which

ENTRYPOINT ["/bin/init"]
