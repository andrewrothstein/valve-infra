from threading import Thread
from logger import logger

from console import SerialConsoleStream
from tcpserver import SerialConsoleTCPServer

import serial.tools.list_ports
import traceback
import threading
import select


class Salad(Thread):
    def __init__(self):
        super().__init__(name=f'SaladThread')

        self._stop_event = threading.Event()

        self._machines = {}
        self._serial_devs = {}

    @property
    def machines(self):
        return list(self._machines.values())

    def find_serial_dev_for(self, machine_id):
        return next((s for s in self._serial_devs.values() if s.machine_id == machine_id), None)

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

    def run(self):
        while not self._stop_event.is_set():
            self._update_ports()

            fd_to_ser_console = dict([(p.fileno(), p) for p in self._serial_devs.values()])
            fd_to_machine_server = dict([(m.fileno_server, m) for m in self._machines.values()])
            fd_to_machine_client = dict([(m.fileno_client, m) for m in self._machines.values() if m.fileno_client is not None])
            rlist, _, _ = select.select(list(fd_to_ser_console) + list(fd_to_machine_server) + list(fd_to_machine_client),
                                        [], [], 1.0)

            for fd in rlist:
                try:
                    if fd in fd_to_ser_console:
                        # DUT's stdout/err: Serial -> Socket
                        ser = fd_to_ser_console[fd]
                        try:
                            buf = ser.recv()
                        except serial.SerialException:
                            buf = b""
                        if len(buf) == 0:
                            ser.close()

                        if ser.machine_id is not None:
                            machine = self.get_or_create_machine(ser.machine_id)
                            if machine is not None:
                                machine.send(buf)
                    elif fd in fd_to_machine_server:
                        # Incoming connections
                        fd_to_machine_server[fd].accept()
                    elif fd in fd_to_machine_client:
                        # DUT's stdin: Socket -> Serial
                        machine = fd_to_machine_client[fd]

                        # Drop the input if we do not have a serial port associated
                        buf = machine.recv(8192)
                        if len(buf) == 0:
                            machine.close_client()

                        ser_dev = self.find_serial_dev_for(machine.id)
                        if ser_dev is not None:
                            ser_dev.send(buf)
                except Exception:
                    logger.error(traceback.format_exc())


salad = Salad()
