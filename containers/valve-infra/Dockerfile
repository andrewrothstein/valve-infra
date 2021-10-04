FROM archlinux:latest

# Make a standalone container, bootable with b2c
RUN pacman -Suy --noconfirm minio-client podman-docker docker-compose bash rsync wget systemd python python-netifaces tmux tmuxp glances nano vim dhcpcd htop speedtest-cli tcpdump \
    && systemctl enable podman.service \
    && pacman -Scc --noconfirm
COPY rootfs /
COPY docker-compose.yml entrypoint /app/
COPY config/ /app/config/
COPY minio_policies/ /app/minio_policies/

# Fix the access rights
RUN chmod 700 /root /root/.ssh && chmod 600 /root/.ssh/authorized_keys

ENTRYPOINT ["/bin/init"]
