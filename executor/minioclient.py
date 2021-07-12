from urllib.parse import urlparse
from minio import Minio
from logger import logger
import config

import requests
import tempfile


class MinioClient():
    def __init__(self, url=None):
        if url is None:
            url = config.MINIO_URL
        self.url = url

        secret_key = config.MINIO_ROOT_PASSWORD
        if secret_key is None:
            secret_key = "random"
            logger.warning("No password specified, jobs won't be runnable")

        self._client = Minio(
            endpoint=urlparse(url).netloc,
            access_key="minioadmin",
            secret_key=secret_key,
            secure=False,
        )

    def is_local_url(self, url):
        return url.startswith(f"{self.url}/")

    def save_boot_artifact(self, remote_artifact_url, minio_object_name):
        minio_bucket_name = 'boot'
        with tempfile.NamedTemporaryFile("wb") as temp_download_area, \
             requests.get(remote_artifact_url, stream=True) as r:
            r.raise_for_status()
            # Read all the available data, then write to disk
            for chunk in r.iter_content(None):
                temp_download_area.write(chunk)
            temp_download_area.flush()
            self._client.fput_object(minio_bucket_name, minio_object_name,
                                     temp_download_area.name)
