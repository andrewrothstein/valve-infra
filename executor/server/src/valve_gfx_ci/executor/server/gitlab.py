from dataclasses import dataclass
from jinja2 import Template
import requests
import psutil

from .logger import logger
from . import config


class SanitizedFieldsMixin:
    @classmethod
    def from_api(cls, fields, **kwargs):
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}

        sanitized_kwargs = dict(fields)
        for arg in fields:
            if arg not in valid_fields:
                sanitized_kwargs.pop(arg)

        return cls(**sanitized_kwargs, **kwargs)


@dataclass
class GitlabRunnerRegistration(SanitizedFieldsMixin):
    id: int
    token: str


def register_runner(gitlab_url: str, registration_token: str,
                    description: str, tag_list: list[str],
                    run_untagged: bool = False, maximum_timeout: int = 3600):
    params = {
        "token": registration_token,
        "description": description,
        "tag_list": ",".join(tag_list),
        "run_untagged": run_untagged,
        "maximum_timeout": maximum_timeout
    }

    r = requests.post(f"{gitlab_url}/api/v4/runners", params=params)
    if r.status_code == 201:
        return GitlabRunnerRegistration.from_api(r.json())
    else:
        return None


def unregister_runner(gitlab_url: str, token: str):
    r = requests.delete(f"{gitlab_url}/api/v4/runners", params={"token": token})
    return r.status_code == 204


def verify_runner_token(gitlab_url: str, token: str):
    # WARNING: The interface for this function is so that we will return
    # False *ONLY* when Gitlab tells us the token is invalid.
    # If Gitlab is unreachable, we will return True.
    #
    # This is a conscious decision, as we never want to throw away a perfectly-good
    # token, just because of a network outtage.

    r = requests.post(f"{gitlab_url}/api/v4/runners/verify", params={"token": token})
    return not r.status_code == 403


def generate_runner_config(mars_db):
    logger.info("Generate the GitLab runner configuration")
    with open(config.GITLAB_CONF_TEMPLATE_FILE) as f:
        params = {
            "config": config,
            "mars_db": mars_db,
            "cpu_count": psutil.cpu_count(),
            "ram_total_MB": psutil.virtual_memory().total / 1e6
        }
        config_toml = Template(f.read()).render(**params)

    with open(config.GITLAB_CONF_FILE, 'w') as f:
        f.write(config_toml)
