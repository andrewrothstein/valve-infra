from urllib.parse import urlparse
from dataclasses import dataclass, field
from collections import defaultdict
from tarfile import TarFile
from minio import Minio
from minio.error import S3Error
from typing import List

import subprocess
import tempfile
import requests
import config
import json


@dataclass
class MinIOPolicyStatement:
    # NOTE: Using the default factory to avoid mutable defaults
    buckets: List[str] = field(default_factory=lambda: ["*"])
    actions: List[str] = field(default_factory=lambda: ["s3:*"])
    allow: bool = True

    # Conditions
    source_ips: List[str] = None
    not_source_ips: List[str] = None


def generate_policy(statements):
    def nesteddict():
        return defaultdict(nesteddict)

    rendered_statements = []
    for s in statements:
        resources = [f"arn:aws:s3:::{b}" for b in s.buckets]
        resources.extend([f"arn:aws:s3:::{b}/*" for b in s.buckets])

        statement = {
            'Action': s.actions,
            'Effect': "Allow" if s.allow else "Deny",
            'Resource': resources,
        }

        conditions = nesteddict()
        if s.source_ips and len(s.source_ips) > 0:
            conditions["IpAddress"]["aws:SourceIp"] = s.source_ips
        if s.not_source_ips and len(s.not_source_ips) > 0:
            conditions["NotIpAddress"]["aws:SourceIp"] = s.not_source_ips
        if len(conditions) > 0:
            statement["Condition"] = conditions

        rendered_statements.append(statement)

    return {
        "Version": "2012-10-17",
        "Statement": rendered_statements
    }


class MinioClient():
    def __init__(self,
                 url=config.MINIO_URL,
                 user=config.MINIO_USER,
                 secret_key=config.MINIO_ROOT_PASSWORD,
                 alias=config.MINIO_ADMIN_ALIAS):
        self.url = url
        self.user = user
        self.secret_key = secret_key
        self.alias = alias

        self._client = Minio(
            endpoint=urlparse(url).netloc,
            access_key=user,
            secret_key=secret_key,
            secure=False,
        )

        # Some operations can only be used using the commandline tool,
        # so initialize it
        if alias is not None:
            try:
                subprocess.check_call(
                    ["mcli", "-q", "--no-color", "alias", "set", self.alias, url,
                     self.user, self.secret_key])
            except subprocess.CalledProcessError:  # pragma: nocover
                raise ValueError("Invalid credentials") from None

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

    def extract_archive(self, archive_fileobj, bucket_name):
        with TarFile.open(fileobj=archive_fileobj, mode='r') as archive:
            while (member := archive.next()) is not None:
                # Ignore everything that isn't a file
                if not member.isfile():
                    continue
                self._client.put_object(bucket_name, member.name, archive.extractfile(member),
                                        member.size, num_parallel_uploads=1)

    def make_bucket(self, bucket_name):
        try:
            self._client.make_bucket(bucket_name)
        except S3Error:
            raise ValueError("The bucket already exists") from None

    # NOTE: Using minioclient's remove_bucket requires first to empty the
    # bucket. Use the CLI version for now.
    def remove_bucket(self, bucket_name):
        assert self.alias is not None

        subprocess.check_call(["mcli", "-q", "--no-color", "rb", "--force",
                               f'{self.alias}/{bucket_name}'])

    def add_user(self, user_id, password):
        assert self.alias is not None

        subprocess.check_call(["mcli", "-q", "--no-color", "admin", "user", "add",
                               self.alias, user_id, password])

    def remove_user(self, user_id):
        assert self.alias is not None

        subprocess.check_call(["mcli", "-q", "--no-color", "admin", "user", "remove",
                               self.alias, user_id])

    def apply_user_policy(self, policy_name, user_id, policy_statements):
        assert self.alias is not None

        with tempfile.NamedTemporaryFile(suffix='json') as f:
            policy = generate_policy(policy_statements)
            f.write(json.dumps(policy).encode())
            f.flush()

            subprocess.check_call(["mcli", "-q", "--no-color", "admin", "policy",
                                   "add", self.alias, policy_name, f.name])
            subprocess.check_call(["mcli", "-q", "--no-color", "admin", "policy", "set",
                                   self.alias, policy_name, f"user={user_id}"])

    def remove_user_policy(self, policy_name, user_id):
        assert self.alias is not None

        subprocess.check_call(["mcli", "-q", "--no-color", "admin", "policy", "unset",
                               self.alias, policy_name, f"user={user_id}"])

        subprocess.check_call(["mcli", "-q", "--no-color", "admin", "policy", "remove",
                               self.alias, policy_name])
