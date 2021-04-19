#!/usr/bin/env python3
# -*- mode: python -*-

# See also: https://docs.gitlab.com/ee/api/runners.html

from pprint import pformat
import gitlab
from datetime import datetime
import os
import requests
import toml
import time
import json
from logging import getLogger, getLevelName, Formatter, StreamHandler
import click

logger = getLogger(__name__)
logger.setLevel(getLevelName('DEBUG'))
log_formatter = \
    Formatter("%(asctime)s [%(levelname)s] %(name)s: "
              "%(message)s")
console_handler = StreamHandler()
console_handler.setFormatter(log_formatter)
logger.addHandler(console_handler)


class GitlabRunnerAPI:
    def __init__(self, remote_api, runner_registration_token):
        self.gl = remote_api
        self.registration_token = runner_registration_token

    def register(self, name, tags):
        """Register a new runner with the given name and tag list"""
        registration_config = {
            'token': self.registration_token,
            'description': name,
            'tag_list': tags,
            'run_untagged': 'false',  # Whether the runner should handle untagged jobs
            # Don't want randoms using our CI resources outside of our mirror project
            'locked': 'true',  # Whether the runner should be locked for current project
        }
        return self.gl.runners.create(registration_config)

    def runners(self):  # pragma: nocover
        return self.gl.runners.list()

    def unregister(self, runner):  # pragma: nocover
        """Remove the given runner from the server."""
        self.gl.runners.delete(runner.id)

    def find_by_name(self, name):  # pragma: nocover
        """Find a runner with a description matching _name_. Return
        the matching runner structure"""
        for runner in self.runners():
            if runner.description == name:
                return runner

    def tags(self, runner_id):  # pragma: nocover
        runner_details = self.gl.runners.get(runner_id)
        return runner_details.tag_list

    def active_jobs(self, runner_id):  # pragma: nocover
        runner_details = self.gl.runners.get(runner_id)
        return runner_details.jobs.list(status='running')

    def set_tags(self, runner_id, tags):  # pragma: nocover
        runner = self.gl.runners.get(runner_id)
        runner.tag_list = tags
        runner.save()


class GitlabConfig:
    DEFAULT_CONFIG = {
        'check_interval': 0,
        'concurrent': 128,
        'session_server': {'session_timeout': 1800}
    }

    def __init__(self, config_path):
        self.config_path = config_path
        self._reload_config()
        self._save()
        logger.debug("starting with the following configuration:\n"
                     f"{pformat(self.config)}")

    def _save(self):
        logger.debug("saving configuration...")
        with open(self.config_path, 'w') as f:
            toml.dump(self.config, f)

    def _reload_config(self):
        # Note: It's quite inefficient to reload the configuration on
        # our property accesses, but it keeps the client usage very
        # simple, and this isn't a high throughput situation, so screw
        # it.
        try:
            self.config = toml.load(self.config_path) or \
                GitlabConfig.DEFAULT_CONFIG
        except FileNotFoundError:
            self.config = GitlabConfig.DEFAULT_CONFIG

    def local_runners(self):
        self._reload_config()
        if "runners" not in self.config:
            self.config["runners"] = []
        return self.config["runners"]

    def find_by_name(self, name):
        for runner in self.local_runners():
            if runner["name"] == name:
                return runner

    def remove_runner(self, runner):
        self.local_runners()[:] = [r for r in self.local_runners()
                                   if r['name'] != runner['name']]
        self._save()

    def add_runner(self, name, token):
        volumes = [
            'local-container-volume:/var/lib/containers',
            '/var/run/docker.sock:/var/run/docker.sock',
            '/cache'
        ]
        config = {
            'name': name,
            'limit': 1,
            'url': 'https://gitlab.freedesktop.org/',
            'token': token,
            'executor': 'docker',
            'custom_build_dir': {},
            'cache': {'s3': {}, 'gcs': {}, 'azure': {}},
            'docker': {
                'tls_verify': False,
                'image':
                'registry.freedesktop.org/mupuf/valve-infra/gitlab-job-runner',
                'privileged': True,
                'disable_entrypoint_overwrite': False,
                'oom_kill_disable': False,
                'disable_cache': False,
                'volumes': volumes,
                'network_mode': 'host',
                'shm_size': 0
            }
        }
        logger.info(f"adding a new runner:\n{pformat(config)}")
        self.local_runners().append(config)
        self._save()


def sync_tags(runner_api, name, local_tags):  # pragma: nocover
    remote_runner = runner_api.find_by_name(name)
    remote_tags = runner_api.tags(remote_runner.id)
    if not set(local_tags) == set(remote_tags):
        logger.info(f"""
local vs remote tags are out of sync: {local_tags} vs
{remote_tags} setting remote tags to local tags...
""")
        runner_api.set_tags(remote_runner.id, local_tags)


def sync_mars_machine_with_coordinator(machine, gitlab_config, runner_api):
    name, tags = machine["full_name"], machine["tags"]

    local_runner = gitlab_config.find_by_name(name)
    remote_runner = runner_api.find_by_name(name)

    def register():
        resp = runner_api.register(name, tags)
        gitlab_config.add_runner(name, resp.token)

    if not local_runner and not remote_runner:
        logger.info(f"There is neither a local nor remote runner for {name}."
                    " Registering...")
        register()
    elif not local_runner and remote_runner:
        logger.info(f"There is remote runner named {name}, but not local."
                    "Deleting remote runner and reregistering...")
        running_jobs = runner_api.active_jobs(remote_runner.id)
        if running_jobs:
            logger.error("The remote runner is actively running jobs. "
                         "For now this means you should manually sort "
                         "that out and come back.")
            return False
        runner_api.unregister(remote_runner)
        register()
    elif local_runner and not remote_runner:
        logger.info(f"{name} exists locally but not on the remote. "
                    "Removing locally and reregistering...")
        gitlab_config.remove_runner(local_runner)
        register()
    elif local_runner and remote_runner:
        pass

    # Both sides are in agreement now, make sure the tags are in agreement too!
    sync_tags(runner_api, name, tags)

    return True


def mars_fetch_machines(mars_host, gitlab_config, runner_api):  # pragma: nocover
    logger.info(f"Fetching machines from MaRS at {mars_host}")
    while True:
        try:
            r = requests.get(
                f'{mars_host}/api/v1/machine/?ready_for_service=true')
            r.raise_for_status()
            machines = r.json()
            if not machines:
                break
            logger.info(f"there are {len(machines)} machines ready"
                        " for service, initializing...")
            success = True
            for machine in machines:
                logger.info(f"configuring\n{pformat(machine)}")
                if not sync_mars_machine_with_coordinator(machine,
                                                          gitlab_config,
                                                          runner_api):
                    logger.error("An error occurred while synchronizing "
                                 f"{pformat(machine)}. "
                                 "Will attempt to refetch machines and "
                                 "try again")
                    success = False
                    break
            if success:
                break
            time.sleep(5)
        except requests.ConnectionError as err:
            logger.info(f"Initial machine fetch from MaRS ({mars_host}) "
                        f"has failed. Error: {err}. "
                        "Trying again...")
            time.sleep(5)


def parse_iso8601_date(d):
    # For some reason the datetime parser doesn't like the lone Z, I
    # thought it was spec'd. It does happily accept +00:00 in lieu of
    # Z.
    return datetime.fromisoformat(d.removesuffix("Z"))


def relevant_event_diff(diff):
    if 'values_changed' not in diff:
        return False
    values_changed = diff['values_changed']
    if 'root.ready_for_service' in values_changed and \
       values_changed['root.ready_for_service']['new_value']:
        return True
    return any([field in values_changed for field in
                ['root.tags', 'root.base_name']])


def process_mars_events(events, gitlab_config, runner_api):
    """Process each event in _events_, if any are relevant for
GitLab, perform the necessary synchronization.

Returns False if no events were processed, otherwise, it will return
the time of the last event processed plus 1 microsecond (the smallest
time unit in datetime) so that clients can do a best-effort refetch of
events after the last one processed"""
    if not events:
        return False
    logger.info(f"===== events since last fetch =====\n:{pformat(events)}")
    last_checked = False
    try:
        for event in events:
            if event['category'] != 'machine-updated':
                logger.debug(f'ignoring {event}, only considering udpate events')
                last_checked = parse_iso8601_date(event['date'])
                continue

            diff = json.loads(event['diff'])
            r = requests.get(event['machine'])
            r.raise_for_status()
            machine = r.json()
            if not relevant_event_diff(diff):
                logger.info("ignoring event, does not have a relevant diff")
                last_checked = parse_iso8601_date(event['date'])
                continue
            logger.debug(f"processing {event}")
            if not sync_mars_machine_with_coordinator(machine,
                                                      gitlab_config,
                                                      runner_api):
                logger.error("An error occurred while synchronizing "
                             f"{pformat(machine)}.")
                break
            last_checked = parse_iso8601_date(event['date'])
        return last_checked
    except requests.ConnectionError:
        return last_checked


def poll_mars_forever(mars_host, gitlab_config, runner_api):  # pragma: nocover
    logger.info("Polling for changes in MaRS...")
    last_checked = datetime.now()

    mars_fetch_machines(mars_host, gitlab_config, runner_api)

    logger.info("Initial machine fetch complete, monitoring for events...")
    while True:
        try:
            r = requests.get(
                f'{mars_host}/api/v1/events/?since={last_checked.isoformat()}')
            r.raise_for_status()
            events = r.json()
            last_event_time = process_mars_events(events,
                                                  gitlab_config,
                                                  runner_api)
            last_checked = last_event_time or last_checked
        except requests.ConnectionError:
            pass
        finally:
            time.sleep(5)


def runner_is_managed_by_our_farm(runner):
    farm_name = os.environ.get('FARM_NAME', 'unknown')
    return runner.description.startswith(farm_name)


def initial_sync(config, rapi):  # pragma: nocover
    """Anything registered remotely that is not known locally, remove it.
Anything known locally that is not registered remotely, register it.
This ensure we start in a sane state."""
    logger.info("making the remote and local configurations agree...")

    remote_runners = rapi.runners()
    local_runners = config.local_runners()

    for runner in remote_runners:
        if not runner_is_managed_by_our_farm(runner):
            logger.info(f"{runner.description} ignored, since it is "
                        "not managed by our farm")
            continue

        logger.debug(f"{runner.description} is registered on the server, "
                     f"tagged with:\n{pformat(rapi.tags(runner.id))}")

        # Convention used by us
        machine_name = runner.description
        local_runner = config.find_by_name(machine_name)

        if not local_runner:
            logger.warning(f"{runner.description} is registered on the "
                           "coordinator but is not locally, removing from "
                           "coordinator...")
            rapi.unregister(runner)

    for runner in local_runners:
        remote_runner = rapi.find_by_name(runner["name"])
        if not remote_runner:
            logger.warn(f"{runner['name']} is registered locally but "
                        "not remotely, registering now")
            rapi.register(runner)


@click.command()
@click.option('--conf-file', required=True)
@click.option('--access-token', required=True)
@click.option('--registration-token', required=True)
@click.option('--mars-host', required=True)
def main(conf_file, access_token, registration_token, mars_host):  # pragma: nocover
    gl = gitlab.Gitlab(url='https://gitlab.freedesktop.org',
                       private_token=access_token)
    local_config = GitlabConfig(conf_file)
    runner_api = GitlabRunnerAPI(gl, registration_token)

    initial_sync(local_config, runner_api)

    try:
        poll_mars_forever(mars_host, local_config, runner_api)
    except KeyboardInterrupt:
        logger.info("interuppted, shutting down...")


if __name__ == '__main__':  # pragma: nocover
    main(auto_envvar_prefix='GITLAB')
