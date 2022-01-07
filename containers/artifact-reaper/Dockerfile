FROM docker.io/library/alpine:latest
RUN set -ex \
        && apk add --no-cache bash curl
WORKDIR /app
COPY minio-put.sh /app/
ENTRYPOINT ["bash", "/app/minio-put.sh"]

