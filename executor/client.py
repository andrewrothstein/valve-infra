#!/usr/bin/env python3

from logging import getLogger, getLevelName, Formatter, StreamHandler
from dataclasses import dataclass
from tarfile import TarFile

import traceback
import argparse
import requests
import tempfile
import termios
import select
import socket
import json
import time
import tty
import sys
import re
import os

from message import MessageType, Message, JobIOMessage, JobStatus


logger = getLogger(__name__)
logger.setLevel(getLevelName('DEBUG'))
log_formatter = \
    Formatter("%(asctime)s [%(levelname)s] %(funcName)s: "
              "%(message)s [%(threadName)s] ")
console_handler = StreamHandler()
console_handler.setFormatter(log_formatter)
logger.addHandler(console_handler)


@dataclass
class Response:
    version: int = 0
    error_msg: str = None


class Job:
    def __init__(self, executor_url, job_desc, wait_if_busy=False, callback_host=None,
                 machine_tags=None, machine_id=None, job_id=None, share_directory=None):
        self.executor_url = executor_url
        self.job_desc = job_desc
        self.wait_if_busy = wait_if_busy
        self.callback_host = callback_host

        self.machine_tags = machine_tags
        self.machine_id = machine_id
        self.job_id = job_id
        self.share_directory = share_directory

    def _create_archive(self):
        with (tempfile.NamedTemporaryFile(mode='wb', suffix='tar.gz', delete=False) as fp,
              TarFile.open(fileobj=fp, mode='w:gz') as tar):
            tar.add(self.share_directory, arcname="")
            return fp.name

    def _parse_response(self, r):
        try:
            ret = r.json()
        except Exception:
            return Response(error_msg=r.text)

        version = ret.get("version", 0)

        if version == 0:
            return Response(error_msg=ret.get("reason"))
        elif version == 1:
            return Response(**ret)
        else:
            raise ValueError(f"Unsupported response version {version}")

    def _setup_connection(self):
        def queue_job(**kwargs):
            first_wait = True

            while True:
                r = requests.post(f"{self.executor_url}/api/v1/jobs", **kwargs)
                response = self._parse_response(r)

                if r.status_code == 200:
                    return True, response
                elif r.status_code == 409 and self.wait_if_busy:
                    if first_wait:
                        print("No machines available for the job, waiting: ", end="", flush=True)
                        first_wait = False
                    else:
                        print(".", end="", flush=True)
                    time.sleep(1)
                else:
                    print(f"\nERROR: Could not queue the work: \"{response.error_msg}\"", file=sys.stderr)

                    return False, response

        # Set up a TCP server
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as tcp_server:
            tcp_server.bind(('', 0))
            tcp_server.listen(1)
            local_port = tcp_server.getsockname()[1]

            # Queue the job
            metadata = {
                "version": 1,
                "job_id": self.job_id,
                "callback": {
                    "port": local_port
                }
            }
            if self.callback_host is not None:
                metadata['callback']['host'] = self.callback_host

            if self.machine_id is not None or (self.machine_tags is not None and len(self.machine_tags) > 0):
                metadata['target'] = {
                    "id": self.machine_id,
                    "tags": self.machine_tags
                }

            files = [('metadata', ('metadata', json.dumps(metadata), 'application/json')),
                     ('job', ('job', self.job_desc, 'application/x-yaml'))]
            if self.share_directory:
                print("Packing up the share_directory")
                archive_path = self._create_archive()
                archive_stats = os.stat(archive_path)
                print("--> Wrote %s bytes..." % archive_stats.st_size)

                with open(archive_path, 'rb') as archive_file:
                    files.append(('job_bucket_initial_state_tarball_file',
                                  ('job_bucket_initial_state_tarball_file',
                                   archive_file,
                                   'application/octet-stream')))

                    success, response = queue_job(files=files)
                    if not success:
                        return None, response
            else:
                success, response = queue_job(files=files)
                if not success:
                    return None, response

            # We should not have a connection queued, accept it with a timeout
            print(f"Waiting for the executor to connect to our local port {local_port}")
            tcp_server.settimeout(5)
            try:
                sock, _ = tcp_server.accept()
            except socket.timeout:
                raise ValueError("The server failed to initiate a connection")

            # Set the resulting socket's timeout to blocking
            sock.settimeout(None)

        return sock, response

        # Set up a TCP server
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as tcp_server:
            tcp_server.bind(('', 0))
            tcp_server.listen(1)
            local_port = tcp_server.getsockname()[1]

            # Queue the job
            metadata = {
                "version": 1,
                "job_id": self.job_id,
                "callback": {
                    "port": local_port
                }
            }
            if self.callback_host is not None:
                metadata['callback']['host'] = self.callback_host

            if self.machine_id is not None or (self.machine_tags is not None and len(self.machine_tags) > 0):
                metadata['target'] = {
                    "id": self.machine_id,
                    "tags": self.machine_tags
                }

            files = [('metadata', ('metadata', json.dumps(metadata), 'application/json')),
                     ('job', ('job', self.job_desc, 'application/x-yaml'))]
            if self.share_directory:
                print("Packing up the share_directory")
                archive_path = self._create_archive()
                archive_stats = os.stat(archive_path)
                print("--> Wrote %s bytes..." % archive_stats.st_size)

                # TODO: Delete this file after calling requests
                archive_file = open(archive_path, 'rb')
                files.append(('job_bucket_initial_state_tarball_file',
                              ('job_bucket_initial_state_tarball_file',
                               archive_file,
                               'application/octet-stream')))
            first_wait = True
            while True:
                r = requests.post(f"{self.executor_url}/api/v1/jobs", files=files)
                response = self._parse_response(r)

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
                    print(f"ERROR: Could not queue the work: \"{response.error_msg}\"", file=sys.stderr)

                    return None, response

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

        return sock, response

    def _read_executor_message_v0(self, job_socket):
        # Local cache
        final_lines = getattr(self, "final_lines", None)
        if final_lines is None:
            self.final_lines = final_lines = bytearray()

        # Get the data
        buf = job_socket.recv(4096)
        if len(buf) == 0:
            # The job is over, check the job status!
            try:
                m = re.search(b'<-- End of the session: (?P<status>\\w+) -->', final_lines)
                if m is not None:
                    status_str = m.groupdict({}).get("status", b'UNKNOWN').decode()
                    return JobStatus.from_str(status_str)
            except Exception:
                traceback.print_exc()

        sys.stdout.buffer.write(buf)
        sys.stdout.buffer.flush()

        # Keep in memory the final lines, for later parsing
        final_lines += buf
        final_lines = final_lines[-100:]

        return None

    def _read_executor_message_v1(self, job_socket):
        try:
            msg = Message.next_message(job_socket)

            # TODO: Only display control messages at the end of a new line
            if msg.msg_type == MessageType.CONTROL:
                print(msg.message, flush=True, end="")
            elif msg.msg_type == MessageType.JOB_IO:
                sys.stdout.buffer.write(msg.buffer)
                sys.stdout.buffer.flush()
            elif msg.msg_type == MessageType.SESSION_END:
                return msg.status
        except Exception:
            traceback.print_exc()
            return JobStatus.INCOMPLETE

        return None

    def _forward_inputs_and_outputs(self, job_socket, job_response):
        print("Connection established: Switch to proxy mode")

        # Set stdin to the raw input mode
        if sys.stdin.isatty():
            old_tty_attrs = termios.tcgetattr(sys.stdin)
            tty.setcbreak(sys.stdin)

        control_char = b'\x01'  # CTRL+A
        control_char_pressed = False

        try:
            while True:
                try:
                    readables = [job_socket]
                    if sys.stdin.isatty():
                        readables.append(sys.stdin)
                    r_fds, w_fds, x_fds = select.select(readables, [], [])

                    for fd in r_fds:
                        if fd is sys.stdin:
                            buf = os.read(sys.stdin.fileno(), 1)
                            msg = JobIOMessage.create(buf)
                            if buf == control_char:
                                if control_char_pressed:
                                    # Repeating the control char sends it through
                                    msg.send(job_socket)
                                else:
                                    control_char_pressed = True
                            else:
                                control_char_pressed = False
                                msg.send(job_socket)
                        elif fd is job_socket:
                            if job_response.version == 0:
                                ret = self._read_executor_message_v0(job_socket)
                            else:
                                ret = self._read_executor_message_v1(job_socket)

                            if ret:
                                return ret
                        else:
                            raise ValueError(f"Received an unexpected fd: {fd}")
                except KeyboardInterrupt:
                    if control_char_pressed:
                        logger.info("Exiting the client in response to CTRL+C...")
                        return JobStatus.INCOMPLETE

                    logger.info("forwarding CTRL+C to job, type CTRL+A followed by CTRL+C to quit the client")
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

    def run(self):
        sock = None

        try:
            sock, response = self._setup_connection()
            if sock is None:
                return JobStatus.SETUP_FAIL

            status = self._forward_inputs_and_outputs(sock, response)
        except json.decoder.JSONDecodeError:
            logger.error("Invalid response from executor server")
            status = JobStatus.SETUP_FAIL
        except requests.exceptions.ConnectionError:
            logger.error("Failed to connect to the executor, is it running?")
            status = JobStatus.SETUP_FAIL
        except Exception:
            traceback.print_exc()
            status = JobStatus.UNKNOWN
        finally:
            if sock is not None:
                self.close(sock)

        return status

    @classmethod
    def from_file(cls, executor_url, path, wait_if_busy=False,
                  callback_host=None, machine_tags=None, machine_id=None,
                  share_directory=None, job_id=None):
        with open(path) as f:
            job_desc = f.read()

        return cls(executor_url, job_desc, wait_if_busy=wait_if_busy,
                   callback_host=callback_host, machine_tags=machine_tags,
                   machine_id=machine_id, share_directory=share_directory,
                   job_id=job_id)


def run_job(args):
    # Perform validation on the share directory
    if args.share_directory:
        if not os.path.isdir(args.share_directory):
            if os.path.exists(args.share_directory):
                raise ValueError("The share directory is not a folder")
            else:
                os.makedirs(args.share_directory)

    job = Job.from_file(executor_url=args.executor_url, path=args.job,
                        wait_if_busy=args.wait, job_id=args.job_id,
                        callback_host=args.callback, machine_tags=args.machine_tags,
                        machine_id=args.machine_id, share_directory=args.share_directory)

    status = job.run()
    logger.info("status: %s", status)
    sys.exit(status.status_code)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(prog='Executor client')
    parser.add_argument("-e", '--executor', dest='executor_url',
                        default="http://localhost",
                        help='URL to the executor service')

    subparsers = parser.add_subparsers()

    run_parser = subparsers.add_parser('run', help='run a job')
    run_parser.add_argument("-w", "--wait", action="store_true",
                            help="Wait for a machine to become available if all are busy")
    run_parser.add_argument("-c", "--callback",
                            help=("Hostname that the executor will use to connect back to this client, "
                                  "useful for non-trivial routing to the test device"))
    run_parser.add_argument("-t", "--machine-tag", action="append", dest="machine_tags",
                            help="Tag of the machine that should be running the job. Overrides the job's target.")
    run_parser.add_argument("-i", "--machine-id",
                            help="ID of the machine that should run the job. Overrides the job's target.")
    run_parser.add_argument("-s", "--share-directory",
                            help=("Directory that will be forwarded to the job, and whose changes will be "
                                  "forwarded back to"))
    run_parser.add_argument("-j", "--job-id", help="Identifier for the job, if you have one already.")
    run_parser.add_argument("job", help='Job that should be run')
    run_parser.set_defaults(func=run_job)

    args = parser.parse_args()
    args.func(args)
