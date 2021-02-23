from unittest.mock import patch
from app import app, SerialLoop, get_machine_or_fail
from salad import Machine

import pytest


@pytest.fixture
def client():
    with app.test_client() as client:
        Machine._machines.clear()
        yield client


@patch("salad.SerialConsoleStream.listen_to_all_serial_ports")
def test_SerialLoop(listen_port_mock, client):
    sl = SerialLoop()

    sl.start()
    sl.join()

    assert listen_port_mock.called_once_with()


def test_get_machine_or_fail__unknown_machine(client):
    with pytest.raises(ValueError) as e:
        get_machine_or_fail("toto")
    assert str(e.value) == "Unknown machine ID 'toto'"


def test_get_machine_or_fail__known_machine(client):
    m_orig = Machine("toto")
    assert get_machine_or_fail("toto") == m_orig


def test_get_machine_list(client):
    m1 = Machine.find_or_create("machine_1")
    m2 = Machine.find_or_create("machine_2")

    ret = client.get("/v1/machines")

    assert ret.status_code == 200
    assert ret.json == {
        "machines": [m1.machine_id, m2.machine_id]
    }


def test_get_session_list(client):
    url = "/v1/machines/machine_1/sessions"

    ret = client.get(url)
    assert ret.status_code == 400
    assert ret.json == {
        "error": "Unknown machine ID 'machine_1'"
    }

    Machine.find_or_create("machine_1")
    ret = client.get(url)
    assert ret.status_code == 200
    assert ret.json == {
        "sessions": ["cur", "next"]
    }


def test_get_session_sources(client):
    url_fmt = "/v1/machines/{m_id}/sessions/{s_id}/sources"

    ret = client.get(url_fmt.format(m_id="machine_1", s_id="blabla"))
    assert ret.status_code == 400
    assert ret.json == {
        "error": "Unknown machine ID 'machine_1'"
    }

    Machine.find_or_create("machine_1")
    ret = client.get(url_fmt.format(m_id="machine_1", s_id="blabla"))
    assert ret.status_code == 400
    assert ret.json == {
        "error": "The session 'blabla' is unavailable"
    }

    ret = client.get(url_fmt.format(m_id="machine_1", s_id="cur"))
    assert ret.status_code == 200
    assert ret.json == {
        "sources": ["serial"]
    }


def test_get_session_logs(client):
    url_fmt = "/v1/machines/{m_id}/sessions/{s_id}/sources/{src_id}"

    ret = client.get(url_fmt.format(m_id="machine_1", s_id="blabla", src_id="src"))
    assert ret.status_code == 400
    assert ret.json == {
        "error": "Unknown machine ID 'machine_1'"
    }

    Machine.find_or_create("machine_1")
    ret = client.get(url_fmt.format(m_id="machine_1", s_id="blabla", src_id="src"))
    assert ret.status_code == 400
    assert ret.json == {
        "error": "The session 'blabla' is unavailable"
    }

    ret = client.get(url_fmt.format(m_id="machine_1", s_id="cur", src_id="src"))
    assert ret.status_code == 400
    assert ret.json == {
        "error": "The source 'src' is unavailable"
    }

    ret = client.get(url_fmt.format(m_id="machine_1", s_id="cur", src_id="serial"))
    assert ret.status_code == 200
    assert ret.data == b""
