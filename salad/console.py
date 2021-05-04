from logger import logger

import serial
import re


class ConsoleStream:
    def __init__(self, stream_name):
        self.stream_name = stream_name
        self.machine_id = None

        self.machine_id_re = \
            re.compile(b".*SALAD.machine_id=(?P<machine_id>\\S+).*")

        # NOTE: Some adapters send garbage at first, so don't assume
        # the ping is at the first byte offset (i.e., do not think you
        # can anchor to ^), sometimes '\x00\x00SALAD.ping' is seen,
        # othertimes '\xfcSALAD.ping', and so on.
        self.ping_re = re.compile(b"SALAD.ping\r?\n$")

    def log_msg(self, data, is_input=True):
        dir = "-->" if is_input else "<--"
        mid = "UNKNOWN" if self.machine_id is None else self.machine_id
        logger.info(f"{self.stream_name}/{mid} {dir} {data}")

    def _send(self, data):
        # To be implemented by the children of this class
        logger.error(f"WARNING: The console '{self.stream_name}' does not implement the _send() method")

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
                logger.warning((f"WARNING: The console {self.stream_name}'s associated "
                                f"machine changed from {self.machine_id} "
                                f"to {new_machine_id}"))

            # Make the new machine the associated machine of this session
            self.machine_id = new_machine_id

        self.log_msg(line)

        if self.ping_re.search(line):
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

    def close(self):
        self.device.close()