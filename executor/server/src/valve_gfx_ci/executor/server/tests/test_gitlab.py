from unittest.mock import MagicMock, patch, mock_open
from dataclasses import dataclass

from server.gitlab import GitlabRunnerRegistration, register_runner, unregister_runner
from server.gitlab import verify_runner_token, generate_runner_config, SanitizedFieldsMixin
from server.mars import MarsDB
import server.config as config

from jinja2 import Template


def test_SanitizedFieldsMixin__from_api():
    @dataclass
    class Dataclass(SanitizedFieldsMixin):
        field1: int
        field2: int

    assert Dataclass.from_api({"field1": 1, "field2": 2, "field3": 3}) == Dataclass(field1=1, field2=2)


def test_register_runner():
    url = "my url"
    registration_token = "reg_token"
    description = "toto"
    tag_list = ["tag1", "tag2"]

    runner_id = 1234
    runner_token = "my token"

    post_mock_return_value = MagicMock(status_code=201,
                                       json=MagicMock(return_value={"id": runner_id, "token": runner_token}))
    with patch("server.gitlab.requests.post", return_value=post_mock_return_value) as post_mock:
        r = register_runner(gitlab_url=url, registration_token=registration_token,
                            description=description, tag_list=tag_list)
        assert r == GitlabRunnerRegistration(id=runner_id, token=runner_token)

        post_mock.assert_called_with(f"{url}/api/v4/runners",
                                     params={'token': registration_token,
                                             'description': description,
                                             'tag_list': ",".join(tag_list),
                                             'run_untagged': False,
                                             'maximum_timeout': 3600})

    with patch("server.gitlab.requests.post", return_value=MagicMock(status_code=403)) as post_mock:
        r = register_runner(gitlab_url=url, registration_token=registration_token,
                            description=description, tag_list=tag_list)
        assert r is None


def test_unregister_runner():
    url = "my url"
    runner_token = "my token"

    with patch("server.gitlab.requests.delete", return_value=MagicMock(status_code=204)) as delete_mock:
        assert unregister_runner(gitlab_url=url, token=runner_token)
        delete_mock.assert_called_with(f"{url}/api/v4/runners", params={"token": runner_token})

    with patch("server.gitlab.requests.delete", return_value=MagicMock(status_code=200)) as delete_mock:
        assert not unregister_runner(gitlab_url=url, token=runner_token)


def test_verify_runner_token():
    url = "my url"
    runner_token = "my token"

    with patch("server.gitlab.requests.post", return_value=MagicMock(status_code=200)) as post_mock:
        assert verify_runner_token(gitlab_url=url, token=runner_token)
        post_mock.assert_called_with(f"{url}/api/v4/runners/verify", params={"token": runner_token})

    with patch("server.gitlab.requests.post", return_value=MagicMock(status_code=403)) as post_mock:
        assert not verify_runner_token(gitlab_url=url, token=runner_token)


def test_generate_runner_config():
    template_data = "data"

    with patch("server.gitlab.Template") as template_mock:
        with patch("builtins.open", mock_open(read_data=template_data)) as mock_file:
            with patch("server.gitlab.psutil") as psutil_mock:
                psutil_mock.cpu_count.return_value = 4
                psutil_mock.virtual_memory.return_value.total = 1e9

                mars_db = MagicMock()

                generate_runner_config(mars_db)

                template_mock.assert_called_with(template_data)
                template_mock.return_value.render.assert_called_with(config=config, mars_db=mars_db,
                                                                     cpu_count=4, ram_total_MB=1000)

                mock_file.return_value.write.assert_called_with(template_mock.return_value.render.return_value)


def test_gitlab_runner_config_template():
    pdus = {
        "apc": {
            "driver": "apc_drv",
            "config": {}
        }
    }

    duts = {
        "de:ad:be:ef:ca:fe": {
            "base_name": "gfx9",
            "tags": ["tag1", "tag2"],
            "ip_address": "10.42.0.1",
            "local_tty_device": "ttyS0",
            "gitlab": {
                "freedesktop": {
                    "token": "mytoken",
                    "exposed": True
                }
            },
            "pdu": "apc",
            "pdu_port_id": 0,
            "pdu_off_delay": 30,
            "ready_for_service": True,
            "is_retired": False
        }
    }

    gitlab = {
        "freedesktop": {
            "url": "https://gitlab.freedesktop.org/",
            "registration_token": "<token>",
            "expose_runners": True,
            "maximum_timeout": 43200,
            "gateway_runner": {
                "token": "<token>",
                "exposed": True
            }
        }
    }

    mars_db = MarsDB(pdus=pdus, duts=duts, gitlab=gitlab)

    with open(config.GITLAB_CONF_TEMPLATE_FILE) as f:
        template = f.read()

    # Single board computers
    params = {
        "config": config,
        "mars_db": mars_db,
        "cpu_count": 4,
        "ram_total_MB": 4096
    }
    config_toml = str(Template(template).render(**params))
    assert 'cpus = 4  # Gateway runner CPU allocation'
    assert 'memory = "2048 MB" # Gateway runner memory allocation' in config_toml
    assert 'memory_swap = "2457 MB" # Gateway runner memory hard limit' in config_toml
    assert 'memory_reservation = "1024 MB" # Gateway runner memory soft limit' in config_toml

    # Recycled x86 computer
    params = {
        "config": config,
        "mars_db": mars_db,
        "cpu_count": 8,
        "ram_total_MB": 16384
    }
    config_toml = str(Template(template).render(**params))
    assert 'cpus = 8  # Gateway runner CPU allocation'
    assert 'memory = "12288 MB" # Gateway runner memory allocation' in config_toml
    assert 'memory_swap = "14745 MB" # Gateway runner memory hard limit' in config_toml
    assert 'memory_reservation = "6144 MB" # Gateway runner memory soft limit' in config_toml

    # Beefy server-class computer
    params = {
        "config": config,
        "mars_db": mars_db,
        "cpu_count": 32,
        "ram_total_MB": 131072
    }
    config_toml = str(Template(template).render(**params))
    assert 'cpus = 32  # Gateway runner CPU allocation'
    assert 'memory = "126976 MB" # Gateway runner memory allocation' in config_toml
    assert 'memory_swap = "152371 MB" # Gateway runner memory hard limit' in config_toml
    assert 'memory_reservation = "63488 MB" # Gateway runner memory soft limit' in config_toml
