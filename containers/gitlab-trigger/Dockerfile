FROM quay.io/buildah/stable
RUN set -ex \
        && dnf -y update; dnf -y install findutils bash wget curl python3-requests skopeo; dnf -y clean all;
COPY bin/ /usr/local/bin
