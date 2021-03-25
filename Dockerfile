FROM python:3.8-alpine
RUN set -ex \
        && apk add -X http://dl-cdn.alpinelinux.org/alpine/edge/testing --no-cache minio-client \
        && apk add --no-cache docker docker-compose bash rsync wget
WORKDIR /app
ENTRYPOINT ["/app/entrypoint"]
