FROM quay.io/buildah/stable

RUN set -ex \
        && dnf -y update; \
           dnf -y install bash inotify-tools git python3-pip skopeo wget \
	 && wget --progres=dot:mega -O /usr/bin/mcli https://dl.min.io/client/mc/release/linux-amd64/mc \
	 && chmod +x /usr/bin/mcli \
	 && dnf -y clean all

COPY containers/gitlab-trigger/bin/ensure_container.sh /usr/local/bin
COPY containers/gitlab-trigger/bin/submit_job.sh /usr/local/bin
COPY valvetraces/ /src/valvetraces
COPY executor/client/ /src/executor/client/

RUN set -ex \
	 && pip3 install /src/valvetraces /src/executor/client \
	 && cp /usr/local/bin/valvetraces /usr/local/bin/valvetraces.py \
	 && cp /usr/local/bin/executorctl /usr/local/bin/client.py

# Just be sure!
RUN chmod +x /usr/local/bin/*
