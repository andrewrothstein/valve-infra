FROM python:3.9-alpine

RUN set -ex \
        && apk add --no-cache net-snmp-tools net-snmp-libs
COPY executor/requirements.txt /app/executor/requirements.txt
WORKDIR /app
RUN set -ex \
        && apk add --no-cache --virtual .build-deps gcc libc-dev linux-headers python3-dev net-snmp-dev \
        && pip install --no-cache-dir -r executor/requirements.txt \
        && apk del --no-network .build-deps
COPY . /app
CMD /app/executor/app.py run
