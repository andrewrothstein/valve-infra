FROM archlinux:latest

# Make a standalone container, bootable with b2c
RUN pacman -Suy --noconfirm podman-docker bash rsync wget systemd glances nano htop speedtest-cli tcpdump ansible git \
    && systemctl enable podman.service \
    && pacman -Scc --noconfirm
COPY rootfs /
COPY config/ /app/config/
COPY minio_policies/ /app/minio_policies/

# TODO: replace with mupuf/valve-infra repo:
RUN git clone --single-branch --branch ansible https://gitlab.freedesktop.org/craftyguy/valve-infra.git /app/valve-infra
WORKDIR /app/valve-infra/ansible
RUN ansible-playbook ./gateway.yml

# Fix the access rights
RUN chmod 700 /root && chmod 600 /etc/authorized_keys

ENTRYPOINT ["/bin/init"]
