from unittest.mock import MagicMock
import pytest

from pdu import PDUState, PDUPort, PDU


def test_PDUState_UNKNOW_is_invalid_action():
    assert PDUState.UNKNOWN not in PDUState.valid_actions()
    assert PDUState.UNKNOWN.is_valid_action is False


def test_PDUState_valid_actions_contain_basics():
    for action in ["ON", "OFF", "REBOOT"]:
        assert action in [s.name for s in PDUState.valid_actions()]
        assert getattr(PDUState, action).is_valid_action is True


def test_PDUPort_get_set():
    pdu = MagicMock(get_port_state=MagicMock(return_value=PDUState.OFF))
    port = PDUPort(pdu, 42, label="My Port")
    assert port.label == "My Port"

    pdu.set_port_state.assert_not_called()
    pdu.get_port_state.assert_not_called()

    port.set(PDUState.ON)
    pdu.set_port_state.assert_called_with(42, PDUState.ON)

    assert port.state == PDUState.OFF
    pdu.get_port_state.assert_called_with(42)


def test_PDU_defaults():
    pdu = PDU("MyPDU")

    assert pdu.name == "MyPDU"
    assert pdu.ports == []
    assert pdu.set_port_state(42, PDUState.ON) is False
    assert pdu.get_port_state(42) == PDUState.UNKNOWN


def test_PDU_supported_pdus():
    pdus = PDU.supported_pdus()
    assert "dummy" in pdus
