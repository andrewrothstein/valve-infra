from .snmp import BaseSnmpPDU


class ApcMasterswitchPDU(BaseSnmpPDU):
    OID_OUTLETS = "SNMPv2-SMI::enterprises.318.1.1.4.4.2.1"

    def __init__(self, name, config):
        hostname = config.get('hostname')

        if hostname is None:
            raise ValueError("Config: Missing the 'hostname' parameter")

        super().__init__(name, hostname,
                         oid_outlets_label_base=f"{self.OID_OUTLETS}.4")

    def port_oid(self, port_id):
        return f"{self.OID_OUTLETS}.3.{port_id}"
