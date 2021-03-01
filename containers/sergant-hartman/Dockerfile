FROM python:3.9-alpine

WORKDIR /app
COPY . /app/

RUN set -ex \
	&& apk add --no-cache --virtual .build-deps gcc rust cargo libc-dev libffi-dev linux-headers python3-dev \
        && apk add --no-cache bash libressl-dev \
	&& pip install --no-cache-dir . \
        && apk del --no-network .build-deps
# FIXME: Use the twist application server at some point, this method
# is a bit naughty.
ENTRYPOINT ["python", "-m", "sergant_hartman._service"]

