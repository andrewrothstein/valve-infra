from datetime import datetime
from enum import IntEnum

import time


class PDUState(IntEnum):
    UNKNOWN = 0
    OFF = 1
    ON = 2
    REBOOT = 3

    @classmethod
    def valid_actions(cls):
        return [s for s in PDUState if s.value > 0]

    @property
    def is_valid_action(self):
        return self in self.valid_actions()


class PDUPort:
    def __init__(self, pdu, port_id, label=None, delay=5):
        self.pdu = pdu
        self.port_id = port_id
        self.label = label
        self.delay = delay

        self.last_state_change = datetime.now()

    def set(self, state):
        # Check the current state before writing it
        if self.state == state:
            return

        # Enforce a minimum amount of time between state changes
        time_since_last_change = (datetime.now() - self.last_state_change).total_seconds()
        if time_since_last_change < self.delay:
            time.sleep(self.delay - time_since_last_change)

        self.pdu.set_port_state(self.port_id, state)

        self.last_state_change = datetime.now()

    @property
    def state(self):
        return self.pdu.get_port_state(self.port_id)


class PDU:
    def __init__(self, name):
        self.name = name

    @property
    def ports(self):
        # NOTICE: Left for drivers to implement
        return []

    def set_port_state(self, port_id, state):
        # NOTICE: Left for drivers to implement
        return False

    def get_port_state(self, port_id):
        # NOTICE: Left for drivers to implement
        return PDUState.UNKNOWN

    @classmethod
    def supported_pdus(cls):
        from .drivers.apc import ApcMasterswitchPDU
        from .drivers.cyberpower import PDU41004
        from .drivers.dummy import DummyPDU
        from .drivers.snmp import SnmpPDU

        return {
            "apc_masterswitch": ApcMasterswitchPDU,
            "cyberpower_pdu41004": PDU41004,
            "dummy": DummyPDU,
            "snmp": SnmpPDU,
        }

    @classmethod
    def create(cls, model_name, pdu_name, config):
        Driver = cls.supported_pdus().get(model_name)

        if Driver is None:
            raise ValueError(f"Unknown model name '{model_name}'")

        return Driver(pdu_name, config)
