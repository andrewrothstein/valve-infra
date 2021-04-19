#!/usr/bin/env python3

from datetime import datetime
from threading import Thread, Event
from collections import defaultdict
from jinja2 import Template
from enum import Enum, IntEnum

from salad import salad, JobSession
from pdu import PDU, PDUState
from client import JobStatus
from job import Job

import traceback
import requests
import tempfile
import socket
import time
import os
from minio import Minio
from logging import getLogger, getLevelName, Formatter, StreamHandler

logger = getLogger(__name__)
logger.setLevel(getLevelName('DEBUG'))
log_formatter = \
    Formatter("%(asctime)s [%(levelname)s] %(name)s: "
              "%(message)s [%(threadName)s] ")
console_handler = StreamHandler()
console_handler.setFormatter(log_formatter)
logger.addHandler(console_handler)

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


class JobConsole(JobSession):
    def __init__(self, machine_id, endpoint, console_patterns, clientless=False, log_level=LogLevel.INFO):
        super().__init__(machine_id)

        self.endpoint = endpoint
        self.console_patterns = console_patterns
        self.clientless = clientless
        self.log_level = log_level

        # Job-long state
        self.closing = False
        self.start_time = None
        self.line_buffer = b""

        self.reset_per_boot_state()

    def reset_per_boot_state(self):
        self.last_send_activity = None
        self.last_recv_activity = None

        self.console_patterns.reset_per_boot_state()
        self.needs_reboot = self.console_patterns.needs_reboot

    def start(self):
        if not self.clientless:
            self.sock = socket.create_connection(self.endpoint)
        self.start_time = datetime.now()

    def fileno(self):
        if self.clientless:
            return None
        else:
            return self.sock.fileno()

    def match_console_patterns(self, buf):
        patterns_matched = set()

        # Process the buffer, line by line
        to_process = self.line_buffer + buf
        cur = 0
        while True:
            idx = to_process.find(b'\n', cur)
            if idx > 0:
                patterns_matched |= self.console_patterns.process_line(to_process[cur:idx+1])
                cur = idx + 1
            else:
                break
        self.line_buffer = to_process[cur:]

        # Tell the user what happened
        if len(patterns_matched) > 0:
            self.log(f"Matched the following patterns: {', '.join(patterns_matched)}\n")

        # Check if the state changed
        if self.console_patterns.session_has_ended:
            self.close()
        self.needs_reboot = self.console_patterns.needs_reboot

    def _send(self, buf):
        if not self.clientless:
            try:
                self.sock.send(buf)
            except (ConnectionResetError, BrokenPipeError, OSError):
                self.close()
        else:
            print(buf.decode(), end="", flush=True)

    def send(self, buf):
        self.last_send_activity = datetime.now()

        self._send(buf)

        try:
            self.match_console_patterns(buf)
        except Exception:
            self.log(traceback.format_exc())

    def recv(self, size=8192):
        self.last_recv_activity = datetime.now()

        buf = b""

        if self.clientless:
            return buf

        try:
            buf = self.sock.recv(size)
            if len(buf) == 0:
                self.close()
        except (ConnectionResetError, BrokenPipeError, OSError):
            self.close()

        return buf

    def log(self, msg, log_level=LogLevel.INFO):
        # Ignore messages with a log level lower than the minimum set
        if log_level < self.log_level:
            return

        relative_time = (datetime.now() - self.start_time).total_seconds()

        machine = f"{self.machine_id}: " if self.clientless else ""
        log_msg = f"{machine}+{relative_time:.3f}s: {msg}"
        self._send(log_msg.encode())

    def close(self):
        if not self.closing:
            self.closing = True
            self.log(f"<-- End of the session: {self.console_patterns.job_status} -->\n")

        if not self.clientless:
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
                self.sock.close()
            except OSError:
                pass

        super().close()


def str_to_int(string, default):
    try:
        return int(string)
    except Exception:
        return default


class SergentHartman:
    def __init__(self, machine, boot_loop_counts=100, qualifying_rate=100):
        super().__init__()

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

    def create_job(self, job_template_path):
        with open(job_template_path, "r") as f_template:
            template_str = f_template.read()

            # Instantiate the template, and write in the temporary file
            template_params = {
                "ready_for_service": self.machine.ready_for_service,
                "machine_id": self.machine.machine_id,
                "machine_tags": set(self.machine.tags),
                "local_tty_device": self.machine.local_tty_device,
            }
            template = Template(template_str).render(**template_params)

            return Job(template)

    def next_task(self):
        mid = self.machine.machine_id

        if not self.is_active:
            # Start by forcing the machine to register itself to make sure the
            # its configuration is up to date (especially the serial console
            # port). Loop until it succeeds!
            self.reset()

            print(f"SergentHartman/{mid} - Try registering the machine")

            self.is_active = True

            return self.create_job(self.register_template)
        else:
            # Check that we got the expected amount of reports
            if self.cur_loop != sum(self.statuses.values()):
                raise ValueError("The previous next_task() call was not followed by a call to report()")

            # The registration went well, let's start the boot loop!
            self.cur_loop += 1

            statuses_str = [f"{status.name}: {values}" for status, values in self.statuses.items()]
            print(f"SergentHartman/{mid} - loop {self.cur_loop}/{self.boot_loop_counts} - statuses {statuses_str}: Execute one more round!")

            return self.create_job(self.bootloop_template)

    def report(self, job_status):
        mid = self.machine.machine_id

        if self.cur_loop == 0:
            if job_status != JobStatus.PASS:
                delay = str_to_int(os.getenv("SERGENT_HARTMAN_REGISTRATION_RETRIAL_DELAY", None), 120)
                print(f"SergentHartman/{mid} - Registration failed with status {job_status.name}. Retrying in {delay} second(s)")
                self.reset()
                return delay
            else:
                print(f"SergentHartman/{mid} - Registration succeeded, moving on to the boot loop")
        else:
            # We are in the boot loop
            self.statuses[job_status] += 1

            if self.cur_loop == self.boot_loop_counts:
                self.is_active = False

                # Update MaRS
                mars_machine_url = f"{self.machine.mars_base_url()}/api/v1/machine/{self.machine.machine_id}/"
                ready_for_service = self.statuses[JobStatus.PASS] >= self.qualifying_rate
                params = {
                    "ready_for_service": ready_for_service
                }
                r = requests.patch(mars_machine_url, json=params)
                r.raise_for_status()

                print(f"SergentHartman/{mid}: Reported to MaRS that the machine is {'' if ready_for_service else 'NOT '}ready for service")

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
    def __init__(self, endpoint="10.42.0.1:9000"):
        self._endpoint = endpoint
        self._client = Minio(
            endpoint=self._endpoint,
            access_key="minioadmin",
            secret_key=os.environ['MINIO_ROOT_PASSWORD'],
            secure=False,
        )

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


class BootsClient:
    @classmethod
    def url(cls, path):
        boots_url = os.getenv('BOOTS_URL', "http://localhost:8087")
        return f"{boots_url}{path}"

    @classmethod
    def set_config(cls, mac_addr, kernel_path, initramfs_path, kernel_cmdline):
        params = {
            "initrd_path": initramfs_path,
            "kernel_path": kernel_path,
            "cmdline": kernel_cmdline,
        }

        r = requests.post(cls.url(f"/duts/{mac_addr}/boot"), json=params)
        if r.status_code != 200:
            print("BOOTS ERROR: ", r.json())
        return r.status_code


class Machine(Thread):
    _machines = dict()

    @classmethod
    def mars_base_url(cls):
        return os.getenv('MARS_URL', "http://127.0.0.1")

    def __init__(self, machine_id, ready_for_service=False, tags=[], pdu_port=None,
                 local_tty_device=None):
        super().__init__()

        # Machine
        self.machine_id = machine_id
        self.minio_cache = MinioCache()
        self.pdu_port = pdu_port
        self.state = MachineState.WAIT_FOR_CONFIG
        self.ready_for_service = ready_for_service
        self.tags = set(tags)
        self.local_tty_device = local_tty_device

        # Training / Qualifying process
        self.sergent_hartman = SergentHartman(self)

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

        self._machines[self.machine_id] = self

        # Start the background thread that will manage the machine
        self.stop_event = Event()
        self.start()

    def __del__(self):
        try:  # pragma: nocover
            del self._machines[self.machine_id]
        except Exception as e:
            print(e)

    def start_job(self, job, console_endpoint):
        if self.state != MachineState.IDLE:
            raise ValueError(f"The machine isn't idle: Current state is {self.state.name}")

        self.state = MachineState.QUEUED
        self.job_config = job
        self.job_console = JobConsole(self.machine_id, console_endpoint, self.job_config.console_patterns)
        self.job_ready.set()

    def log(self, msg, log_level=LogLevel.INFO):
        if self.job_console is not None:
            self.job_console.log(msg, log_level=log_level)

    def _cache_remote_artifact(self, artifact_name, start_url, continue_url):
        artifact_prefix = f"{artifact_name}-{self.machine_id}"

        # Assume the remote artifacts already exist locally
        self.remote_url_to_local_cache_mapping[start_url] = start_url
        self.remote_url_to_local_cache_mapping[continue_url] = continue_url

        def cache_it(url, suffix):
            if url.startswith("http://10.42.0.1:9000"):
                logger.debug("skip caching {url} since it already exists")
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

        self._cache_remote_artifact("kernel", deploy_strt.kernel_url,
                                    deploy_cnt.kernel_url)
        self._cache_remote_artifact("initramfs", deploy_strt.initramfs_url,
                                    deploy_cnt.initramfs_url)

    def run(self):
        def session_init():
            # Reset the state
            self.job_config = None
            self.job_console = None

            # Cut the power to the machine, we do not need it
            self.pdu_port.set(PDUState.OFF)

            # Pick a job
            if self.sergent_hartman.is_available and not self.ready_for_service:
                self.state = MachineState.TRAINING

                self.job_config = self.sergent_hartman.next_task()
                self.job_console = JobConsole(self.machine_id, endpoint=None, clientless=True,
                                              console_patterns=self.job_config.console_patterns,
                                              log_level=LogLevel.WARN)
            else:
                # Wait for a job to be set
                self.state = MachineState.IDLE
                if not self.job_ready.wait(1):
                    return False
                self.job_ready.clear()

                self.state = MachineState.RUNNING

            # Mark the start time to now()
            self.job_start_time = datetime.now()

            # Connect to the client's endpoint, to relay the serial console
            self.job_console.start()

            return True

        def set_boot_config(deployment):
            # Allow the kernel cmdline to reference some machine attributes
            template = Template(deployment.kernel_cmdline)
            kernel_cmdline = template.render(machine_id=self.machine_id,
                                             tags=self.tags,
                                             local_tty_device=self.local_tty_device)

            BootsClient.set_config(mac_addr=self.machine_id,
                                   kernel_path=self.remote_url_to_local_cache_mapping.get(deployment.kernel_url),
                                   initramfs_path=self.remote_url_to_local_cache_mapping.get(deployment.initramfs_url),
                                   kernel_cmdline=kernel_cmdline)

        def session_end():
            cooldown_delay_s = 0

            if self.sergent_hartman.is_active and self.job_config is not None:
                status = JobStatus.from_str(self.job_config.console_patterns.job_status)
                cooldown_delay_s = int(self.sergent_hartman.report(status))

            self.job_config = None

            # Signal to the job that we reached the end of the execution
            if self.job_console is not None:
                self.job_console.close()
                self.job_console = None

            # Interruptible sleep
            for i in range(cooldown_delay_s):
                if self.stop_event.is_set():
                    return
                time.sleep(1)

        def execute_job():
            # Ask Salad to relay inputs/outputs to/from the test machine to/from the client
            salad.register_session(self.job_console)

            # Start the overall timeout
            timeouts = self.job_config.timeouts
            timeouts.overall.start()

            # Download the kernel/initramfs
            timeouts.infra_setup.start()
            self._cache_remote_artifacts()
            timeouts.infra_setup.stop()

            # Keep on resuming until success, timeouts' retry limits is hit, or the entire executor is going down
            deployment = self.job_config.deployment_start
            while not self.stop_event.is_set() and not timeouts.overall.has_expired and not self.job_console.is_over:
                self.job_console.reset_per_boot_state()

                # Make sure the machine shuts down
                self.pdu_port.set(PDUState.OFF)

                # Set up the deployment
                self.log("Setting up the boot configuration\n")
                set_boot_config(deployment)
                self.log(f"Power up the machine, enforcing {self.pdu_port.min_off_time} seconds of down time\n")
                self.pdu_port.set(PDUState.ON)

                # Start the boot, and enable the timeouts!
                self.log("Boot the machine\n")
                timeouts.boot_cycle.start()
                timeouts.first_console_activity.start()
                timeouts.console_activity.stop()

                while (not self.job_console.is_over and not self.job_console.needs_reboot
                       and not self.stop_event.is_set() and not timeouts.has_expired):
                    # Update the activity timeouts, based on when was the
                    # last time we sent it data
                    if self.job_console.last_send_activity is not None:
                        timeouts.first_console_activity.stop()
                        timeouts.console_activity.reset(when=self.job_console.last_send_activity)

                    # Wait a little bit before checking again
                    time.sleep(0.1)

                # Cut the power
                self.pdu_port.set(PDUState.OFF)

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
                    decision = f"Boot cycle {retries_str}, go ahead!" if retry else "Exceeded boot loop count, aborting!"
                    self.log(f"The DUT asked us to reboot: {decision}\n", LogLevel.WARN)
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
            # Wait for the machine to have an assigned PDU port
            if self.pdu_port is None:
                time.sleep(1)
                continue

            try:
                if not session_init():
                    continue
                self.log(f"Starting the job: {self.job_config}\n\n")

                execute_job()
            except Exception:
                self.log(f"An exception got caught: {traceback.format_exc()}\n", LogLevel.ERROR)

            session_end()

            # TODO: Keep the state of the job in memory for later querying

    @classmethod
    def update_or_create(cls, machine_id, ready_for_service=False, tags=[], pdu_port=None,
                         local_tty_device=None):
        machine = cls._machines.get(machine_id)
        if machine is None:
            machine = cls(machine_id, ready_for_service=ready_for_service,
                          tags=tags, pdu_port=pdu_port, local_tty_device=local_tty_device)
        else:
            machine.ready_for_service = ready_for_service
            machine.tags = tags
            if machine.pdu_port != pdu_port:
                machine.pdu_port = pdu_port
            machine.local_tty_device = local_tty_device

        return machine

    @classmethod
    def get_by_id(cls, machine_id):
        return cls._machines.get(machine_id)

    @classmethod
    def known_machines(cls):
        return list(cls._machines.values())

    @classmethod
    def sync_machines_with_mars(cls):
        def get_PDU_or_create_from_MaRS_URL(mars_pdu_url, pdu_port, pdu_off_delay):
            if mars_pdu_url is None:
                return None

            pdu = pdus.get(mars_pdu_url)
            if pdu is None:
                r = requests.get(mars_pdu_url)
                r.raise_for_status()

                p = r.json()
                pdu = PDU.create(p.get('pdu_model'), p.get('name'), p.get('config', {}))

            if pdu is not None:
                for port in pdu.ports:
                    if str(port.port_id) == str(pdu_port):
                        port.min_off_time = int(pdu_off_delay)
                        return port

            return None

        pdus = dict()

        r = requests.get(f"{cls.mars_base_url()}/api/v1/machine/")
        r.raise_for_status()

        local_only_machines = set(cls.known_machines())
        for m in r.json():
            # Ignore retired machines
            if m.get('is_retired', False):
                continue

            pdu_port = get_PDU_or_create_from_MaRS_URL(m.get('pdu'), m.get('pdu_port_id'),
                                                       m.get('pdu_off_delay', 5))
            machine = cls.update_or_create(m.get("mac_address"),
                                           ready_for_service=m.get('ready_for_service', False),
                                           tags=set(m.get('tags', [])),
                                           pdu_port=pdu_port,
                                           local_tty_device=m.get("local_tty_device"))

            # Remove the machine from the list of local-only machines
            local_only_machines.discard(machine)

        # Delete all the machines that are not found in MaRS
        for machine in local_only_machines:
            del cls._machines[machine.machine_id]

    @classmethod
    def find_suitable_machine(cls, target):
        cls.sync_machines_with_mars()

        wanted_tags = set(target.tags)

        # If the target_id is specified, check the tags
        if target.target_id is not None:
            machine = cls.get_by_id(target.target_id)
            if machine is None:
                return None, 404, f"Unknown machine with ID {target.target_id}"
            elif not wanted_tags.issubset(machine.tags):
                return None, 406, f"The machine {target.target_id} does not matching tags (asked: {wanted_tags}, actual: {machine.tags})"
            elif machine.state != MachineState.IDLE:
                return None, 409, f"The machine {target.target_id} is unavailable: Current state is {machine.state.name}"
            return machine, 200, None
        else:
            found_a_candidate_machine = False
            for machine in cls.known_machines():
                if not wanted_tags.issubset(machine.tags):
                    continue

                found_a_candidate_machine = True
                if machine.state == MachineState.IDLE:
                    return machine, 200, "success"

            if found_a_candidate_machine:
                return None, 409, f"All machines matching the tags {wanted_tags} are busy"
            else:
                return None, 406, f"No machines found matching the tags {wanted_tags}"

    @classmethod
    def shutdown_all_workers(cls):
        machines = cls.known_machines()

        # Signal all the workers we want to stop
        for machine in machines:
            machine.stop_event.set()
            try:
                machine.sergent_hartman.kill()
            except AttributeError:
                pass

        # Wait for all the workers to stop
        for machine in machines:
            machine.join()
