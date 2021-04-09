#!/usr/bin/env python3

from enum import Enum

import traceback
import argparse
import requests
import termios
import select
import socket
import time
import tty
import sys
import re
import os


class JobStatus(Enum):
    PASS = 0
    WARN = 1
    COMPLETE = 2
    FAIL = 3
    INCOMPLETE = 4
    UNKNOWN = 5
    SETUP_FAIL = 6

    @classmethod
    def from_str(cls, status):
        return getattr(cls, status, cls.UNKNOWN)

    @property
    def status_code(self):
        return self.value


class Job:
    def __init__(self, executor_url, job_desc, wait_if_busy=False):
        self.executor_url = executor_url
        self.job_desc = job_desc
        self.wait_if_busy = wait_if_busy

    def _setup_conection(self):
        # Set up a TCP server
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as tcp_server:
            tcp_server.bind(('', 0))
            tcp_server.listen(1)
            local_port = tcp_server.getsockname()[1]

            # Queue the job
            data = {
                "metadata": {
                    "callback_port": local_port,
                },
                "job": self.job_desc
            }

            first_wait = True
            while True:
                r = requests.post(f"{self.executor_url}/api/v1/jobs", json=data)
                if r.status_code == 200:
                    break
                elif r.status_code == 409 and self.wait_if_busy:
                    if first_wait:
                        print("No machines available for the job, waiting: ", end="", flush=True)
                        first_wait = False
                    else:
                        print(".", end="", flush=True)
                    time.sleep(1)
                else:
                    ret = r.json()
                    reason_msg = ret.get("reason")
                    print(f"ERROR: Could not queue the work: \"{reason_msg}\"", file=sys.stderr)
                    return None

            if not first_wait:
                print("")

            # We should not have a connection queued, accept it with a timeout
            print(f"Waiting for the executor to connect to our local port {local_port}")
            tcp_server.settimeout(5)
            try:
                sock, _ = tcp_server.accept()
            except socket.timeout:
                raise ValueError("The server failed to initiate a connection")

            # Set the resulting socket's timeout to blocking
            sock.settimeout(None)

        return sock

    def _parse_job_status(self, final_lines):
            try:
                m = re.search(b"<-- End of the session: (?P<status>\\w+) -->", final_lines)
                if m is not None:
                    status_str = m.groupdict({}).get("status", b"UNKNOWN").decode()
                    return JobStatus.from_str(status_str)
            except Exception as e:
                traceback.print_exc()

            return JobStatus.INCOMPLETE

    def _forward_inputs_and_outputs(self, job_socket):
        print(f"Connection established: Switch to proxy mode")

        # Set stdin to the raw input mode
        if sys.stdin.isatty():
            old_tty_attrs = termios.tcgetattr(sys.stdin)
            tty.setcbreak(sys.stdin)

        try:
            final_lines = b""
            while True:
                try:
                    readables = [job_socket]
                    if sys.stdin.isatty():
                        readables.append(sys.stdin)
                    r_fds, w_fds, x_fds = select.select(readables, [], [])

                    for fd in r_fds:
                        if fd is sys.stdin:
                            buf = os.read(sys.stdin.fileno(), 4096)
                            job_socket.send(buf)
                        elif fd is job_socket:
                            buf = job_socket.recv(4096)
                            if len(buf) == 0:
                                # The job is over, check the job status!
                                return self._parse_job_status(final_lines)

                            sys.stdout.buffer.write(buf)
                            sys.stdout.buffer.flush()

                            # Keep in memory the final lines, for later parsing
                            final_lines += buf
                            final_lines = final_lines[-100:]
                        else:
                            raise ValueError("Received an unexpected fd ")
                            print(f"Ooopsie! we don't know the fd {fd}")
                except KeyboardInterrupt:
                    # Forward the CTRL+C
                    job_socket.send(chr(3).encode())
        finally:
            if sys.stdin.isatty():
                termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_tty_attrs)

    def close(self, sock):
        try:
            sock.shutdown(socket.SHUT_RDWR)
            sock.close()
        except OSError:
            pass

    def start(self):
        sock = None

        try:
            sock = self._setup_conection()
            if sock is None:
                return JobStatus.SETUP_FAIL

            status = self._forward_inputs_and_outputs(sock)
        except Exception as e:
            traceback.print_exc()
            status = JobStatus.UNKNOWN
        finally:
            if sock is not None:
                self.close(sock)

        return status

    @classmethod
    def from_file(cls, executor_url, path, wait_if_busy=False):
        with open(path) as f:
            job_desc = f.read()

        return cls(executor_url, job_desc, wait_if_busy=wait_if_busy)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("-e", '--executor', dest='executor_url',
                        default="http://localhost:8003",
                        help='URL to the executor service')
    parser.add_argument("-w", "--wait", action="store_true",
                        help="Wait for a machine to become available if all are busy")
    parser.add_argument('action', help='Action this script should do',
                        choices=['run'])
    parser.add_argument("job", help='Job that should be run')
    args = parser.parse_args()

    job = Job.from_file(args.executor_url, args.job, args.wait)
    status = job.start()
    sys.exit(status.status_code)
