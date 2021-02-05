FROM python:3.8-alpine
RUN set -ex \
        && apk add --no-cache docker docker-compose bash rsync
WORKDIR /app
ENTRYPOINT ["/app/entrypoint"]
