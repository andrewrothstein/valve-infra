#!/usr/bin/env python3
# -*- mode: python -*-

# See also: https://docs.gitlab.com/ee/api/runners.html

from pprint import pformat
import gitlab
from datetime import datetime
import os
import enum
import requests
import backoff
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


def parse_iso8601_date(d):
    # For some reason the datetime parser doesn't like the lone Z, I
    # thought it was spec'd. It does happily accept +00:00 in lieu of
    # Z.
    return datetime.fromisoformat(d.removesuffix("Z"))


class GitlabRunnerAPI:
    def __init__(self, remote_api, runner_registration_token, farm_name=None):
        self.gl = remote_api
        self.registration_token = runner_registration_token
        self.farm_name = farm_name or os.environ.get('FARM_NAME', 'unknown')

    def runner_is_managed_by_our_farm(self, runner):
        return runner.description.startswith(self.farm_name)

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

    def registered_runners(self):
        # Not cached on purpose, it's less efficient and arguable we
        # don't need to requery, but it removes some corner cases of
        # people faffinf manually on the server side
        return filter(self.runner_is_managed_by_our_farm,
                      self.gl.runners.list())

    def unregister(self, runner):
        """Remove the given runner from the server."""
        self.gl.runners.delete(runner.id)

    def unregister_machine(self, machine):
        runner = self.find_by_name(machine["full_name"])
        if runner:
            self.unregister(runner)

    def find_by_name(self, name):
        """Find a runner with a description matching _name_. Return
        the matching runner structure"""
        for runner in self.registered_runners():
            if runner.description == name:
                return runner

    def active_jobs(self, runner_id):  # pragma: nocover
        runner_details = self.gl.runners.get(runner_id)
        return runner_details.jobs.list(status='running')

    def set_tags(self, machine):  # pragma: nocover
        runner = self.find_by_name(machine["full_name"])
        if runner is not None:
            runner.tag_list = machine["tags"]
            runner.save()
        else:
            logger.error("This should not happen!")
            import traceback
            traceback.print_stack()


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
        except (FileNotFoundError, toml.TomlDecodeError) as err:
            logger.warning("Encountered an exception reloading configuration: %s\n"
                           "Loading the default configuration", err)
            self.config = GitlabConfig.DEFAULT_CONFIG

    def runners(self):
        self._reload_config()
        if "runners" not in self.config:
            self.config["runners"] = []
        return self.config["runners"]

    def find_by_name(self, name):
        for runner in self.runners():
            if runner["name"] == name:
                return runner

    def remove_runner(self, runner):
        self.runners()[:] = [r for r in self.runners()
                             if r['name'] != runner['name']]
        self._save()

    def clear(self):  # pragma: nocover
        self.config = GitlabConfig.DEFAULT_CONFIG
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
                'registry.freedesktop.org/mupuf/valve-infra/gitlab-trigger',
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
        self.runners().append(config)
        self._save()


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
                    " Deleting remote runner and reregistering...")
        running_jobs = runner_api.active_jobs(remote_runner.id)
        if running_jobs:
            logger.error("The remote runner is actively running jobs, or "
                         "waiting for a timeout to expire. "
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
    runner_api.set_tags(machine)

    logger.info(f'The runner {name} has been synchronized')
    return True


class Event(enum.Enum):
    METADATA_CHANGE = 1
    READY_FOR_SERVICE = 2
    OUT_OF_SERVICE = 3
    OTHER = 4


def parse_event_diff(diff):
    values_changed = diff.get('values_changed', {})
    modified_fields = values_changed
    modified_fields.update(diff.get('iterable_item_added', {}))
    modified_fields.update(diff.get('iterable_item_removed', {}))

    if 'root.base_name' in values_changed or any([key.startswith('root.tags') for key in modified_fields.keys()]):
        return Event.METADATA_CHANGE
    elif 'root.ready_for_service' in values_changed:
        if values_changed['root.ready_for_service']['new_value']:
            return Event.READY_FOR_SERVICE
        return Event.OUT_OF_SERVICE
    else:
        return Event.OTHER


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
    for event in events:
        if event['category'] != 'machine-updated':
            logger.debug(f'ignoring {event}, only considering udpate events')
            last_checked = parse_iso8601_date(event['date'])
            continue

        diff = json.loads(event['diff'])
        r = requests.get(event['machine'])
        r.raise_for_status()
        machine = r.json()
        parsed_event = parse_event_diff(diff)
        if parsed_event == Event.OTHER:
            logger.info("ignoring event, does not have a relevant diff")
            last_checked = parse_iso8601_date(event['date'])
            continue
        elif parsed_event in [Event.READY_FOR_SERVICE, Event.METADATA_CHANGE]:
            logger.debug(f"processing {event}")
            if not sync_mars_machine_with_coordinator(machine,
                                                      gitlab_config,
                                                      runner_api):
                logger.error("An error occurred while synchronizing {machine['full_name']}")
                break
        elif parsed_event == Event.OUT_OF_SERVICE:
            logger.info(f"{pformat(machine)} out of service, disabling runner")
            runner_api.unregister_machine(machine)
        else:
            assert False  # pragma: nocover
        last_checked = parse_iso8601_date(event['date'])
    return last_checked


@backoff.on_exception(backoff.constant,
                      requests.exceptions.RequestException,
                      interval=5)
def poll_mars_forever(mars_host, gitlab_config, runner_api):  # pragma: nocover
    logger.info("Polling for changes in MaRS...")

    r = requests.get(
        f'{mars_host}/api/v1/machine/?ready_for_service=true')
    r.raise_for_status()
    machines = r.json()
    if not machines:
        logger.info("There are no registered machines, clear any old runner configuration")
        gitlab_config.clear()
    else:
        logger.info(f"{len(machines)} machines ready for service, syncing...")
        for machine in machines:
            logger.info(f"syncing {machine['full_name']}")
            if not sync_mars_machine_with_coordinator(machine,
                                                      gitlab_config,
                                                      runner_api):
                logger.error("An error occurred while synchronizing "
                             f"{pformat(machine)}. "
                             "Will attempt to refetch machines and "
                             "try again")
                raise requests.exceptions.RequestException()
    logger.info("MaRS sync complete, switching to event monitoring mode...")

    last_checked = datetime.now()
    while True:
        r = requests.get(
            f'{mars_host}/api/v1/events/?since={last_checked.isoformat()}')
        r.raise_for_status()
        events = r.json()
        last_event_time = process_mars_events(events,
                                              gitlab_config,
                                              runner_api)
        last_checked = last_event_time or last_checked
        time.sleep(3)


@click.group()
@click.option('--access-token', required=True, envvar='GITLAB_ACCESS_TOKEN')
@click.pass_context
def cli(ctx, access_token):  # pragma: nocover
    # ensure that ctx.obj exists and is a dict (in case `cli()` is called
    # by means other than the `if` block below)
    ctx.ensure_object(dict)
    ctx.obj['GITLAB_API'] = gitlab.Gitlab(url='https://gitlab.freedesktop.org',
                                          private_token=access_token)


@cli.command()
@click.option('--conf-file', required=True, envvar='GITLAB_CONF_FILE')
@click.option('--registration-token', required=True, envvar='GITLAB_REGISTRATION_TOKEN')
@click.option('--mars-host', required=True, envvar='MARS_HOST')
@click.pass_context
def service(ctx, conf_file, registration_token, mars_host):  # pragma: nocover
    local_config = GitlabConfig(conf_file)
    runner_api = GitlabRunnerAPI(ctx.obj['GITLAB_API'], registration_token)

    try:
        poll_mars_forever(mars_host, local_config, runner_api)
    except KeyboardInterrupt:
        logger.info("interuppted, shutting down...")


@cli.command()
@click.option('--farm-name', required=True, envvar='FARM_NAME')
@click.pass_context
def remove_all_gitlab_runners(ctx, farm_name):  # pragma: nocover
    gl = ctx.obj['GITLAB_API']
    runners = list(filter(lambda r: r.description.startswith(f'{farm_name}-'),
                          gl.runners.list(all=True)))
    if not click.confirm(f'About to remove {len(runners)} runners for the '
                         f' {farm_name} farm, are you sure?',
                         default=False):
        return

    for runner in runners:
        if runner.description.startswith(f'{farm_name}-'):
            logger.info("Attempting to remove %s...", runner.description)
            try:
                runner.delete()
                logger.info('Removed')
            except gitlab.exceptions.GitlabDeleteError as err:
                if 'Runner associated with more than one project' in err.error_message:
                    logger.error('Not removing %s since it is associated to more than one project',
                                 runner.description)
                else:
                    raise


if __name__ == '__main__':  # pragma: nocover
    cli()
