from threading import Thread
from .logger import logger

from .console import (
    SerialConsoleStream,
    TCPConsoleStream
)
from .tcpserver import SerialConsoleTCPServer

import os
import serial.tools.list_ports
import traceback
import threading
import select
import socket
from itertools import chain


class Salad(Thread):
    def __init__(self):
        super().__init__(name='SaladThread')

        self._stop_event = threading.Event()

        netconsole_port = os.getenv("SALAD_TCPCONSOLE_PORT", 8100)
        self._netconsole_server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        netconsole_server_addr = ('', netconsole_port)
        self._netconsole_server_sock.bind(netconsole_server_addr)
        self._netconsole_server_sock.listen(1)

        self._machines = {}
        self._serial_devs = {}
        self._external_socket_streams = {}
        self._netconsole_streams = {}

    @property
    def machines(self):
        return list(self._machines.values())

    def find_console_listener(self, machine_id):
        return next((s for s in chain(self._serial_devs.values(),
                                      self._external_socket_streams.values())
                     if s.machine_id == machine_id), None)

    def get_or_create_machine(self, machine_id):
        machine = self._machines.get(machine_id)
        if machine is not None:
            return machine

        machine = SerialConsoleTCPServer(machine_id)
        self._machines[machine_id] = machine

        return machine

    def _update_ports(self):
        ports = set([p.device for p in serial.tools.list_ports.comports()])
        for new_dev in ports - set(self._serial_devs.keys()):
            try:
                self._serial_devs[new_dev] = SerialConsoleStream(new_dev)
                logger.warning(f"Found new serial device {new_dev}")
            except Exception as e:
                logger.error(f"ERROR: Could not allocate a stream for the serial port {new_dev}: {e}")

        for old_dev in set(self._serial_devs.keys()) - ports:
            logger.warning(f"Serial device {old_dev} got removed")
            del self._serial_devs[old_dev]

    def stop(self):
        self._stop_event.set()
        self.join()

    def send_to_console_listener(self, console, buf):
        if not console.machine_id:
            return
        if machine := self.get_or_create_machine(console.machine_id):
            machine.send(buf)

    def run(self):
        while not self._stop_event.is_set():
            self._update_ports()

            fd_to_ser_console = dict([(p.fileno(), p) for p in self._serial_devs.values()])
            fd_to_netconsole = dict([(s.fileno(), s) for s in self._netconsole_streams.values()])
            fd_to_machine_server = dict([(m.fileno_server, m) for m in self._machines.values()])
            fd_to_machine_client = dict([(m.fileno_client, m) for m in self._machines.values() if m.fileno_client is not None])
            ready_fds = list(chain(fd_to_ser_console,
                                   fd_to_machine_server,
                                   fd_to_machine_client,
                                   fd_to_netconsole))
            ready_fds.append(self._netconsole_server_sock.fileno())
            rlist, _, _ = select.select(ready_fds, [], [], 1.0)
            for fd in rlist:
                try:
                    if fd in fd_to_ser_console:
                        # DUT's stdout/err: Serial -> Socket
                        ser = fd_to_ser_console[fd]
                        try:
                            buf = ser.recv()
                            if len(buf) == 0:
                                ser.close()
                                continue

                            self.send_to_console_listener(ser, buf)
                        except serial.SerialException:
                            logger.warning(traceback.format_exc())
                    elif fd in fd_to_netconsole:
                        # DUT's stdout/err: Netconsole -> Socket
                        console = fd_to_netconsole[fd]
                        try:
                            buf = console.recv()
                            if len(buf) == 0:
                                console.close()
                                del self._netconsole_streams[console.stream_name]
                                continue
                            self.send_to_console_listener(console, buf)
                        except ConnectionResetError:
                            console.close()
                            del self._netconsole_streams[console.stream_name]
                    elif fd in fd_to_machine_server:
                        # Incoming connections
                        fd_to_machine_server[fd].accept()
                    elif fd == self._netconsole_server_sock.fileno():
                        console_client = self._netconsole_server_sock.accept()
                        console = TCPConsoleStream(console_client)
                        self._netconsole_streams[console.stream_name] = console
                    elif fd in fd_to_machine_client:
                        # DUT's stdin: Socket -> Console
                        machine = fd_to_machine_client[fd]

                        # Drop the input if we do not have a console associated
                        buf = machine.recv(8192)
                        if len(buf) == 0:
                            machine.close_client()
                            continue

                        if console := self.find_console_listener(machine.id):
                            console.send(buf)
                        else:
                            logger.warning("Dropping %s, no console attached for %s",
                                           buf, machine.id)
                except Exception:
                    logger.error(traceback.format_exc())


salad = Salad()
