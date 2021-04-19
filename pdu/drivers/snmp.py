from pdu import PDU, PDUPort, PDUState
from easysnmp import snmp_get, snmp_set, snmp_walk


def _is_int(s):
    try:
        s = int(s)
        return True
    except ValueError:
        return False


class BaseSnmpPDU(PDU):
    def __init__(self, name, hostname, oid_outlets_label_base,
                 community="private"):
        self.hostname = hostname
        self.oid_outlets_label_base = oid_outlets_label_base
        self.community = community

        super().__init__(name)

    @property
    def ports(self):
        ports = []

        try:
            names = [x.value for x in snmp_walk(self.oid_outlets_label_base,
                                                hostname=self.hostname,
                                                community=self.community,
                                                version=1)]
        except SystemError as e:
            raise ValueError(f"The snmp_walk() call failed with the following error: {e}")

        for i, name in enumerate(names):
            ports.append(PDUPort(self, i+1, name))

        return ports

    def _port_spec_to_int(self, port_spec):
        if _is_int(port_spec):
            return port_spec
        else:
            for port in self.ports:
                if port.label == port_spec:
                    return port.port_id
            raise ValueError(
                f"{port_spec} can not be interpreted as a valid port")

    def port_oid(self, port_id):
        raise ValueError("This needs to be implemented in a child class")

    @property
    def action_to_snmp_value(self):
        return {
            "ON": 1,
            "OFF": 2,
            "REBOOT": 3
        }

    def state_to_raw_value(self, state):
        value = self.action_to_snmp_value.get(state.name, None)
        if value is None:
            raise ValueError(f"The state '{state.name}' does not have an SNMP mapping")
        return value

    def raw_value_to_state(self, value):
        val_to_state = dict([(val, key) for key, val in self.action_to_snmp_value.items()])
        return getattr(PDUState, val_to_state.get(value))

    def set_port_state(self, port_spec, state):
        SNMP_INTEGER_TYPE = 'i'

        port_id = self._port_spec_to_int(port_spec)
        try:
            return snmp_set(self.port_oid(port_id),
                            self.state_to_raw_value(state),
                            SNMP_INTEGER_TYPE,
                            hostname=self.hostname,
                            version=1,
                            community=self.community)
        except SystemError as e:
            raise ValueError(f"The snmp_set() call failed with the following error: {e}")

    def get_port_state(self, port_spec):
        port_id = self._port_spec_to_int(port_spec)
        try:
            vs = snmp_get(self.port_oid(port_id),
                          hostname=self.hostname,
                          version=1,
                          community=self.community)
        except SystemError as e:
            raise ValueError(f"The snmp_get() call failed with the following error: {e}")
        return self.raw_value_to_state(int(vs.value))

    def __eq__(self, other):
        for attr in ["name", "hostname", "oid_outlets_label_base", "community"]:
            if getattr(self, attr, None) != getattr(other, attr, None):
                return False
        return True


class SnmpPDU(BaseSnmpPDU):
    def __init__(self, name, config):
        hostname = config.get('hostname')
        if hostname is None:
            raise ValueError("Config: Missing the 'hostname' parameter")

        oid_outlets_label_base = config.get('oid_outlets_label_base')
        if oid_outlets_label_base is None:
            raise ValueError("Config: Missing the 'oid_outlets_label_base' parameter")

        self.oid_outlets_base = config.get('oid_outlets_base')
        if self.oid_outlets_base is None:
            raise ValueError("Config: Missing the 'oid_outlets_base' parameter")

        community = config.get('community', 'private')

        self.action_mapping = config.get('action_to_snmp_value', None)
        if self.action_mapping is not None:
            for action in ["ON", "OFF", "REBOOT"]:
                if action not in self.action_mapping:
                    raise ValueError(f"The action '{action}' is missing from the action mapping")
                value = self.action_mapping[action]
                try:
                    value = int(value)
                except Exception as e:
                    print(e)
                    raise ValueError(f"The value for action '{action}' should be an integer")

        super().__init__(name, hostname, oid_outlets_label_base, community)

    def port_oid(self, port_id):
        return f"{self.oid_outlets_base}.{port_id}"

    @property
    def action_to_snmp_value(self):
        if self.action_mapping is not None:
            return self.action_mapping
        else:
            return super().action_to_snmp_value