FROM quay.io/buildah/stable
RUN set -ex \
        && dnf -y update; \
           dnf -y install bash inotify-tools python3-jinja2 python3-requests \
                          skopeo wget; \
           dnf -y clean all
COPY containers/gitlab-trigger/bin/ensure_container.sh /usr/local/bin
COPY containers/gitlab-trigger/bin/submit_job.sh /usr/local/bin
COPY executor/client.py /usr/local/bin
