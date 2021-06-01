FROM quay.io/buildah/stable
RUN set -ex \
        && dnf -y update; dnf -y install findutils bash wget curl python3-requests skopeo; dnf -y clean all;
COPY containers/gitlab-trigger/bin/submit_job.sh /usr/local/bin
COPY executor/client.py /usr/local/bin
