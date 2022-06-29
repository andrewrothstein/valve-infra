from unittest.mock import MagicMock, patch, mock_open
from dataclasses import dataclass

from server.gitlab import GitlabRunnerRegistration, register_runner, unregister_runner
from server.gitlab import verify_runner_token, generate_runner_config, SanitizedFieldsMixin
import server.config as config


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
            mars_db = MagicMock()

            generate_runner_config(mars_db)

            template_mock.assert_called_with(template_data)
            template_mock.return_value.render.assert_called_with(config=config, mars_db=mars_db)

            mock_file.return_value.write.assert_called_with(template_mock.return_value.render.return_value)
