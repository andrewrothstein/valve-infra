FROM python:3.9-slim

WORKDIR /app

COPY machine_registration /app/machine_registration
COPY gfxinfo /app/gfxinfo

RUN set -ex \
	 && apt-get update -qyy && apt-get install -qyy gcc libvulkan-dev mesa-vulkan-drivers \
	 && pip install --no-cache-dir -r /app/machine_registration/requirements.txt \
         && pip install --no-cache-dir /app/gfxinfo \
	 && apt-get remove -y gcc && apt-get autoremove -y && apt-get clean -y

# For production, cache the known PCI devices for into the container
# to avoid external network requirements.
RUN python3 /app/machine_registration/machine_registration.py -a /app cache
ENTRYPOINT ["/app/machine_registration/machine_registration.py", "-a", "/app"]

CMD ["register"]
