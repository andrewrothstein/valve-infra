from unittest.mock import MagicMock
import pytest
import copy
import sys

from pdu import PDUState
from drivers.apc import ApcMasterswitchPDU
from drivers.cyberpower import PDU41004
from drivers.dummy import DummyPDU
from drivers.snmp import BaseSnmpPDU, SnmpPDU, snmp_get, snmp_set, snmp_walk


@pytest.fixture(autouse=True)
def reset_easysnmp_mock(monkeypatch):
    import drivers.snmp
    global snmp_get, snmp_set, snmp_walk
    m1, m2, m3 = MagicMock(), MagicMock(), MagicMock()
    # REVIEW: I wonder if there's a clever way of covering the
    # difference in import locations between here and snmp.py
    monkeypatch.setattr(drivers.snmp, "snmp_walk", m1)
    monkeypatch.setattr(drivers.snmp, "snmp_get", m2)
    monkeypatch.setattr(drivers.snmp, "snmp_set", m3)
    snmp_walk = m1
    snmp_get = m2
    snmp_set = m3


def test_driver_BaseSnmpPDU_listing_ports():
    pdu = BaseSnmpPDU("MyPDU", "127.0.0.1", "label_base")
    snmp_walk.return_value = [MagicMock(value="P1"), MagicMock(value="P2")]
    snmp_walk.assert_not_called()
    ports = pdu.ports
    snmp_walk.assert_called_with(pdu.oid_outlets_label_base,
                                 hostname=pdu.hostname, community=pdu.community,
                                 version=1)

    # Check that the labels are stored, and the port IDs are 1-indexed
    for i in range(0, 2):
        assert ports[i].port_id == i+1
        assert ports[i].label == f"P{i+1}"

    snmp_walk.side_effect = SystemError("An error")
    with pytest.raises(ValueError):
        pdu.ports


def test_driver_BaseSnmpPDU_port_label_mapping():
    pdu = BaseSnmpPDU("MyPDU", "127.0.0.1", "label_base")
    pdu.port_oid = MagicMock(return_value="oid_port_1")
    snmp_walk.return_value = [
        MagicMock(value="P1"),
        MagicMock(value="P2")
    ]
    snmp_set.return_value = True
    assert pdu.set_port_state("P1", PDUState.REBOOT) is True
    pdu.port_oid.assert_called_with(1)
    snmp_set.assert_called_with(pdu.port_oid.return_value,
                                pdu.state_to_raw_value(PDUState.REBOOT), 'i',
                                hostname=pdu.hostname, community=pdu.community,
                                version=1)
    assert pdu.set_port_state("P2", PDUState.REBOOT) is True
    pdu.port_oid.assert_called_with(2)
    snmp_set.assert_called_with(pdu.port_oid.return_value,
                                pdu.state_to_raw_value(PDUState.REBOOT), 'i',
                                hostname=pdu.hostname, community=pdu.community,
                                version=1)
    with pytest.raises(ValueError):
        pdu.set_port_state("flubberbubber", PDUState.OFF)


def test_driver_BaseSnmpPDU_get_port():
    pdu = BaseSnmpPDU("MyPDU", "127.0.0.1", "label_base")

    with pytest.raises(ValueError):
        pdu.port_oid(2)
    pdu.port_oid = MagicMock(return_value="oid_port_2")

    snmp_get.return_value = pdu.raw_value_to_state(PDUState.REBOOT)
    snmp_get.assert_not_called()
    assert pdu.get_port_state(2)
    pdu.port_oid.assert_called_with(2)
    snmp_get.assert_called_with(pdu.port_oid.return_value,
                                hostname=pdu.hostname, community=pdu.community,
                                version=1)

    snmp_get.side_effect = SystemError("An error")
    with pytest.raises(ValueError):
        pdu.get_port_state(2)


def test_driver_BaseSnmpPDU_set_port():
    pdu = BaseSnmpPDU("MyPDU", "127.0.0.1", "label_base")

    pdu.port_oid = MagicMock(return_value="oid_port_2")
    snmp_set.return_value = True
    snmp_set.assert_not_called()
    assert pdu.set_port_state(2, PDUState.REBOOT) is True
    pdu.port_oid.assert_called_with(2)
    snmp_set.assert_called_with(pdu.port_oid.return_value,
                                pdu.state_to_raw_value(PDUState.REBOOT), 'i',
                                hostname=pdu.hostname, community=pdu.community,
                                version=1)

    snmp_set.side_effect = SystemError("An error")
    with pytest.raises(ValueError):
        pdu.set_port_state(2, PDUState.REBOOT)


def test_driver_BaseSnmpPDU_action_translation():
    pdu = BaseSnmpPDU("MyPDU", "127.0.0.1", "label_base")

    # Check the state -> SNMP value translation
    for action in PDUState.valid_actions():
        assert pdu.state_to_raw_value(action) == pdu.action_to_snmp_value[action.name]

    with pytest.raises(ValueError):
        pdu.state_to_raw_value(PDUState.UNKNOWN)

    # Check the SNMP value -> state translation
    for state in PDUState.valid_actions():
        raw = pdu.state_to_raw_value(state)
        assert pdu.raw_value_to_state(raw) == state

    with pytest.raises(AttributeError):
        pdu.state_to_raw_value(42)


def test_driver_ApcMasterswitchPDU_check_OIDs():
    pdu = ApcMasterswitchPDU("MyPDU", config={"hostname": "127.0.0.1"})

    assert pdu.oid_outlets_label_base == "SNMPv2-SMI::enterprises.318.1.1.4.4.2.1.4"
    assert pdu.port_oid(10) == "SNMPv2-SMI::enterprises.318.1.1.4.4.2.1.3.10"


def test_driver_ApcMasterswitchPDU_invalid_config():
    with pytest.raises(ValueError):
        ApcMasterswitchPDU("MyPDU", config={})


def test_driver_PDU41004_check_OIDs():
    pdu = PDU41004("MyPDU", config={"hostname": "127.0.0.1"})

    assert pdu.oid_outlets_label_base == "SNMPv2-SMI::enterprises.3808.1.1.3.3.3.1.1.2"
    assert pdu.port_oid(10) == "SNMPv2-SMI::enterprises.3808.1.1.3.3.3.1.1.4.10"


def test_driver_PDU41004_invalid_config():
    with pytest.raises(ValueError):
        PDU41004("MyPDU", config={})


def test_driver_DummyPDU():
    ports = ['P1', 'P2', 'P3']
    pdu = DummyPDU("MyPDU", {"ports": ports})

    assert [p.label for p in pdu.ports] == ports
    assert pdu.get_port_state(0) == PDUState.ON
    pdu.set_port_state(0, PDUState.OFF)
    assert pdu.get_port_state(0) == PDUState.OFF


def test_driver_SnmpPDU_check_OIDs_and_default_actions():
    pdu = SnmpPDU("MyPDU", config={
        "hostname": "127.0.0.1",
        "oid_outlets_label_base": "label_base",
        "oid_outlets_base": "outlet_base",
    })

    assert pdu.community == "private"
    assert pdu.oid_outlets_label_base == "label_base"
    assert pdu.port_oid(10) == "outlet_base.10"
    assert pdu.action_to_snmp_value == super(SnmpPDU, pdu).action_to_snmp_value


def test_driver_SnmpPDU_actions():
    pdu = SnmpPDU("MyPDU", config={
        "hostname": "127.0.0.1",
        "oid_outlets_label_base": "label_base",
        "oid_outlets_base": "outlet_base",
        "community": "public",
        "action_to_snmp_value": {
            "ON": 42,
            "OFF": 43,
            "REBOOT": 44
        }
    })

    assert pdu.community == "public"
    assert pdu.action_to_snmp_value == {
        "ON": 42,
        "OFF": 43,
        "REBOOT": 44
    }


def test_driver_SnmpPDU_invalid_actions():
    with pytest.raises(ValueError):
        SnmpPDU("MyPDU", config={
            "hostname": "127.0.0.1",
            "oid_outlets_label_base": "label_base",
            "oid_outlets_base": "outlet_base",
            "community": "public",
            "action_to_snmp_value": {
                "ON": "TOTO",
                "OFF": 43,
                "REBOOT": 44
            }
        })


def test_driver_SnmpPDU_missing_actions():
    with pytest.raises(ValueError):
        SnmpPDU("MyPDU", config={
            "hostname": "127.0.0.1",
            "oid_outlets_label_base": "label_base",
            "oid_outlets_base": "outlet_base",
            "community": "public",
            "action_to_snmp_value": {
                "OFF": 43,
                "REBOOT": 44
            }
        })


def test_driver_SnmpPDU_missing_parameters():
    valid_config = {
        "hostname": "127.0.0.1",
        "oid_outlets_label_base": "label_base",
        "oid_outlets_base": "outlet_base",
        "community": "public",
        "action_to_snmp_value": {
            "ON": 42,
            "OFF": 43,
            "REBOOT": 44
        }
    }

    SnmpPDU("MyPDU", config=valid_config)
    for required_param in ["hostname", "oid_outlets_label_base", "oid_outlets_base"]:
        new_config = copy.deepcopy(valid_config)
        del new_config[required_param]
        with pytest.raises(ValueError):
            SnmpPDU("MyPDU", config=new_config)
