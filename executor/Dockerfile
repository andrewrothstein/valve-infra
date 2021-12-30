FROM python:3.9-slim

COPY requirements.txt /app/requirements.txt
WORKDIR /app

RUN set -ex \
         && echo "deb http://deb.debian.org/debian buster non-free" >> /etc/apt/sources.list \
         && cat /etc/apt/sources.list \
         && apt-get update -y \
         && apt-get install -y --no-install-recommends gcc libsnmp-dev snmp-mibs-downloader dnsmasq vim \
         && pip install --no-cache-dir -r requirements.txt \
	 && wget -O /usr/bin/mcli https://dl.min.io/client/mc/release/linux-amd64/mc \
	 && chmod +x /usr/bin/mcli \
         && apt-get remove -y gcc \
         && apt-get autoremove -y \
         && apt-get clean -y \
         && rm -rf /var/lib/apt/lists/*

COPY . /app/

CMD /app/app.py run
