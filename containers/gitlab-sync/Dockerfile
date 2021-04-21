FROM python:3.9-alpine
RUN set -ex \
        && apk add --no-cache bash
WORKDIR /app
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt
COPY . /app
CMD ["python", "gitlab_sync.py", "service"]

