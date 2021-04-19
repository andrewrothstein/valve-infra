FROM alpine:edge
RUN set -ex \
        && apk add --no-cache bash wget curl skopeo python3 py3-requests \
	&& apk add buildah --repository=http://dl-cdn.alpinelinux.org/alpine/edge/testing
COPY bin/ /usr/local/bin
