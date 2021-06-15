#!/usr/bin/env python3

from datetime import datetime
from threading import Thread, Event
from collections import defaultdict
from urllib.parse import urlparse, urlsplit
from enum import Enum, IntEnum

from pdu import PDUState
from client import JobStatus
from job import Job
from logger import logger

import traceback
import requests
import tempfile
import select
import socket
import time
import os
from minio import Minio


# Constants
CONSOLE_DRAINING_DELAY = 1


class MachineState(Enum):
    WAIT_FOR_CONFIG = 0
    IDLE = 1
    TRAINING = 2
    QUEUED = 3
    RUNNING = 4


class LogLevel(IntEnum):
    DEBUG = 0
    INFO = 1
    WARN = 2
    ERROR = 3


def str_to_int(string, default):
    try:
        return int(string)
    except Exception:
        return default


class JobConsole(Thread):
    def __init__(self, machine_id, client_endpoint, console_patterns, clientless=False, log_level=LogLevel.INFO):
        super().__init__(name='ConsoleThread')

        self.machine_id = machine_id

        self.client_endpoint = client_endpoint
        self.console_patterns = console_patterns
        self.clientless = clientless
        self.log_level = log_level

        # Thread
        self._stop_event = Event()

        # Sockets
        self.client_sock = None
        self.salad_sock = self.connect_to_salad()

        # Job-long state
        self.is_over = False
        self.start_time = None
        self.line_buffer = b""

        self.reset_per_boot_state()

    @property
    def salad_base_url(self):
        return os.getenv('SALAD_URL', "http://10.42.0.1:8005")

    @property
    def salad_url(self):
        return f"{self.salad_base_url}/api/v1/machine/{self.machine_id}"

    def connect_to_salad(self):
        parsed_url = urlsplit(self.salad_base_url)

        r = requests.get(self.salad_url)
        r.raise_for_status()

        machine = r.json()
        port = machine.get("tcp_port")

        return socket.create_connection((parsed_url.hostname, port))

    def reset_per_boot_state(self):
        self.last_activity_from_machine = None
        self.last_activity_from_client = None

        self.console_patterns.reset_per_boot_state()
        self.needs_reboot = self.console_patterns.needs_reboot

    def start(self):
        if not self.clientless:
            logger.info(f"Connecting to the client endpoint {self.client_endpoint}")
            self.client_sock = socket.create_connection(self.client_endpoint)
        self.start_time = datetime.now()

        super().start()

    def match_console_patterns(self, buf):
        patterns_matched = set()

        # Process the buffer, line by line
        to_process = self.line_buffer + buf
        cur = 0
        while True:
            idx = to_process.find(b'\n', cur)
            if idx > 0:
                line = to_process[cur:idx+1]
                logger.info(f"{self.machine_id} -> {line}")
                patterns_matched |= self.console_patterns.process_line(line)
                cur = idx + 1
            else:
                break
        self.line_buffer = to_process[cur:]

        # Tell the user what happened
        if len(patterns_matched) > 0:
            self.log(f"Matched the following patterns: {', '.join(patterns_matched)}\n")

        # Check if the state changed
        self.needs_reboot = self.console_patterns.needs_reboot

    def log(self, msg, log_level=LogLevel.INFO):
        # Ignore messages with a log level lower than the minimum set
        if log_level < self.log_level:
            return

        if self.start_time is not None:
            relative_time = (datetime.now() - self.start_time).total_seconds()
        else:
            relative_time = 0.0

        log_msg = f"+{relative_time:.3f}s: {msg}"
        logger.info(log_msg.rstrip("\r\n"))

        if not self.clientless:
            try:
                self.client_sock.send(log_msg.encode())
            except OSError:
                pass

    def close(self):
        was_over = self.is_over
        self.is_over = True

        if not was_over:
            self.log(f"<-- End of the session: {self.console_patterns.job_status} -->\n")

        if not self.clientless:
            try:
                self.client_sock.shutdown(socket.SHUT_RDWR)
                self.client_sock.close()
            except OSError:
                pass

        try:
            self.salad_sock.shutdown(socket.SHUT_RDWR)
            self.salad_sock.close()
        except OSError:
            pass

        self._stop_event.set()

    def stop(self):
        self._stop_event.set()
        self.join()

    def run(self):
        while not self._stop_event.is_set():
            fds = [self.salad_sock.fileno()]
            if not self.clientless:
                fds.extend([self.client_sock.fileno()])

            rlist, _, _ = select.select(fds, [], [], 1.0)

            for fd in rlist:
                try:
                    if fd == self.salad_sock.fileno():
                        # DUT's stdout/err: Salad -> Client
                        buf = self.salad_sock.recv(8192)
                        if len(buf) == 0:
                            self.close()

                        # Match the console patterns
                        try:
                            self.match_console_patterns(buf)
                        except Exception:
                            self.log(traceback.format_exc())

                        self.last_activity_from_machine = datetime.now()

                        # Forward to the client
                        if not self.clientless:
                            self.client_sock.send(buf)

                        # The message got forwarded, close the session if it ended
                        if self.console_patterns.session_has_ended:
                            self.close()

                    elif fd == self.client_sock.fileno():
                        # DUT's stdin: Client -> Salad
                        buf = self.client_sock.recv(8192)
                        if len(buf) == 0:
                            self.close()

                        self.last_activity_from_client = datetime.now()

                        # Forward to the salad
                        self.salad_sock.send(buf)
                except (ConnectionResetError, BrokenPipeError, OSError):
                    self.log(traceback.format_exc())
                    self.close()
                except Exception:
                    logger.error(traceback.format_exc())


class SergentHartman:
    def __init__(self, machine, boot_loop_counts=None, qualifying_rate=None):
        super().__init__()

        if boot_loop_counts is None:
            boot_loop_counts = str_to_int(os.environ.get("SERGENT_HARTMAN_BOOT_COUNT"), 100)

        if qualifying_rate is None:
            qualifying_rate = str_to_int(os.environ.get("SERGENT_HARTMAN_QUALIFYING_BOOT_COUNT"), 100)

        self.machine = machine
        self.boot_loop_counts = boot_loop_counts
        self.qualifying_rate = qualifying_rate

        self.reset()

    @property
    def is_machine_registered(self):
        return self.cur_loop > 0

    def reset(self):
        self.is_active = False
        self.cur_loop = 0
        self.statuses = defaultdict(int)

    def next_task(self):
        mid = self.machine.id

        if not self.is_active:
            # Start by forcing the machine to register itself to make sure the
            # its configuration is up to date (especially the serial console
            # port). Loop until it succeeds!
            self.reset()

            logger.info("SergentHartman/%s - Try registering the machine", mid)

            self.is_active = True

            return Job.from_path(self.register_template, self.machine)
        else:
            # Check that we got the expected amount of reports
            if self.cur_loop != sum(self.statuses.values()):
                raise ValueError("The previous next_task() call was not followed by a call to report()")

            # The registration went well, let's start the boot loop!
            self.cur_loop += 1

            statuses_str = [f"{status.name}: {values}" for status, values in self.statuses.items()]
            logger.info("SergentHartman/%s - loop %s/%s - statuses %s: "
                        "Execute one more round!",
                        mid,
                        self.cur_loop,
                        self.boot_loop_counts,
                        statuses_str)

            return Job.from_path(self.bootloop_template, self.machine)

    def report(self, job_status):
        mid = self.machine.id

        if self.cur_loop == 0:
            if job_status != JobStatus.PASS:
                delay = str_to_int(os.getenv("SERGENT_HARTMAN_REGISTRATION_RETRIAL_DELAY", None), 120)
                logger.warning((f"SergentHartman/{mid} - Registration failed with status {job_status.name}. "
                                f"Retrying in {delay} second(s)"))
                self.reset()
                return delay
            else:
                logger.info(f"SergentHartman/{mid} - Registration succeeded, moving on to the boot loop")
        else:
            # We are in the boot loop
            self.statuses[job_status] += 1

            if self.cur_loop == self.boot_loop_counts:
                self.is_active = False

                # Update MaRS
                ready_for_service = self.statuses[JobStatus.PASS] >= self.qualifying_rate
                self.machine.ready_for_service = ready_for_service

        return 0

    @property
    def register_template(self):
        return os.getenv('EXECUTOR_REGISTRATION_JOB', None)

    @property
    def bootloop_template(self):
        return os.getenv('EXECUTOR_BOOTLOOP_JOB', None)

    @property
    def is_available(self):
        return self.register_template is not None or self.bootloop_template is not None


class MinioCache():
    def __init__(self, url=None):
        if url is None:
            url = os.environ.get("MINIO_URL", "http://10.42.0.1:9000")

        parsed_url = urlparse(url)
        self.url = url

        secret_key = os.environ.get('MINIO_ROOT_PASSWORD')
        if secret_key is None:
            secret_key = "random"
            logger.warning("No password specified, jobs won't be runnable")

        self._client = Minio(
            endpoint=parsed_url.netloc,
            access_key="minioadmin",
            secret_key=secret_key,
            secure=False,
        )

    def is_local_url(self, url):
        return url.startswith(f"{self.url}/")

    def save_boot_artifact(self, remote_artifact_url, minio_object_name):
        minio_bucket_name = 'boot'
        with tempfile.NamedTemporaryFile("wb") as temp_download_area, \
             requests.get(remote_artifact_url, stream=True) as r:
            r.raise_for_status()
            # Read all the available data, then write to disk
            for chunk in r.iter_content(None):
                temp_download_area.write(chunk)
            temp_download_area.flush()
            self._client.fput_object(minio_bucket_name, minio_object_name, temp_download_area.name)


class Executor(Thread):
    def __init__(self, machine):
        super().__init__(name=f'ExecutorThread-{machine.id}')

        self.machine = machine

        self.state = MachineState.WAIT_FOR_CONFIG
        self.minio_cache = MinioCache()

        # Training / Qualifying process
        self.sergent_hartman = SergentHartman(machine)

        # Outside -> Inside communication
        self.job_ready = Event()
        self.job_config = None
        self.job_console = None

        # Remote artifacts (typically over HTTPS) are stored in our
        # local minio instance which is exposed over HTTP to the
        # private LAN. This makes such artifacts amenable to PXE
        # booting, for which HTTPS clients are not available.  Less
        # critically, it makes access easier for the boards in our
        # private LAN, for which HTTPS offers no advantage.
        self.remote_url_to_local_cache_mapping = {}

        # Start the background thread that will manage the machine
        self.stop_event = Event()
        self.start()

    def start_job(self, job, console_endpoint):
        if self.state != MachineState.IDLE:
            raise ValueError(f"The machine isn't idle: Current state is {self.state.name}")

        self.state = MachineState.QUEUED
        self.job_config = job
        self.job_console = JobConsole(self.machine.id, console_endpoint, self.job_config.console_patterns)
        self.job_ready.set()

    def log(self, msg, log_level=LogLevel.INFO):
        if self.job_console is not None:
            self.job_console.log(msg, log_level=log_level)

    def _cache_remote_artifact(self, artifact_name, start_url, continue_url):
        artifact_prefix = f"{artifact_name}-{self.machine.id}"

        # Assume the remote artifacts already exist locally
        self.remote_url_to_local_cache_mapping[start_url] = start_url
        self.remote_url_to_local_cache_mapping[continue_url] = continue_url

        def cache_it(url, suffix):
            if self.minio_cache.is_local_url(url):
                logger.debug(f"Ignore caching {url} as it is already hosted by our minio cache")
                return
            self.remote_url_to_local_cache_mapping[url] = f"http://10.42.0.1:9000/boot/{artifact_prefix}-{suffix}"
            self.log(f'Caching {url} into minio...\n')
            self.minio_cache.save_boot_artifact(start_url, f"{artifact_prefix}-start")

        cache_it(start_url, 'start')
        if start_url != continue_url:
            cache_it(continue_url, 'continue')

    def _cache_remote_artifacts(self):
        deploy_strt = self.job_config.deployment_start
        deploy_cnt = self.job_config.deployment_start

        logger.info("Caching the kernel...")
        self._cache_remote_artifact("kernel", deploy_strt.kernel_url,
                                    deploy_cnt.kernel_url)
        logger.info("Caching the initramfs...")
        self._cache_remote_artifact("initramfs", deploy_strt.initramfs_url,
                                    deploy_cnt.initramfs_url)

    def run(self):
        def session_init():
            # Reset the state
            self.job_config = None
            self.job_console = None

            # Pick a job
            if self.sergent_hartman.is_available and not self.machine.ready_for_service:
                self.state = MachineState.TRAINING

                self.job_config = self.sergent_hartman.next_task()
                self.job_console = JobConsole(self.machine.id,
                                              client_endpoint=None,
                                              clientless=True,
                                              console_patterns=self.job_config.console_patterns)
            else:
                self.sergent_hartman.reset()

                # Wait for a job to be set
                self.state = MachineState.IDLE
                if not self.job_ready.wait(1):
                    return False
                self.job_ready.clear()

                self.state = MachineState.RUNNING

            # Cut the power to the machine, we do not need it
            self.machine.pdu_port.set(PDUState.OFF)

            # Mark the start time to now()
            self.job_start_time = datetime.now()

            # Connect to the client's endpoint, to relay the serial console
            self.job_console.start()

            return True

        def session_end():
            cooldown_delay_s = 0

            if self.sergent_hartman.is_active and self.job_config is not None:
                status = JobStatus.from_str(self.job_config.console_patterns.job_status)
                cooldown_delay_s = int(self.sergent_hartman.report(status))

            self.job_config = None

            # Signal to the job that we reached the end of the execution
            if self.job_console is not None:
                time.sleep(CONSOLE_DRAINING_DELAY)  # Delay to make sure messages are read before the end of the job
                self.job_console.close()
                self.job_console = None

            # Interruptible sleep
            for i in range(cooldown_delay_s):
                if self.stop_event.is_set():
                    return
                time.sleep(1)

        def execute_job():
            # Start the overall timeout
            timeouts = self.job_config.timeouts
            timeouts.overall.start()

            # Download the kernel/initramfs
            self.log("Setup the infrastructure\n")
            timeouts.infra_setup.start()
            self._cache_remote_artifacts()
            self.log(f"Completed setup of the infrastructure, after {timeouts.infra_setup.active_for} s")
            timeouts.infra_setup.stop()

            # Keep on resuming until success, timeouts' retry limits is hit, or the entire executor is going down
            deployment = self.job_config.deployment_start
            while not self.stop_event.is_set() and not timeouts.overall.has_expired and not self.job_console.is_over:
                self.job_console.reset_per_boot_state()

                # Make sure the machine shuts down
                self.machine.pdu_port.set(PDUState.OFF)

                # Set up the deployment
                self.log("Setting up the boot configuration\n")
                self.machine.boots.write_pxelinux_config(
                    mac_addr=self.machine.id,
                    kernel_path=self.remote_url_to_local_cache_mapping.get(deployment.kernel_url),
                    cmdline=deployment.kernel_cmdline,
                    initrd_path=self.remote_url_to_local_cache_mapping.get(deployment.initramfs_url))

                self.log(f"Power up the machine, enforcing {self.machine.pdu_port.min_off_time} seconds of down time\n")
                self.machine.pdu_port.set(PDUState.ON)

                # Start the boot, and enable the timeouts!
                self.log("Boot the machine\n")
                timeouts.boot_cycle.start()
                timeouts.first_console_activity.start()
                timeouts.console_activity.stop()

                while (not self.job_console.is_over and not self.job_console.needs_reboot
                       and not self.stop_event.is_set() and not timeouts.has_expired):
                    # Update the activity timeouts, based on when was the
                    # last time we sent it data
                    if self.job_console.last_activity_from_machine is not None:
                        timeouts.first_console_activity.stop()
                        timeouts.console_activity.reset(when=self.job_console.last_activity_from_machine)

                    # Wait a little bit before checking again
                    time.sleep(0.1)

                # Cut the power
                self.machine.pdu_port.set(PDUState.OFF)

                # Increase the retry count of the timeouts that expired, and
                # abort the job if we exceeded their limits.
                abort = False
                for timeout in timeouts.expired_list:
                    retry = timeout.retry()
                    decision = "Try again!" if retry else "Abort!"
                    self.log(f"Hit the timeout {timeout} --> {decision}\n", LogLevel.ERROR)
                    abort = abort or not retry

                # Check if the DUT asked us to reboot
                if self.job_console.needs_reboot:
                    retry = timeouts.boot_cycle.retry()
                    retries_str = f"{timeouts.boot_cycle.retried}/{timeouts.boot_cycle.retries}"
                    dec = f"Boot cycle {retries_str}, go ahead!" if retry else "Exceeded boot loop count, aborting!"
                    self.log(f"The DUT asked us to reboot: {dec}\n", LogLevel.WARN)
                    abort = abort or not retry

                if abort:
                    return

                # Stop all the timeouts, except the overall
                timeouts.first_console_activity.stop()
                timeouts.console_activity.stop()
                timeouts.boot_cycle.stop()

                # We went through one boot cycle, update the
                deployment = self.job_config.deployment_continue

        while not self.stop_event.is_set():
            try:
                # Wait for the machine to have an assigned PDU port
                if self.machine.pdu_port is None:
                    time.sleep(1)
                    continue

                try:
                    if not session_init():
                        # No jobs for us to run!
                        continue

                    self.log(f"Starting the job: {self.job_config}\n\n", LogLevel.DEBUG)
                    execute_job()
                except Exception:
                    logger.debug("Exception caught:\n%s", traceback.format_exc())
                    self.log(f"An exception got caught: {traceback.format_exc()}\n", LogLevel.ERROR)

                session_end()
            except Exception:
                traceback.print_exc()
                # If exceptions start firing, throttle the run loop,
                # since it's very heavy spam if left to run at full
                # speed.
                time.sleep(2)

            # TODO: Keep the state of the job in memory for later querying
