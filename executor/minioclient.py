from urllib.parse import urlparse
from tarfile import TarFile
from jinja2 import Template
from minio import Minio
from minio.error import S3Error
import subprocess
import tempfile
import requests
import config


job_policy = """{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "AllowGroupToSeeBucketListInTheConsole",
            "Action": ["s3:ListAllMyBuckets", "s3:GetBucketLocation"],
            "Effect": "Allow",
            "Resource": ["arn:aws:s3:::*"],
            "Condition":
            {
                "IpAddress": {
                    "aws:SourceIp": [
                        {{ ip_whitelist }}
                    ]
                }
            }
        },
        {
            "Sid": "AllowListingOfJobSpecificFolder",
            "Action": ["s3:ListBucket"],
            "Effect": "Allow",
            "Resource": ["arn:aws:s3:::*"],
            "Condition":{
               "StringLike": {
                  "s3:prefix": ["{{ bucket_name }}/*", "${aws:username}"]
               },
               "IpAddress": {
                   "aws:SourceIp": [
                       {{ ip_whitelist }}
                   ]
               }
            }
        },
        {
            "Sid": "AllowAllS3ActionsInJobSpecificFolder",
            "Action": ["s3:*"],
            "Effect":"Allow",
            "Resource": ["arn:aws:s3:::{{ bucket_name }}/*"],
            "Condition": {
               "IpAddress": {
                   "aws:SourceIp": [
                       {{ ip_whitelist }}
                   ]
               }
            }
        }
    ]
}"""


# TODO: use the template engine to implement this in a more understandable way
def generate_whitelist_str(whitelist):
    if whitelist is None or len(whitelist) == 0:
        return '"0.0.0.0/0"'

    return ",".join(list(map(lambda x: "\"" + x + "\"", whitelist)))


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
        subprocess.check_call(
            ["mcli", "-q", "--no-color", "alias", "set", self.alias, url,
             self.user, self.secret_key])

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
        subprocess.check_call(["mcli", "-q", "--no-color", "rb", "--force",
                               f'{self.alias}/{bucket_name}'])

    def add_user(self, user_id, password):
        subprocess.check_call(["mcli", "-q", "--no-color", "admin", "user", "add",
                               self.alias, user_id, password])

    def remove_user(self, user_id):
        subprocess.check_call(["mcli", "-q", "--no-color", "admin", "user", "remove",
                               self.alias, user_id])

    def apply_user_policy(self, policy_name, user_id, bucket_name, ip_whitelist):  # pragma: nocover
        with tempfile.NamedTemporaryFile(suffix='json') as f:
            rendered_policy = Template(job_policy).render(bucket_name=bucket_name,
                                                          ip_whitelist=generate_whitelist_str(ip_whitelist))
            f.write(rendered_policy.encode('utf-8'))
            f.flush()

            subprocess.check_call(["mcli", "-q", "--no-color", "admin", "policy",
                                   "add", self.alias, policy_name, f.name])
            subprocess.check_call(["mcli", "-q", "--no-color", "admin", "policy", "set",
                                   self.alias, policy_name, f"user={user_id}"])

    def remove_user_policy(self, policy_name, user_id):
        subprocess.check_call(["mcli", "-q", "--no-color", "admin", "policy", "unset",
                               self.alias, policy_name, f"user={user_id}"])

        subprocess.check_call(["mcli", "-q", "--no-color", "admin", "policy", "remove",
                               self.alias, policy_name])
