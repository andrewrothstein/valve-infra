FROM python:3.8-alpine
RUN set -ex \
        && apk add --no-cache docker docker-compose bash rsync
WORKDIR /app
COPY requirements.txt /app
RUN pip install --no-cache-dir -r requirements.txt
ENTRYPOINT ["/app/entrypoint"]
