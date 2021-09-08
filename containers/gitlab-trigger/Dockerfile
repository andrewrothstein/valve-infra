FROM quay.io/buildah/stable

RUN set -ex \
        && dnf -y update; \
           dnf -y install bash inotify-tools git python3-pip python3-jinja2 python3-requests \
                          python3-humanize skopeo wget \
         && pip3 install minio \
	 && `# Needed for the client.py in executor` \
	 && wget --progres=dot:mega -O /usr/bin/mcli https://dl.min.io/client/mc/release/linux-amd64/mc \
	 && chmod +x /usr/bin/mcli \
	 && dnf -y clean all

COPY containers/gitlab-trigger/bin/ensure_container.sh /usr/local/bin
COPY containers/gitlab-trigger/bin/submit_job.sh /usr/local/bin
COPY containers/gitlab-trigger/bin/valvetraces.py /usr/local/bin/valvetraces

# TODO: Package the client in pip (depends on the mcli binary)
COPY executor/client.py /usr/local/bin
COPY executor/message.py /usr/local/bin

# Just be sure!
RUN chmod +x /usr/local/bin/*