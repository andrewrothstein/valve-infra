from .snmp import BaseSnmpPDU


class PDU41004(BaseSnmpPDU):
    OID_OUTLETS = "SNMPv2-SMI::enterprises.3808.1.1.3.3.3.1.1"

    def __init__(self, name, config):
        hostname = config.get('hostname')

        if hostname is None:
            raise ValueError("Config: Missing the 'hostname' parameter")

        super().__init__(name, hostname,
                         oid_outlets_label_base=f"{self.OID_OUTLETS}.2")

    def port_oid(self, port_id):
        return f"{self.OID_OUTLETS}.4.{port_id}"
