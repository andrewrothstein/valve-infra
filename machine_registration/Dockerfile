FROM python:3.9-slim

WORKDIR /app

COPY machine_registration /app/machine_registration
COPY gfxinfo /app/gfxinfo

RUN set -ex \
	 && apt-get update -qyy && apt-get install -qyy gcc libvulkan-dev \
	 && pip install --no-cache-dir -r /app/machine_registration/requirements.txt \
         && pip install --no-cache-dir /app/gfxinfo \
	 && apt-get remove -y gcc && apt-get autoremove -y && apt-get clean -y \
	 && find /var/cache/apt/ -type f -exec rm -v {} \; \
	 && find /var/lib/apt/lists -type f -exec rm -v {} \; \
	 && rm -rf  /var/lib/dpkg  /var/lib/apt/lists

RUN python3 /app/machine_registration/machine_registration.py -a /app/amdgpu_drv.c cache_dbs
ENTRYPOINT ["/app/machine_registration/machine_registration.py", "-a", "/app/amdgpu_drv.c"]

CMD ["register"]
