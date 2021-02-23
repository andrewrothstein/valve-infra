from datetime import datetime
from unittest.mock import MagicMock, patch
from salad import Line, Session, Machine, ConsoleStream, SerialConsoleStream

import threading
import pytest


def is_roughly_now(dt):
    now = datetime.now()
    return datetime.timestamp(dt) == pytest.approx(datetime.timestamp(now))


def test_Line_contains_current_time():
    line_str = "My line"
    line = Line(line_str)

    assert is_roughly_now(line.time)
    assert line.data == line_str
    assert line.is_input


def test_Line_direction():
    line = Line(b"line")
    assert line.is_input

    line = Line(b"line", is_input=True)
    assert line.is_input

    line = Line(b"line", is_input=False)
    assert not line.is_input


def test_Session_life_cycle():
    session = Session()

    # Default state
    assert session.started_at is None
    assert session.ended_at is None
    assert not session.has_started
    assert not session.has_ended
    assert session.raw_logs == b""

    line1 = b"My line 1\n"
    line2 = b"My line 2\n"
    session.append_input_line(line1)
    session.append_output_line(line2)

    assert is_roughly_now(session.started_at)
    assert session.ended_at is None
    assert session.has_started
    assert not session.has_ended
    assert session.raw_logs == line1 + line2

    session.end()
    assert is_roughly_now(session.started_at)
    assert is_roughly_now(session.ended_at)
    assert session.has_started
    assert session.has_ended
    assert session.raw_logs == line1 + line2


def test_Machine_creation_and_retrieval():
    # Reset the state
    Machine._machines.clear()

    m1_id = "Machine 1"
    m1 = Machine(m1_id)

    # Check that the machine is now in the list of known machines and can be
    # retrieved by name
    assert Machine.known_machines() == [m1_id]
    assert Machine.get_by_id(m1_id) == m1

    # Create a new machine, check that the list of known machines got
    # updated, and that the machine can be retrieved by ID
    m2_id = "Machine 2"
    m2 = Machine.find_or_create(m2_id)

    assert set(Machine.known_machines()) == set([m1_id, m2_id])
    assert Machine.get_by_id(m1_id) == m1
    assert Machine.get_by_id(m2_id) == m2


def test_Machine_session_management():
    m1 = Machine("Machine 1")

    # Check the sessions are well initialized
    assert m1.session_prev is None
    assert m1.session_cur is not None
    assert m1.session_next is not None
    assert set(m1.sessions.keys()) == set(["cur", "next"])

    # Check that next -> cur and cur -> prev, when starting a new session
    s_cur = m1.session_cur
    s_next = m1.session_next
    assert m1.start_new_session() == s_next
    assert m1.session_cur == s_next
    assert m1.session_prev == s_cur
    assert m1.session_next is not None
    assert set(m1.sessions.keys()) == set(["prev", "cur", "next"])


def test_ConsoleStream_process_input_line_session_management_without_machine():
    cs = ConsoleStream("my_stream")

    assert cs.cur_session is not None
    assert cs.cur_session.raw_logs == b""

    # Add a line, and check that it gets appended to the session
    line0 = b"line 0\n"
    cs.process_input_line(line0)
    assert cs.cur_session.raw_logs == line0

    # Create a new session, and check that the old data is gone
    line_new_session = b"\r[    0.000000] Linux version 5.10.15-MUPUF+ ..."
    cs.process_input_line(line_new_session)
    assert cs.cur_session.raw_logs == line_new_session


def test_ConsoleStream_process_input_line_session_management(capsys):
    cs = ConsoleStream("my_stream")

    assert cs.stream_name == "my_stream"
    assert cs.associated_machine is None

    # Check the format of the log messages when the machine is unknown
    line1 = b"line 1\n"
    cs.process_input_line(line1)
    captured = capsys.readouterr()
    assert captured.out == f"{cs.stream_name}/UNKNOWN --> {str(line1)}\n"
    assert captured.err == ""

    # Check the back association of the session to the machine
    line_machine_id1 = b'Fluff SALAD.machine_id=123456789 Fluff\n'
    cs.process_input_line(line_machine_id1)
    captured = capsys.readouterr()
    assert cs.associated_machine is not None
    assert cs.associated_machine.machine_id == "123456789"
    assert cs.associated_machine.session_cur.raw_logs == line1 + line_machine_id1
    assert captured.out == f"{cs.stream_name}/123456789 --> {str(line_machine_id1)}\n"
    assert captured.err == ""

    # Start a new Session, and check that the old data is gone
    line_new_session = b"\r[    0.000000] Linux version 5.10.15-MUPUF+ ..."
    cs.process_input_line(line_new_session)
    assert cs.associated_machine.machine_id == "123456789"
    assert cs.associated_machine.session_cur.raw_logs == line_new_session

    # Try changing the machine id, and check the back association
    prev_machine = cs.associated_machine
    line_machine_id2 = b'Fluff SALAD.machine_id=987654321 Fluff\n'
    cs.process_input_line(line_machine_id2)
    assert cs.associated_machine != prev_machine
    assert prev_machine.session_cur.has_ended
    assert cs.associated_machine.machine_id == "987654321"
    assert not cs.associated_machine.session_cur.has_ended
    assert cs.associated_machine.session_cur.raw_logs == line_new_session + line_machine_id2

    line_end_session = b"SALAD.close_current_session\n"
    cs.process_input_line(line_end_session)
    assert cs.associated_machine.session_cur.raw_logs == line_new_session + line_machine_id2 + line_end_session
    assert cs.associated_machine.session_cur.has_ended

    # TODO: Check what happens when multiple consoles are mapped to the same machine


def test_ConsoleStream_process_input_line_ping(capsys):
    pong_line = b'SALAD.pong\n'

    class ConsoleStreamTest(ConsoleStream):
        def _send(self, data):
            assert data == pong_line
            print("_send called")

    cs = ConsoleStreamTest("my_stream")

    ping_line = b'SALAD.ping\n'
    cs.process_input_line(ping_line)
    captured = capsys.readouterr()
    assert cs.cur_session.raw_logs == ping_line + pong_line
    assert "_send called" in captured.out


def test_ConsoleStream_send(capsys):
    cs = ConsoleStream("my_stream")

    cs.send(b"line 1")
    captured = capsys.readouterr()
    assert captured.out == "my_stream/UNKNOWN <-- b'line 1'\n"
    assert captured.err == "WARNING: The console 'my_stream' does not implement the _send() method\n"


def test_ConsoleStream_thread():
    class SerialConsoleStreamTest(ConsoleStream):
        def process_input(self):
            pass

    t = SerialConsoleStreamTest("test")
    t.start()
    t.join()


@patch('serial.tools.list_ports.comports',
       side_effect=[[MagicMock(device='com1')],
                    [MagicMock(device='com1'), MagicMock(device='com2')],
                    [MagicMock(device='com2'), MagicMock(device='com3')],
                    [MagicMock(device='com1')],
                    [MagicMock(device='com1'), MagicMock(device='com_stop')]])
@patch('serial.Serial')
@patch('time.sleep')
def test_SerialConsoleStream_listen_to_all_serial_ports(comports_mock, serial_mock, sleep_mock):
    class SerialConsoleStreamTest(SerialConsoleStream):
        stop_event = threading.Event()
        added_devices = []

        def __init__(self, dev):
            super().__init__(dev)
            self.added_devices.append(dev)

        def process_input(self):
            if self.stream_name == "com_stop":
                self.stop_event.set()

    SerialConsoleStreamTest.listen_to_all_serial_ports(SerialConsoleStreamTest.stop_event)

    # Check the number of iterations in the loop
    assert sleep_mock.call_count == 5
    assert sleep_mock.called_with(1)

    # Check that all the com ports got created, destroyed, then re-created as expected
    assert SerialConsoleStreamTest.added_devices == ["com1", "com2", "com3", "com1", "com_stop"]


@patch('serial.Serial')
def test_SerialConsoleStream_process_input(serial_mock):
    class SerialConsoleStreamTest(SerialConsoleStream):
        def process_input_line(self, line):
            assert line == b"My line"
            self.stop_input_processing.set()

    serial_mock.return_value.readline.return_value = b"My line"

    stream = SerialConsoleStreamTest("device")
    stream.process_input()

    # Make sure the serial port was opened correctly
    assert serial_mock.called_once_with("device", baudrate=115200)


@patch('serial.Serial')
def test_SerialConsoleStream_send(serial_mock):
    stream = SerialConsoleStream("device")

    data = b"toto"
    stream._send(data)
    serial_mock.return_value.write.assert_called_once_with(data)
