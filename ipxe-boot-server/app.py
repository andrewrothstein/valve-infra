import argparse
from b2sdk.v2 import InMemoryAccountInfo, B2Api
from b2sdk.v2.exception import NonExistentBucket
from dataclasses import dataclass
from datetime import datetime, timedelta
from flask import Flask, current_app, request, abort, g, send_from_directory
from flask.logging import default_handler
import logging
from pprint import pformat
from secrets import token_urlsafe
import socket
from string import Template
import subprocess
import os


app = Flask(__name__)


@dataclass
class BbzClient:
    access_key: str
    access_key_id: str

    def __post_init__(self):
        # check the crendentials
        print("Authenticating to Backblaze")
        self.info = InMemoryAccountInfo()
        self.b2_api = B2Api(self.info)
        self.b2_api.authorize_account("production", self.access_key_id, self.access_key)
        print("Backblaze authentication complete")


@dataclass
class BbzBucket:
    endpoint: str
    access_key: str
    access_key_id: str
    bucket_name: str


@dataclass
class ClientProfile:
    ip_address: str
    mac_address: str
    client_cert_serial_number: str
    client_cert_fingerprint: str

    @property
    def files_prefix(self) -> str:
        return os.path.join(current_app.config['DATA_ROOT'],
                            self.client_cert_fingerprint)

    def get_scratch_space_on_b2(self, bbz, server_name) -> BbzBucket:
        prefix = f'ipxe-{server_name}'

        # Get or create the bucket
        bucket_name = f'{prefix}-{self.client_cert_fingerprint}'[0:50]
        try:
            bucket = bbz.b2_api.get_bucket_by_name(bucket_name)
        except NonExistentBucket:
            bucket = bbz.b2_api.create_bucket(bucket_name, 'allPrivate')

        # Create the disposable credentials, remove any key that would already
        # exist for this client
        key_name = f'{prefix}-{self.client_cert_fingerprint}'[0:100]
        for key in bbz.b2_api.list_keys():
            if key.key_name == key_name:
                bbz.b2_api.delete_key(key)
        key = bbz.b2_api.create_key(capabilities=["listBuckets", "listFiles", "readFiles", "writeFiles", "deleteFiles"],
                                    key_name=key_name)

        return BbzBucket(endpoint=bbz.info.get_s3_api_url(),
                         access_key=key.application_key,
                         access_key_id=key.id_,
                         bucket_name=bucket_name)


class OneTimeSecretDatabase:
    def __init__(self):
        self.db = dict()

    def set(self, secret: str, validity_period: timedelta) -> str:
        token = token_urlsafe(32)
        self.db[token] = {
            "expiration": datetime.now() + validity_period,
            "secret": secret
        }
        return token

    def get(self, token: str) -> str:
        if entry := self.db.pop(token, None):
            if entry["expiration"] > datetime.now():
                return entry["secret"]

        return None


def gen_conf(template_name: str, p: ClientProfile, bucket: BbzBucket, secrets_url: str = None) -> str:
    params = {
        's3_endpoint': bucket.endpoint,
        's3_access_key_id': bucket.access_key_id,
        's3_access_key': bucket.access_key,
        's3_bucket_name': bucket.bucket_name,
        'client_cert_fingerprint': p.client_cert_fingerprint,
        'secrets_url': secrets_url
    }

    with open(os.path.join(p.files_prefix, template_name)) as f:
        return Template(f.read()).substitute(params)


@app.before_request
def gen_client_profile():
    g.client_profile = ClientProfile(
        client_cert_serial_number=request.headers.get('X-Ssl-Client-Serial'),
        client_cert_fingerprint=request.headers.get('X-Ssl-Client-Fingerprint'),
        mac_address=request.args.get('mac', default=None, type=str),
        ip_address=request.headers.get("X-Real-Ip", request.remote_addr))


@app.after_request
def log_the_access(response):
    p = g.client_profile
    now = datetime.utcnow()
    print(f"{now} - {p.ip_address} (fingerprint {p.client_cert_fingerprint}) - {request.url} - {response.status}")
    return response


@app.route("/boot/ipxe")
def ipxe():
    p = g.client_profile

    # Do not boot clients without a client certificate
    if p.client_cert_fingerprint is None:
        abort(403, description="The server requires a client certificate")

    # Generate a scratch space for the machine to use for backups
    bucket = p.get_scratch_space_on_b2(current_app.config['BBZ_CLIENT'],
                                       current_app.config['B2_PREFIX'])

    # Base path for the configuration files
    try:
        secrets = gen_conf('secrets', p, bucket)
        expiration_delay = current_app.config['SECRETS_EXPIRATION']
        token = current_app.config['SECRETS_DB'].set(secrets, validity_period=timedelta(seconds=expiration_delay))
        secrets_url = current_app.config['BASE_URL'] + f"/secrets/{token}"
    except Exception:
        secrets_url = None

    # Generate the boot configuration
    try:
        boot_config = gen_conf('boot.ipxe', p, bucket, secrets_url)
        print("Return a configuration for a client:\n%s" % pformat(p))
        print(boot_config)
        print("End of configuration")
        return boot_config
    except Exception as err:
        return '#!ipxe\necho Server Error %s' % err


@app.route("/files/<path:path>")
def files(path):
    # Do not boot clients without a client certificate
    if g.client_profile.client_cert_fingerprint is None:
        abort(403, description="The server requires a client certificate")

    # TODO: Source from the associated b2 bucket!
    return send_from_directory(g.client_profile.files_prefix, path)


@app.route("/secrets/<token>")
def secrets(token):
    # NOTE: The secrets can be accessed by anyone having the URL
    # without needing a client certificate

    if secret := current_app.config['SECRETS_DB'].get(token):
        return secret
    else:
        return abort(404)


@app.route("/update-cfg")
def update_cfg():
    def run(cmd):
        err_msg = f"ERROR: Got the following unexpected error while executing '{cmd}':"
        try:
            return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  shell=True, universal_newlines=True,
                                  cwd=current_app.config['DATA_ROOT'])
        except subprocess.CalledProcessError as e:
            return abort(500, description=f"{err_msg}: {e.stderr}")
        except Exception as e:
            return abort(500, description=f"{err_msg}: {e}")

    fetch = run("git fetch")
    reset = run(f'git reset --hard "`git branch --format "%(upstream:short)"`"')

    return f"""$ {fetch.args}
{fetch.stdout}
$ {reset.args}
{reset.stdout}"""


if __name__ == "__main__":
    def server_name_validator(value):
        # This leaves 20 characters for the fingerprint in the generated bucket name
        if len(value) < 3 or len(value) > 25:
            raise ValueError("The server name length should be 3 to 25 characters long")

        return str(value)

    parser = argparse.ArgumentParser()

    parser.add_argument("-d", "--data-root", default="./files",
                        help="Directory to store ramdisks and kernels and other metadata per-client")
    parser.add_argument("-u", "--base-url", required=True,
                        help="Base URL that the service can be accessed at")
    parser.add_argument("-n", "--server-name", help="Name of the server (3-25 characters)",
                        required=True, type=server_name_validator)
    parser.add_argument("-e", "--secrets-expiration-period",
                        help="Secrets expiration period, in seconds (default: 60)",
                        default=60, type=float)
    args = parser.parse_args()

    # Argument validation
    if not os.path.isdir(args.data_root):
        os.makedirs(args.data_root, exist_ok=True)

    # Connect to backblaze, to create credentials on demand
    bbzc = BbzClient(access_key_id=os.environ.get('BBZ_ACCESS_KEY_ID', 'test-key-id'),
                     access_key=os.environ.get('BBZ_ACCESS_KEY', 'test-key'))

    # Disable the logging of flask, as we replaced it
    log = logging.getLogger("werkzeug")
    log.disabled = True

    app.config.update({
        'DATA_ROOT': args.data_root,
        'BASE_URL': args.base_url,
        'BBZ_CLIENT': bbzc,
        'SECRETS_DB': OneTimeSecretDatabase(),
        'B2_PREFIX': args.server_name if args.server_name else socket.gethostname(),
        'SECRETS_EXPIRATION': args.secrets_expiration_period,
    })
    app.run(host='127.0.0.1', port=8080)
