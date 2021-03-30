FROM alpine:3

RUN set -ex \
        && apk add --no-cache py3-netifaces py3-psutil py3-requests py3-pip \
        && apk add --no-cache -X http://dl-cdn.alpinelinux.org/alpine/edge/testing py3-pyserial

WORKDIR /app

RUN pip install gfxinfo-mupuf

COPY machine_registration.py /app/machine_registration
RUN python3 /app/machine_registration -a /app/amdgpu_drv.c cache_dbs

ENTRYPOINT ["/app/machine_registration", "-a", "/app/amdgpu_drv.c"]
CMD ["register"]
