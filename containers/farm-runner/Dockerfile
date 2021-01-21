FROM python:3.8-alpine
RUN set -ex \
        && apk add --no-cache bash openssh wget \
        && pip3 install --no-cache-dir httpie
COPY ssh/ /root/.ssh
COPY bin/ /usr/local/bin
# Permissions are not always preserved in the host environment The
# config file must not be group or world readable, or else SSH will
# fail
RUN chmod 600 /root/.ssh/*
