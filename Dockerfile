FROM docker/compose:alpine-1.27.4
ADD . /radv-infra
WORKDIR /radv-infra
ENTRYPOINT ["/radv-infra/entrypoint.sh"]
