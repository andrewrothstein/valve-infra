FROM python:3.9-alpine

WORKDIR /app

COPY ./requirements.txt /app/requirements.txt

RUN set -ex \
        && pip install --no-cache-dir -r requirements.txt
COPY ./ /app
CMD /app/app.py
