FROM python:3.9-slim

COPY executor/requirements.txt /app/executor/requirements.txt
WORKDIR /app

RUN set -ex \
         && echo "deb http://deb.debian.org/debian buster non-free" >> /etc/apt/sources.list \
         && cat /etc/apt/sources.list \
         && apt-get update -y \
         && apt-get install -y --no-install-recommends gcc libsnmp-dev snmp-mibs-downloader dnsmasq \
         && pip install --no-cache-dir -r executor/requirements.txt \
         && apt-get remove -y gcc \
         && apt-get autoremove -y \
         && apt-get clean -y \
         && rm -rf /var/lib/apt/lists/*

COPY . /app/
CMD /app/executor/app.py run
