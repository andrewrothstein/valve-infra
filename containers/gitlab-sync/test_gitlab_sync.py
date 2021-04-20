from datetime import datetime
import gitlab_sync
import attr
from gitlab_sync import (
    GitlabRunnerAPI,
    GitlabConfig,
    sync_mars_machine_with_coordinator,
    process_mars_events,
    parse_iso8601_date,
    parse_event_diff,
    Event,
)
from operator import attrgetter
import copy
import tempfile
import toml
import random
import unittest
from unittest.mock import create_autospec, MagicMock, PropertyMock
import pytest
import requests
import responses


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
    monkeypatch.setenv('FARM_NAME', farm_name)
    api = GitlabRunnerAPI(MagicMock(), 'test-registration-token')
    assert api.runner_is_managed_by_our_farm(runner) is expectation


def test_runner_registration():
    remote_api = MagicMock()
    remote_api.runners = MagicMock()
    api = GitlabRunnerAPI(remote_api, 'test-registration-token')

    api.register('name-1', 'tags-1')
    remote_api.runners.create.assert_called_with(
        {
            'token': 'test-registration-token',
            'description': 'name-1',
            'tag_list': 'tags-1',
            'run_untagged': 'false',
            'locked': 'true'
        }
    )


def test_registered_runners(remote_with_runners):
    api = GitlabRunnerAPI(remote_with_runners, 'test-registration-token', farm_name='tchar')
    runners = sorted(api.registered_runners(), key=attrgetter('id'))
    assert len(runners) == 2
    assert runners[0].description == 'tchar-gfx8-1'
    assert runners[1].description == 'tchar-gfx10-2'


def test_unregister():
    remote_api = MagicMock()
    api = GitlabRunnerAPI(remote_api, 'test-registration-token', farm_name='tchar')
    api.unregister(MockRunner(1, "random-gfx7-9"))
    remote_api.runners.delete.assert_called_with(1)


def test_unregister_machine(remote_with_runners):
    api = GitlabRunnerAPI(remote_with_runners, 'test-registration-token', farm_name='tchar')
    api.unregister_machine({"full_name": "tchar-gfx8-1"})
    remote_with_runners.runners.delete.assert_called_with(4)
    remote_with_runners.reset_mock()
    api.unregister_machine({"full_name": "mupuf-gfx10-3"})
    remote_with_runners.runners.delete.assert_not_called()


class MarsSyncTests(unittest.TestCase):
    def setUp(self):
        # The Gitlab API is mostly generated dynamically, which makes
        # testing it a mess. You can't use auto-specing. Lukcily, our
        # testing needs are minor.
        self.remote_api = MagicMock()
        gitlab_sync.sync_tags = MagicMock()
        self.api = create_autospec(GitlabRunnerAPI, spec_set=True)
        self.machine_name = 'gfx8-1'
        self.machine_tags = ['tag1', 'tag2']
        self.machine = {
            'full_name': self.machine_name,
            'tags': self.machine_tags,
        }
        self.config = create_autospec(GitlabConfig, spec_set=True)

    def test_noRunners(self):
        self.api.find_by_name.return_value = None
        self.config.find_by_name.return_value = None
        sync_mars_machine_with_coordinator(self.machine,
                                           self.config,
                                           self.api)
        self.api.register.assert_called_with(self.machine_name,
                                             self.machine_tags)

    def test_localRunnerNoRemote(self):
        self.api.find_by_name.return_value = None
        self.config.find_by_name.return_value = 'cookie'
        type(self.api.register.return_value).token = \
            PropertyMock(return_value=42)
        sync_mars_machine_with_coordinator(self.machine,
                                           self.config,
                                           self.api)
        self.config.remove_runner.assert_called_with('cookie')
        self.api.register.assert_called_with(self.machine_name,
                                             self.machine_tags)
        self.config.add_runner.assert_called_with(self.machine_name,
                                                  42)

    def test_remoteRunnerNoLocalNoActiveJobs(self):
        pm = PropertyMock(return_value=42)
        m = MagicMock(return_value=pm)
        self.api.find_by_name = m
        self.config.find_by_name.return_value = None
        self.api.active_jobs.return_value = False
        type(self.api.register.return_value).token = \
            PropertyMock(return_value=42)
        sync_mars_machine_with_coordinator(self.machine,
                                           self.config,
                                           self.api)
        self.api.unregister.assert_called_with(pm)
        self.api.register.assert_called_with(self.machine_name,
                                             self.machine_tags)
        self.config.add_runner.assert_called_with(self.machine_name,
                                                  42)

    def test_remoteRunnerNoLocalActiveJobs(self):
        self.api.find_by_name = MagicMock()
        self.config.find_by_name.return_value = None
        self.api.active_jobs.return_value = True
        type(self.api.register.return_value).token = \
            PropertyMock(return_value=42)
        sync_mars_machine_with_coordinator(self.machine,
                                           self.config,
                                           self.api)
        self.api.unregister.assert_not_called()
        self.api.register.assert_not_called()
        self.config.add_runner.assert_not_called()

    def test_localRunnerAndRemote(self):
        self.api.find_by_name.return_value = 'cookie1'
        self.config.find_by_name.return_value = 'cookie2'
        sync_mars_machine_with_coordinator(self.machine,
                                           self.config,
                                           self.api)
        self.api.unregister.assert_not_called()
        self.api.register.assert_not_called()
        self.config.add_runner.assert_not_called()


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


def test_config_add_runner(tmpfile):
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


def test_config_remove_runner(tmpfile):
    config = GitlabConfig(tmpfile.name)
    for i in range(1, 10):
        config.add_runner(f'test-runner-{i}', f'token-{i}')
    for i in range(1, 5):
        runner = config.find_by_name(f'test-runner-{i}')
        assert runner is not None
        config.remove_runner(runner)
        assert len(config.runners()) == 10 - i - 1


class ProcessMarsEventsTests(unittest.TestCase):
    def setUp(self):
        # The Gitlab API is mostly generated dynamically, which makes
        # testing it a mess. You can't use auto-specing. Lukcily, our
        # testing needs are minor.
        self.remote_api = MagicMock()
        gitlab_sync.sync_mars_machine_with_coordinator = MagicMock()
        self.api = create_autospec(GitlabRunnerAPI, spec_set=True)
        self.machine_name = 'gfx8-1'
        self.machine_tags = ['tag1', 'tag2']
        self.machine = {
            'full_name': self.machine_name,
            'tags': self.machine_tags,
        }
        self.config = create_autospec(GitlabConfig, spec_set=True)
        self.rsps = responses.RequestsMock(False)
        self.events = [
            {
                'category': 'machine-updated',
                'machine': 'http://10.42.0.1/machines/00:01:02:03:04:05',
                'diff': '{"values_changed": {"root.ready_for_service": {"new_value": true, "old_value": "false"}}}',
                'date': '2021-02-22T22:31:31Z'
            },
            {
                'category': 'machine-updated',
                'machine': 'http://10.42.0.1/machines/11:11:22:33:22:33',
                'diff': '{"values_changed": {"root.ready_for_service": {"new_value": true, "old_value": "false"}}}',
                'date': '2021-02-22T22:32:00Z'
            },
        ]
        for event in self.events:
            # Add an empty machine return value, extend as needed in the future
            self.rsps.add(responses.GET,
                          event['machine'],
                          json={})

        self.rsps.start()

    def tearDown(self):
        self.rsps.stop()
        self.rsps.reset()

    def test_noEvents(self):
        process_mars_events([], self.config, self.api)
        assert gitlab_sync.sync_mars_machine_with_coordinator.call_count == 0

    def test_basic(self):
        gitlab_sync.sync_mars_machine_with_coordinator.return_value = True
        last_checked = process_mars_events(self.events, self.config, self.api)
        assert gitlab_sync.sync_mars_machine_with_coordinator.call_count == len(self.events)
        assert last_checked == parse_iso8601_date(self.events[-1]['date'])

    def test_exception(self):
        events = copy.deepcopy(self.events)
        events[-1]['date'] = 'not-a-date'
        gitlab_sync.sync_mars_machine_with_coordinator.return_value = True
        with pytest.raises(ValueError):
            process_mars_events(events, self.config, self.api)
        assert gitlab_sync.sync_mars_machine_with_coordinator.call_count == len(events)

    def test_syncMarsWithCoordinatorFails(self):
        gitlab_sync.sync_mars_machine_with_coordinator.return_value = False
        assert process_mars_events(self.events, self.config, self.api) is False
        assert gitlab_sync.sync_mars_machine_with_coordinator.call_count == 1

    def test_connectionerror(self):
        events = copy.deepcopy(self.events)
        events[0]['machine'] = 'http://connection-error.invalid'
        gitlab_sync.sync_mars_machine_with_coordinator.return_value = True
        with pytest.raises(requests.exceptions.ConnectionError):
            process_mars_events(events, self.config, self.api)
        assert gitlab_sync.sync_mars_machine_with_coordinator.call_count == 0

    def test_non_interesting_events(self):
        events = copy.deepcopy(self.events)
        for event in events:
            event['category'] = 'machine-created'
        assert process_mars_events(events, self.config, self.api) == \
            parse_iso8601_date(events[-1]['date'])
        assert gitlab_sync.sync_mars_machine_with_coordinator.call_count == 0

    def test_irrelevant_events(self):
        events = copy.deepcopy(self.events)
        for event in events:
            event['diff'] = '{"values_changed": {"root.ip_address": {"new_value": "1.1.1.1", "old_value": "8.8.8.8"}}}'
        assert process_mars_events(events, self.config, self.api) == \
            parse_iso8601_date(events[-1]['date'])
        assert gitlab_sync.sync_mars_machine_with_coordinator.call_count == 0

    def test_out_of_service_event(self):
        event = {
            'category': 'machine-updated',
            'machine': 'http://10.42.0.1/machines/00:01:02:03:04:05',
            'diff': '{"values_changed": {"root.ready_for_service": {"new_value": false, "old_value": true}}}',
            'date': '2021-02-22T22:31:31Z'
        }
        assert process_mars_events([event], self.config, self.api) == \
            parse_iso8601_date(event['date'])
        assert gitlab_sync.sync_mars_machine_with_coordinator.call_count == 0
        self.api.unregister_machine.assert_called_once()


def test_parse_iso8601_date():
    assert parse_iso8601_date('2021-02-17T17:04:24.579263Z') == \
        datetime(2021, 2, 17, 17, 4, 24, 579263)

    assert parse_iso8601_date('2021-02-17T17:04:24.579263') == \
        datetime(2021, 2, 17, 17, 4, 24, 579263)

    with pytest.raises(ValueError):
        parse_iso8601_date('garbage.579263')


@pytest.mark.parametrize(
    "diff,expectation",
    [
        ({}, Event.OTHER),
        ({"values_changed": {
            "root.ready_for_service": {
                "new_value": True,
                "old_value": False
            }
        }}, Event.READY_FOR_SERVICE),
        ({"values_changed": {
            "root.ready_for_service": {
                "new_value": False,
                "old_value": True
            }
        }}, Event.OUT_OF_SERVICE),
        ({"values_changed": {
            "root.tags": {
                "new_value": {'tag1', 'tag2'},
                "old_value": {'tag1'},
            }
        }}, Event.METADATA_CHANGE),
        ({"values_changed": {
            "root.base_name": {
                "new_value": 'martin-farm',
                "old_value": 'charlie-farm',
            }
        }}, Event.METADATA_CHANGE),
        ({"values_changed": {
            "root.ip_address": {
                "new_value": '10.42.0.10',
                "old_value": '10.42.0.9',
            }
        }}, Event.OTHER),
    ],
)
def test_parse_event_diff(diff, expectation):
    assert parse_event_diff(diff) is expectation
