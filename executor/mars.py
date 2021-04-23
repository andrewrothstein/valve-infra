from threading import Thread, Event
from pdu import PDU
from executor import Executor

import traceback
import requests
import time
import os


class Machine:
    def __init__(self, mars_base_url, machine_id, fields=None):
        self.mars_base_url = mars_base_url
        self._machine_id = machine_id

        self.pdu_port = self._create_pdu_port(fields)

        # Fields from MaRS
        if fields is None:
            fields = {}
        self._fields = fields

        # Executor associated (temporary)
        self.executor = Executor(self)

    def destroy(self):
        self.executor.stop_event.set()
        self.executor.join()

    @property
    def url(self):
        return f"{self.mars_base_url}/api/v1/machine/{self.id}/"

    @property
    def id(self):
        return self._machine_id

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
        pdu = PDU.create(p.get('pdu_model'), p.get('name'), p.get('config', {}))
        if pdu is not None:
            for port in pdu.ports:
                if str(port.port_id) == str(pdu_port):
                    return port

        return pdu_port

    def update(self, fields=None):
        if fields is not None:
            fields = fields
        else:
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


class MarsClient(Thread):
    def __init__(self):
        super().__init__()

        self.mars_base_url = os.getenv('MARS_URL', "http://127.0.0.1")
        self.stop_event = Event()
        self._machines = {}

    @property
    def known_machines(self):
        return list(self._machines.values())

    def get_machine_by_id(self, machine_id):
        return self._machines.get(machine_id)

    def _machine_update_or_create(self, machine_id, fields):
        machine = self._machines.get(machine_id)
        if machine is None:
            machine = Machine(self.mars_base_url, machine_id, fields)
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
            del self._machines[machine.id]

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

                # Wait for 5 seconds, with the ability to exit every second
                for i in range(5):
                    time.sleep(1)
                    if self.stop_event.is_set():
                        return
            except Exception:
                traceback.print_exc()
