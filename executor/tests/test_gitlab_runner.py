from unittest.mock import MagicMock, PropertyMock, patch, call
from gitlab_runner import (
    GitlabRunnerAPI,
    GitlabConfig,
    GitlabRunnerConfig)
from operator import attrgetter

import tempfile
import toml
import random
import unittest
import pytest
import attr


@attr.s
class MockRunner(object):
    id: int = attr.ib()
    description: str = attr.ib()


@pytest.fixture
def remote_with_runners():
    remote_api = MagicMock()
    remote_api.runners.list = MagicMock(
        return_value=[
            MockRunner(1, "random-gfx7-9"),
            MockRunner(2, "random-gfx8-3"),
            MockRunner(3, "random-gfx9-3"),
            MockRunner(4, "tchar-gfx8-1"),
            MockRunner(5, "tchar-gfx10-2"),
            MockRunner(6, "mupuf-gfx10-3"),
        ]
    )
    yield remote_api


@pytest.fixture
def tmpfile():
    # The pytest provided fixtures around temporary files are nuts, roll our own.
    tmp_file = tempfile.NamedTemporaryFile()
    yield tmp_file
    tmp_file.close()


@pytest.mark.parametrize(
    "runner,farm_name,expectation",
    [
        (MockRunner(1, "gfx8-1"), 'gfx8', True),
        (MockRunner(2, "random-gfx10-3"), 'gfx8', False),
    ],
)
def test_runner_registration_farm(monkeypatch, runner, farm_name, expectation):
    api = GitlabRunnerConfig(MagicMock(), 'test-registration-token', farm_name=farm_name)
    assert api.runner_is_managed_by_our_farm(runner) is expectation


def test_runner_registration():
    remote_api = MagicMock()
    remote_api.runners = MagicMock()
    api = GitlabRunnerConfig(remote_api, 'test-registration-token')

    api.register('name-1', ['tags-1'])
    remote_api.runners.create.assert_called_with(
        {
            'token': 'test-registration-token',
            'description': 'name-1',
            'tag_list': ['tags-1'],
            'run_untagged': 'false',
            'locked': 'true'
        }
    )


def test_registered_runners(remote_with_runners):
    api = GitlabRunnerConfig(remote_with_runners, 'test-registration-token', farm_name='tchar')
    runners = sorted(api.registered_runners(), key=attrgetter('id'))
    assert len(runners) == 2
    assert runners[0].description == 'tchar-gfx8-1'
    assert runners[1].description == 'tchar-gfx10-2'


def test_unregister():
    remote_api = MagicMock()
    api = GitlabRunnerConfig(remote_api, 'test-registration-token', farm_name='tchar')
    api.unregister(MockRunner(1, "random-gfx7-9"))
    remote_api.runners.delete.assert_called_with(1)


def test_unregister_machine(remote_with_runners):
    api = GitlabRunnerConfig(remote_with_runners, 'test-registration-token', farm_name='tchar')
    api.unregister_machine("tchar-gfx8-1")
    remote_with_runners.runners.delete.assert_called_with(4)
    remote_with_runners.reset_mock()
    api.unregister_machine("mupuf-gfx10-3")
    remote_with_runners.runners.delete.assert_not_called()


def test_runner_runner_names(remote_with_runners):
    api = GitlabRunnerConfig(remote_with_runners, 'test-registration-token', farm_name='tchar')
    assert api.runner_names == ['tchar-gfx8-1', 'tchar-gfx10-2']


def test_runner_pause(remote_with_runners):
    api = GitlabRunnerConfig(remote_with_runners, 'test-registration-token', farm_name='tchar')
    api.gl.http_put.return_value = {"active": False}

    api.set_active("tchar-gfx8-1", False)

    api.gl.http_put.assert_called_with(path='/runners/4', query_data={"active": False})


def test_runner_pause_unknown_runner(remote_with_runners):
    api = GitlabRunnerConfig(remote_with_runners, 'test-registration-token', farm_name='tchar')

    with pytest.raises(ValueError, match="The machine 'unknown' is not found on the Gitlab API"):
        api.set_active("unknown", False)


def test_runner_unpause(remote_with_runners):
    api = GitlabRunnerConfig(remote_with_runners, 'test-registration-token', farm_name='tchar')
    api.gl.http_put.return_value = {"active": True}

    api.set_active("tchar-gfx10-2", True)

    api.gl.http_put.assert_called_with(path='/runners/5', query_data={"active": True})


class GitlabRunnerAPITests(unittest.TestCase):
    @patch("gitlab.Gitlab")
    @patch("gitlab_runner.GitlabRunnerConfig", autospec=True)
    @patch("gitlab_runner.GitlabConfig", autospec=True)
    def setUp(self, gitlab_mock, runner_config_mock, config_mock):
        self.runner_api = GitlabRunnerAPI("url", "file", "access_token", "registration_token", farm_name="mupuf")
        self.remote_config = self.runner_api.remote_config
        self.local_config = self.runner_api.local_config

        self.machine_name = 'gfx8-1'
        self.machine_tags = ['tag1', 'tag2']

    @patch("gitlab.Gitlab")
    @patch("gitlab_runner.GitlabRunnerConfig", autospec=True)
    @patch("gitlab_runner.GitlabConfig", autospec=True)
    def test_generic_runner(self, gitlab_mock, runner_config_mock, config_mock):
        runner_api = GitlabRunnerAPI("url", "file", "access_token", "registration_token",
                                     farm_name="mupuf", expose_generic_runner=False)

        runner_api.remote_config.unregister_machine.assert_called_with(runner_api.generic_runner_name)
        runner_api.local_config.remove_machine(runner_api.generic_runner_name)

    def test_noRunners(self):
        self.remote_config.find_by_name.return_value = None
        self.local_config.find_by_name.return_value = None

        self.runner_api.expose(self.machine_name, self.machine_tags)

        self.remote_config.register.assert_called_with(self.machine_name,
                                                       self.machine_tags)

    def test_localRunnerNoRemote(self):
        self.remote_config.find_by_name.return_value = None
        self.local_config.find_by_name.return_value = 'cookie'
        type(self.remote_config.register.return_value).token = \
            PropertyMock(return_value=42)

        self.runner_api.expose(self.machine_name, self.machine_tags)

        self.local_config.remove_runner.assert_called_with('cookie')
        self.remote_config.register.assert_called_with(self.machine_name,
                                                       self.machine_tags)
        self.local_config.add_runner.assert_called_with(self.machine_name,
                                                        42, cpus=None,
                                                        memory=None, swap=None,
                                                        memory_reservation=None)

    def test_remoteRunnerNoLocalNoActiveJobs(self):
        pm = PropertyMock(return_value=42)
        self.remote_config.find_by_name = MagicMock(return_value=pm)
        self.local_config.find_by_name.return_value = None
        self.remote_config.active_jobs.return_value = False
        type(self.remote_config.register.return_value).token = \
            PropertyMock(return_value=42)

        self.runner_api.expose(self.machine_name, self.machine_tags,
                               cpus=2, memory="memory", swap="swap",
                               memory_reservation="reservation")

        self.remote_config.unregister.assert_called_with(pm)
        self.remote_config.register.assert_called_with(self.machine_name,
                                                       self.machine_tags)
        self.local_config.add_runner.assert_called_with(self.machine_name,
                                                        42, cpus=2,
                                                        memory="memory", swap="swap",
                                                        memory_reservation="reservation")

    def test_remoteRunnerNoLocalActiveJobs(self):
        self.remote_config.find_by_name = MagicMock()
        self.local_config.find_by_name.return_value = None
        self.remote_config.active_jobs.return_value = True
        type(self.remote_config.register.return_value).token = \
            PropertyMock(return_value=42)

        self.runner_api.expose(self.machine_name, self.machine_tags)

        self.remote_config.unregister.assert_not_called()
        self.remote_config.register.assert_not_called()
        self.local_config.add_runner.assert_not_called()

    def test_localRunnerAndRemote(self):
        self.remote_config.find_by_name.return_value = 'cookie1'
        self.local_config.find_by_name.return_value = 'cookie2'

        self.runner_api.expose(self.machine_name, self.machine_tags)

        self.remote_config.unregister.assert_not_called()
        self.remote_config.register.assert_not_called()
        self.local_config.add_runner.assert_not_called()

    def test_unregister(self):
        self.runner_api.remove(self.machine_name)

        self.remote_config.unregister_machine.assert_called_with(self.machine_name)
        self.local_config.remove_machine.assert_called_with(self.machine_name)

    def test_exposed_machines(self):
        self.remote_config.runner_names = ["machine 1", "machine 2"]
        self.local_config.runner_names = ["machine 2", "machine 3"]

        assert self.runner_api.exposed_machines == set(["machine 1", "machine 2", "machine 3"])

    def test_drop_unsynced_runners(self):
        self.remote_config.return_value.registered_runners = [
            MockRunner(1, description="machine 1"),
            MockRunner(2, description="machine 2"),
        ]
        self.remote_config.runner_names = ["machine 1", "machine 2"]
        self.local_config.runner_names = ["machine 2", "machine 3"]

        assert self.runner_api.exposed_machines == set(["machine 1", "machine 2", "machine 3"])

        self.runner_api.drop_unsynced_runners()

        self.remote_config.unregister_machine.assert_has_calls([call("machine 1"),
                                                                call("machine 3")],
                                                               any_order=True)
        self.local_config.remove_machine.assert_has_calls([call("machine 1"),
                                                           call("machine 3")],
                                                          any_order=True)

    def test_pause(self):
        self.runner_api.pause("toto")
        self.remote_config.set_active.assert_called_with("toto", False)

    def test_unpause(self):
        self.runner_api.unpause("toto")
        self.remote_config.set_active.assert_called_with("toto", True)


def test_config_corrupted_configuration(tmpfile):
    tmpfile.write(b'{broke n toml {};;;;}')
    _ = GitlabConfig(tmpfile.name)  # Test the side-effect in the init
    assert GitlabConfig.DEFAULT_CONFIG == toml.load(tmpfile.name)


def test_config_file_not_found(tmpfile):
    tmpfile.close()
    _ = GitlabConfig(tmpfile.name)  # Test the side-effect in the init
    assert GitlabConfig.DEFAULT_CONFIG == toml.load(tmpfile.name)


def test_config_default_configuration(tmpfile):
    config = GitlabConfig(tmpfile.name)
    assert GitlabConfig.DEFAULT_CONFIG == toml.load(tmpfile.name)
    assert len(config.runners()) == 0
    assert config.find_by_name("Johnson") is None


@patch('config.job_environment_vars')
def test_config_add_runner(job_env, tmpfile):
    job_env.return_value = {'MINIO_URL': 'testing-url'}
    config = GitlabConfig(tmpfile.name)
    pop = range(1, 10)
    for i in pop:
        config.add_runner(f'test-runner-{i}', f'token-{i}')
        assert len(config.runners()) == i
    for i in random.sample(pop, k=len(pop)):
        assert config.find_by_name('test-runner-x') is None
        added_runner = config.find_by_name(f'test-runner-{i}')
        assert added_runner is not None
        assert added_runner['token'] == f'token-{i}'
        assert added_runner['docker']['image'].find('gitlab-trigger')
        assert len(added_runner['docker']['volumes']) == 3


@patch('config.job_environment_vars')
def test_config_remove_runner(job_env, tmpfile):
    job_env.return_value = {'MINIO_URL': 'testing-url'}
    config = GitlabConfig(tmpfile.name)
    for i in range(1, 10):
        config.add_runner(f'test-runner-{i}', f'token-{i}')
    for i in range(1, 5):
        runner = config.find_by_name(f'test-runner-{i}')
        assert runner is not None
        config.remove_runner(runner)
        assert len(config.runners()) == 10 - i - 1


def test_runner_names(tmpfile):
    config = GitlabConfig(tmpfile.name)
    assert config.runner_names == []
