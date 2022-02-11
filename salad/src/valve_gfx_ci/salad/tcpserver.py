from .logger import logger

import socket


class SerialConsoleTCPServer:
    def __init__(self, machine_id):
        self.id = machine_id

        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.bind(('', 0))
        self.server.listen(1)

        self.client = None

    @property
    def port(self):
        return self.server.getsockname()[1]

    @property
    def fileno_client(self):
        if self.client is None:
            return None

        return self.client.fileno()

    @property
    def fileno_server(self):
        return self.server.fileno()

    def accept(self):
        client, _ = self.server.accept()

        if self.client is not None:
            client.send(b"A client is already connected, re-try later!\r\n")
            client.shutdown(socket.SHUT_RDWR)
            client.close()
        else:
            self.client = client

    def send(self, buf):
        client = self.client
        if client is None:
            return

        try:
            client.send(buf)
        except (ConnectionResetError, BrokenPipeError, OSError):
            self.close_client()

    def recv(self, size=8192):
        client = self.client
        if client is not None:
            try:
                buf = self.client.recv(size)
                if len(buf) == 0:
                    self.close_client()
                return buf
            except (ConnectionResetError, BrokenPipeError, OSError):
                self.close_client()

        return b""

    def close_client(self):
        logger.info("Closing the connection for the client of %s", self.id)

        client = self.client

        self.client = None
        self.server.listen(1)

        if client is not None:
            client.shutdown(socket.SHUT_RDWR)
            client.close()
