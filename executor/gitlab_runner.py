from pprint import pformat
from gitlab import Gitlab
from logger import logger

import toml


class GitlabRunnerConfig:
    def __init__(self, remote_api, runner_registration_token, farm_name=None):
        self.gl = remote_api
        self.registration_token = runner_registration_token
        self.farm_name = farm_name or 'unknown'

    def runner_is_managed_by_our_farm(self, runner):
        return runner.description.startswith(self.farm_name)

    def register(self, name, tags):
        """Register a new runner with the given name and tag list"""
        registration_config = {
            'token': self.registration_token,
            'description': name,
            'tag_list': list(tags),
            'run_untagged': 'false',  # Whether the runner should handle untagged jobs
            # Don't want randoms using our CI resources outside of our mirror project
            'locked': 'true',  # Whether the runner should be locked for current project
        }
        return self.gl.runners.create(registration_config)

    def registered_runners(self):
        # Not cached on purpose, it's less efficient and arguable we
        # don't need to re-query, but it removes some corner cases of
        # people faffinf manually on the server side
        return filter(self.runner_is_managed_by_our_farm,
                      self.gl.runners.list())

    def unregister(self, runner):
        """Remove the given runner from the server."""
        self.gl.runners.delete(runner.id)

    def unregister_machine(self, machine_name):
        runner = self.find_by_name(machine_name)
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

    def set_tags(self, machine_name, machine_tags):  # pragma: nocover
        runner = self.find_by_name(machine_name)
        if runner is not None:
            runner.tag_list = list(machine_tags)
            runner.save()
        else:
            logger.error("This should not happen!")
            import traceback
            traceback.print_stack()

    @property
    def runner_names(self):
        return [r.description for r in self.registered_runners()]


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
            logger.warning("GitlabConfig: Encountered an exception reloading "
                           "configuration: %s\nLoading the default configuration", err)
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

    def remove_machine(self, machine_name):
        if self.find_by_name(machine_name) is None:
            return  # pragma: nocover

        self.runners()[:] = [r for r in self.runners()
                             if r['name'] != machine_name]
        self._save()

    def remove_runner(self, runner):
        self.remove_machine(runner['name'])

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
        logger.info(f"GitlabConfig: adding a new runner:\n{pformat(config)}")
        self.runners().append(config)
        self._save()

    @property
    def runner_names(self):
        return [r["name"] for r in self.runners()]


class GitlabRunnerAPI:
    def __init__(self, instance_url, config_file, access_token, registration_token, farm_name=None):
        self.instance_url = instance_url

        self.gl = Gitlab(url=instance_url, private_token=access_token)
        self.remote_config = GitlabRunnerConfig(self.gl, registration_token, farm_name)
        self.local_config = GitlabConfig(config_file)

        self.drop_unsynced_runners()

    @property
    def exposed_machines(self):
        return set(self.local_config.runner_names) | set(self.remote_config.runner_names)

    def remove(self, machine_name):
        self.remote_config.unregister_machine(machine_name)
        self.local_config.remove_machine(machine_name)

    def expose(self, name, tags):
        def register(machine_name, machine_tags):
            resp = self.remote_config.register(machine_name, machine_tags)
            self.local_config.add_runner(machine_name, resp.token)

        local_runner = self.local_config.find_by_name(name)
        remote_runner = self.remote_config.find_by_name(name)

        if not local_runner and not remote_runner:
            logger.info("GitlabRunnerAPI: There is neither a local nor remote "
                        f"runner for {name}. Registering...")
            register(name, tags)
        elif not local_runner and remote_runner:
            logger.info(f"GitlabRunnerAPI: There is remote runner named {name}, but "
                         "not local. Deleting remote runner and reregistering...")

            running_jobs = self.remote_config.active_jobs(remote_runner.id)
            if running_jobs:
                logger.error("GitlabRunnerAPI: The remote runner is actively "
                             "running jobs, or waiting for a timeout to expire. "
                             "For now this means you should manually sort "
                             "that out and come back.")
                return False
            self.remote_config.unregister(remote_runner)
            register(name, tags)
        elif local_runner and not remote_runner:
            logger.info(f"GitlabRunnerAPI: {name} exists locally but not on "
                        "the remote. Removing locally and re-registering...")
            self.local_config.remove_runner(local_runner)
            register(name, tags)
        elif local_runner and remote_runner:
            pass

        # Both sides are in agreement now, make sure the tags are in agreement too!
        self.remote_config.set_tags(name, tags)

        logger.info(f'The runner {name} has been synchronized')
        return True

    def drop_unsynced_runners(self):
        local_machines = set(self.local_config.runner_names)
        remote_machines = set(self.remote_config.runner_names)
        exposed_machines = local_machines | remote_machines

        # Remove all runners found only in either the local or the remote config
        for machine_name in exposed_machines - (local_machines & remote_machines):
            self.remove(machine_name)
