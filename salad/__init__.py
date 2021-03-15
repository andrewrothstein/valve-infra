#!/usr/bin/env python3

from datetime import datetime
from threading import Thread
from enum import Enum

import serial.tools.list_ports
import traceback
import threading
import select
import serial
import socket
import copy
import time
import sys
import re


class ConsoleStream:
    def __init__(self, stream_name):
        self.stream_name = stream_name
        self.machine_id = None

        self.machine_id_re = \
            re.compile(b".*SALAD.machine_id=(?P<machine_id>\\S+).*")

        self.ping_re = re.compile(b"^SALAD.ping\r?\n$")

    def log_msg(self, data, is_input=True):
        dir = "-->" if is_input else "<--"
        mid = "UNKNOWN" if self.machine_id is None else self.machine_id
        print(f"{self.stream_name}/{mid} {dir} {data}")

    def _send(self, data):
        # To be implemented by the children of this class
        print(f"WARNING: The console '{self.stream_name}' does not implement the _send() method", file=sys.stderr)

    def send(self, data):
        self._send(data)
        self.log_msg(data, is_input=False)

    def process_input_line(self, line):
        # Check if the new line indicate for which machine the stream is for
        m = self.machine_id_re.match(line)
        if m:
            # We found a machine!
            new_machine_id = m.groupdict().get('machine_id').decode()

            # Make sure users are aware when the ownership of a console changes
            if self.machine_id is not None and new_machine_id != self.machine_id:
                print((f"WARNING: The console {self.stream_name}'s associated "
                       f"machine changed from {self.machine_id} "
                       f"to {new_machine_id}"))

            # Make the new machine the associated machine of this session
            self.machine_id = new_machine_id

        self.log_msg(line)

        if self.ping_re.match(line):
            self.send(b"SALAD.pong\n")


class SerialConsoleStream(ConsoleStream):
    def __init__(self, dev):
        super().__init__(dev)

        self.serial_dev = dev
        self.device = serial.Serial(self.serial_dev, baudrate=115200, timeout=0)

        self.line_buffer = b""

    def fileno(self):
        return self.device.fileno()

    def _send(self, data):
        self.device.write(data)

    def recv(self):
        r_buf = b""

        while True:
            buf = self.device.read(1)
            if len(buf) == 0:
                return r_buf

            r_buf += buf

            self.line_buffer += buf
            is_new_line = buf[0] == ord('\n')
            if is_new_line:
                self.process_input_line(self.line_buffer)
                self.line_buffer = b""


# Inherit from this class to hook on the send/read
class JobSession:
    def __init__(self, machine_id):
        self.machine_id = machine_id
        self.sock = None

        self.is_over = False

    def start(self):
        raise ValueError("The start method is not implemented")

    def fileno(self):
        return self.sock.fileno()

    def send(self, buf):
        try:
            self.sock.send(buf)
        except (ConnectionResetError, BrokenPipeError, OSError):
            self.close()

    def recv(self, size=8192):
        buf = b""
        try:
            buf = self.sock.recv(size)
            if len(buf) == 0:
                self.close()
        except (ConnectionResetError, BrokenPipeError, OSError):
            self.close()

        return buf

    def close(self):
        self.is_over = True
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
            self.sock.close()
        except OSError:
            pass


class Salad(Thread):
    def __init__(self):
        super().__init__()

        self._stop_event = threading.Event()

        self._sessions = {}
        self._serial_devs = {}

    def find_serial_dev_for(self, machine_id):
        return next((s for s in self._serial_devs.values() if s.machine_id == machine_id), None)

    def register_session(self, session):
        cur_session = self._sessions.get(session.machine_id)
        if cur_session is not None and not cur_session.is_over:
            raise ValueError("A session for machine ID '{session.machine_id}' is already registered")

        self._sessions[session.machine_id] = session

        return True

    def _update_ports(self):
        ports = set([p.device for p in serial.tools.list_ports.comports()])

        for new_dev in ports - set(self._serial_devs.keys()):
            try:
                self._serial_devs[new_dev] = SerialConsoleStream(new_dev)
                print(f"Found new serial device {new_dev}")
            except Exception as e:
                print(f"ERROR: Could not allocate a stream for the serial port {new_dev}: {e}")

        for old_dev in set(self._serial_devs.keys()) - ports:
            print(f"Serial device {old_dev} got removed")
            del self._serial_devs[old_dev]

    def _remove_stale_sessions(self):
        for session in [s for s in self._sessions.values() if s.is_over]:
            self._sessions.pop(session.machine_id, None)

    def stop(self):
        self._stop_event.set()
        self.join()

    def run(self):
        while not self._stop_event.is_set():
            self._update_ports()
            self._remove_stale_sessions()

            fd_to_ser_console = dict([(p.fileno(), p) for p in self._serial_devs.values()])
            fd_to_session = dict([(s.fileno(), s) for m_id, s in self._sessions.items()])
            rlist, _, _ = select.select(list(fd_to_ser_console.keys()) + list(fd_to_session.keys()),
                                        [], [], 1.0)
            for fd in rlist:
                try:
                    if fd in fd_to_ser_console:
                        # DUT's stdout/err: Serial -> Socket
                        ser = fd_to_ser_console[fd]
                        buf = ser.recv()

                        session = self._sessions.get(ser.machine_id)
                        if session is not None:
                            session.send(buf)
                    elif fd in fd_to_session:
                        # DUT's stdin: Socket -> Serial
                        session = fd_to_session[fd]

                        # Drop the input if we do not have a serial port associated
                        buf = session.recv(8192)

                        ser_dev = self.find_serial_dev_for(session.machine_id)
                        if ser_dev is not None:
                            ser_dev.send(buf)
                except Exception as e:
                    traceback.print_exc()

salad = Salad()
