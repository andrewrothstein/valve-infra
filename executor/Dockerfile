FROM docker.io/library/python:3.9-slim

WORKDIR /app

COPY . /app/

RUN set -ex \
         && echo "deb http://deb.debian.org/debian buster non-free" >> /etc/apt/sources.list \
         && cat /etc/apt/sources.list \
         && apt-get update -y \
         && apt-get install -y --no-install-recommends gcc libsnmp-dev snmp-mibs-downloader dnsmasq vim \
         && pip install ./server ./client \
         && wget -O /usr/bin/mcli https://dl.min.io/client/mc/release/linux-amd64/mc \
         && chmod +x /usr/bin/mcli \
         && apt-get remove -y gcc \
         && apt-get autoremove -y \
         && apt-get clean -y \
         && rm -rf /var/lib/apt/lists/*

CMD executor run
