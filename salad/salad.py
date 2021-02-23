#!/usr/bin/env python3

from datetime import datetime
from threading import Thread

import serial.tools.list_ports
import threading
import serial
import copy
import time
import sys
import re


class Line:
    def __init__(self, data, is_input=True):
        self.time = datetime.now()
        self.is_input = is_input
        self.data = data


class Session:
    def __init__(self):
        self.started_at = None
        self.ended_at = None

        self._lines = []

    @property
    def has_started(self):
        return self.started_at is not None

    @property
    def has_ended(self):
        return self.ended_at is not None

    @property
    def raw_logs(self):
        logs = b""
        for line in self._lines:
            logs += line.data
        return logs

    def append_input_line(self, line):
        if self.started_at is None:
            self.started_at = datetime.now()

        self._lines.append(Line(line))

    def append_output_line(self, line):
        self._lines.append(Line(line, is_input=False))

    def end(self):
        self.ended_at = datetime.now()


class Machine:
    _machines = dict()

    def __init__(self, machine_id):
        self.machine_id = machine_id

        self.session_cur = Session()
        self.session_prev = None
        self.session_next = Session()

        self._machines[self.machine_id] = self

    def __del__(self):
        try:  # pragma: nocover
            del self._machines[self.machine_id]
        except Exception:
            pass

    @property
    def sessions(self):
        sessions = dict()

        if self.session_prev is not None:
            sessions["prev"] = self.session_prev

        if self.session_cur is not None:
            sessions["cur"] = self.session_cur

        if self.session_next is not None:
            sessions["next"] = self.session_next

        return sessions

    def start_new_session(self):
        self.session_cur.end()

        self.session_prev = self.session_cur
        self.session_cur = self.session_next
        self.session_next = Session()

        return self.session_cur

    @classmethod
    def find_or_create(cls, machine_id):
        machine = cls._machines.get(machine_id)
        if machine is None:
            machine = cls(machine_id)
        return machine

    @classmethod
    def get_by_id(cls, machine_id):
        return cls._machines.get(machine_id)

    @classmethod
    def known_machines(cls):
        return list(cls._machines.keys())


class ConsoleStream(Thread):
    def __init__(self, stream_name):
        super().__init__()

        self.stream_name = stream_name

        self.machine_id_re = \
            re.compile(b".*SALAD.machine_id=(?P<machine_id>\\S+).*")

        self.new_session_re = \
            re.compile(b"^\r\\[    0.000000\\] Linux version")

        self.ping_re = re.compile(b"^SALAD.ping$")

        self.end_session_re = \
            re.compile(b"^SALAD.close_current_session$")  # reboot: Restarting system

        self.associated_machine = None
        self.cur_session = Session()

    @property
    def machine_id(self):
        machine = self.associated_machine
        return "UNKNOWN" if machine is None else machine.machine_id

    def log_msg(self, data, is_input=True):
        dir = "-->" if is_input else "<--"
        print(f"{self.stream_name}/{self.machine_id} {dir} {data}")

    def _send(self, data):
        # To be implemented by the children of this class
        print(f"WARNING: The console '{self.stream_name}' does not implement the _send() method", file=sys.stderr)

    def send(self, data):
        self.cur_session.append_output_line(data)
        self._send(data)
        self.log_msg(data, is_input=False)

    def process_input_line(self, line):
        machine = self.associated_machine

        # Check if the new line indicate for which machine the stream is for
        m = self.machine_id_re.match(line)
        if m:
            # We found a machine!
            new_machine_id = m.groupdict().get('machine_id').decode()

            # Associate the current session to the machine
            new_machine = Machine.find_or_create(new_machine_id)
            new_machine.session_cur = copy.deepcopy(self.cur_session)

            # Make sure users are aware when the ownership of a console changes
            if machine is not None and new_machine_id != machine.machine_id:
                print((f"WARNING: The console {self.stream_name}'s associated "
                       f"machine changed from {machine.machine_id} "
                       f"to {new_machine_id}"))
                machine.session_cur.end()

            # Make the new machine the associated machine of this session
            self.associated_machine = machine = new_machine
            self.cur_session = new_machine.session_cur

        if self.new_session_re.match(line):
            print(f"{self.machine_id}: Starting a new session")
            if machine is not None:
                self.cur_session = machine.start_new_session()
            else:
                self.cur_session = Session()

        self.cur_session.append_input_line(line)
        self.log_msg(line)

        if self.ping_re.match(line):
            self.send(b"SALAD.pong\n")
        elif self.end_session_re.match(line):
            if machine is not None:
                machine.session_cur.end()
            print(f"{self.machine_id}: Session is over")

    def run(self):
        try:
            self.process_input()
        except KeyboardInterrupt:  # pragma: nocover
            pass


class SerialConsoleStream(ConsoleStream):
    def __init__(self, dev):
        self.serial_dev = dev

        self._ser = serial.Serial(self.serial_dev, baudrate=115200)
        self.stop_input_processing = threading.Event()

        super().__init__(self.serial_dev)

    def _send(self, data):
        self._ser.write(data)

    def process_input(self):
        while not self.stop_input_processing.is_set():
            self.process_input_line(self._ser.readline())

    @classmethod
    def listen_to_all_serial_ports(cls, stop_event=None):
        serial_devs = {}
        while stop_event is None or not stop_event.is_set():
            ports = set([p.device for p in serial.tools.list_ports.comports()])

            for new_dev in ports - set(serial_devs.keys()):
                try:
                    t = cls(new_dev)
                    t.start()
                    serial_devs[new_dev] = t

                    print(f"Found new serial device {new_dev}")
                except Exception as e:
                    print(e)

            for old_dev in set(serial_devs.keys()) - ports:
                print(f"Serial device {old_dev} got removed")
                t = serial_devs[old_dev]
                t.join()  # just wait for the thread to die, it shouldn't take long!
                del serial_devs[old_dev]

            time.sleep(1)


if __name__ == '__main__':  # pragma: nocover
    SerialConsoleStream.listen_to_all_serial_ports()
