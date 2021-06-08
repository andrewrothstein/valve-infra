from threading import Thread, Event
from pdu import PDU
from executor import Executor

import traceback
import requests
import time


class Machine:
    def __init__(self, mars_base_url, machine_id, fields=None, gitlab_runner_api=None):
        self.mars_base_url = mars_base_url
        self._machine_id = machine_id
        self.gitlab_runner_api = gitlab_runner_api

        self.pdu_port = self._create_pdu_port(fields)

        # Fields from MaRS
        self._fields = fields or {}

        # Executor associated (temporary)
        self.executor = Executor(self)

        # Make sure the updates are reflected in the runner's state
        self.update_runner_state()

    def remove(self):
        if self.gitlab_runner_api is not None:
            self.gitlab_runner_api.remove(self.full_name)

        self.executor.stop_event.set()
        self.executor.join()

    @property
    def url(self):
        return f"{self.mars_base_url}/api/v1/machine/{self.id}/"

    @property
    def id(self):
        return self._machine_id

    @property
    def full_name(self):
        return self._fields.get('full_name')

    @property
    def mac_address(self):
        return self._machine_id

    @property
    def ready_for_service(self):
        return self._fields.get('ready_for_service', False)

    @ready_for_service.setter
    def ready_for_service(self, val):
        r = requests.patch(self.url, json={
            "ready_for_service": val
        })
        r.raise_for_status()

        self._fields['ready_for_service'] = val

        # Make sure the updates are reflected in the runner's state
        self.update_runner_state

    @property
    def is_retired(self):
        return self._fields.get('is_retired', False)

    @property
    def tags(self):
        return set(self._fields.get('tags', []))

    @property
    def local_tty_device(self):
        return self._fields.get("local_tty_device")

    def _create_pdu_port(self, fields):
        mars_pdu_url = fields.get('pdu')
        pdu_port = fields.get('pdu_port_id')
        if mars_pdu_url is None or pdu_port is None:
            return None

        r = requests.get(mars_pdu_url)
        r.raise_for_status()

        p = r.json()
        if pdu := PDU.create(p.get('pdu_model'), p.get('name'), p.get('config', {})):
            for port in pdu.ports:
                if str(port.port_id) == str(pdu_port):
                    return port
        raise ValueError('Could not find a matching port for %s on %s' %
                         (pdu_port, pdu))

    def update(self, fields=None):
        if not fields:
            r = requests.get(self.url)
            r.raise_for_status()

            fields = r.json()

        # Check if the PDU port changed
        if (fields.get('pdu') != self._fields.get('pdu') or
           fields.get('pdu_port_id') != self._fields.get('pdu_port_id')):
            self.pdu_port = self._create_pdu_port(fields)

        if self.pdu_port is not None:
            self.pdu_port.min_off_time = fields.get('pdu_off_delay', 5)

        self._fields = fields

        # Make sure the updates are reflected in the runner's state
        self.update_runner_state()

    def update_runner_state(self):
        if self.gitlab_runner_api is None:
            return

        if self.ready_for_service and not self.is_retired:
            self.gitlab_runner_api.expose(self.full_name, self.tags)
        else:
            self.gitlab_runner_api.remove(self.full_name)


class MarsClient(Thread):
    def __init__(self, base_url, gitlab_runner_api=None):
        super().__init__()

        self.mars_base_url = base_url
        self.gitlab_runner_api = gitlab_runner_api

        self.stop_event = Event()
        self._machines = {}

    @property
    def known_machines(self):
        return list(self._machines.values())

    def get_machine_by_id(self, machine_id, raise_if_missing=False):
        machine = self._machines.get(machine_id)
        if machine is None and raise_if_missing:
            raise ValueError(f"Unknown machine ID '{machine_id}'")
        return machine

    def _machine_update_or_create(self, machine_id, fields):
        machine = self._machines.get(machine_id)
        if machine is None:
            machine = Machine(self.mars_base_url, machine_id, fields, self.gitlab_runner_api)
        else:
            machine.update(fields)

        return machine

    def sync_machines(self):
        r = requests.get(f"{self.mars_base_url}/api/v1/machine/")
        r.raise_for_status()

        local_only_machines = set(self.known_machines)
        for m in r.json():
            # Ignore retired machines
            if m.get('is_retired', False):
                continue

            machine = self._machine_update_or_create(m.get("mac_address"), fields=m)

            # Remove the machine from the list of local-only machines
            local_only_machines.discard(machine)

            self._machines[machine.id] = machine

        # Delete all the machines that are not found in MaRS
        for machine in local_only_machines:
            self._machines[machine.id].remove()
            del self._machines[machine.id]

        # Delete all the Gitlab Runner that are not found locally
        if self.gitlab_runner_api is not None:
            gitlab_runners = self.gitlab_runner_api.exposed_machines
            non_local_runners = set(gitlab_runners) - set([m.full_name for m in self.known_machines])

            for machine_name in non_local_runners:
                self.gitlab_runner_api.remove(machine_name)

    def stop(self, wait=True):
        self.stop_event.set()

        # Signal all the executors we want to stop
        for machine in self.known_machines:
            machine.executor.stop_event.set()

        if wait:
            self.join()

    def join(self):
        for machine in self.known_machines:
            machine.executor.join()
        super().join()

    def run(self):
        while True:
            try:
                self.sync_machines()
            except Exception:
                traceback.print_exc()
            finally:
                # Wait for 5 seconds, with the ability to exit every second
                for i in range(5):
                    time.sleep(1)
                    if self.stop_event.is_set():
                        return
