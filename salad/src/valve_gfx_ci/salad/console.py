from .logger import logger

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
        logger.info("Closing the %s serial port", self.serial_dev)
        self.device.close()


class TCPConsoleStream(ConsoleStream):
    def __init__(self, accepted_sock):
        super().__init__('netconsole@%s:%d' % accepted_sock[1])

        logger.info("Opening %s", self.stream_name)
        self.sock = accepted_sock[0]
        self.ping_re = re.compile(b"SALAD.ping$")
        self._line_buffer = b""

    def fileno(self):
        return self.sock.fileno()

    def _send(self, data):
        try:
            self.sock.sendall(data)
        except BrokenPipeError:
            logger.error("Sending %s failed, broken pipe", data)
            raise

    def recv(self):
        data = self.sock.recv(4096)
        lines = re.split(rb'\r?\n', self._line_buffer + data)
        self._line_buffer = lines.pop()
        for line in lines:
            self.process_input_line(line)
        return data

    def close(self):
        logger.info("Closing %s", self.stream_name)
        self.sock.close()
