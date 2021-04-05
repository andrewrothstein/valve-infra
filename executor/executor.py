#!/usr/bin/env python3

from datetime import datetime, timedelta
from threading import Thread, Event
from multiprocessing import Process
from collections import defaultdict
from jinja2 import Template
from enum import Enum

from salad import salad, JobSession
from pdu import PDU, PDUState
from bootsclient import BootsClient
from client import JobStatus

import subprocess
import traceback
import requests
import tempfile
import socket
import time
import yaml
import sys
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
    QUEUED = 2
    RUNNING = 3


class JobConsole(JobSession):
    def __init__(self, machine_id, endpoint, console_patterns):
        super().__init__(machine_id)

        self.endpoint = endpoint
        self.console_patterns = console_patterns

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
        self.sock = socket.create_connection(self.endpoint)
        self.start_time = datetime.now()

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

    def send(self, buf):
        self.last_send_activity = datetime.now()

        ret = super().send(buf)

        try:
            self.match_console_patterns(buf)
        except Exception:
            self.log(traceback.format_exc())

        return ret

    def recv(self, size=8192):
        self.last_recv_activity = datetime.now()
        return super().recv(size)

    def log(self, msg):
        relative_time = (datetime.now() - self.start_time).total_seconds()

        log_msg = f"+{relative_time:.3f}s: {msg}"
        super().send(log_msg.encode())

    def close(self):
        if not self.closing:
            self.closing = True
            self.log(f"<-- End of the session: {self.console_patterns.job_status} -->\n")

        super().close()


def str_to_int(string, default):
    try:
        return int(string)
    except Exception:
        return default


class SergentHartman(Process):
    def __init__(self, machine_id, mars_base_url, template_params,
                 boot_loop_counts=100, qualifying_rate=100):
        super().__init__()

        self.machine_id = machine_id
        self.mars_base_url = mars_base_url
        self.template_params = template_params

        self.boot_loop_counts = boot_loop_counts
        self.qualifying_rate = qualifying_rate

        self.statuses = defaultdict(int)

    @property
    def mars_machine_url(self):
        return f"{self.mars_base_url}/api/v1/machine/{self.machine_id}/"

    def run_job(self, job_template):
        try:
            with tempfile.NamedTemporaryFile("w") as f_job, open(job_template, "r") as f_template:
                template_str = f_template.read()

                # Instanciate the template, and write in the temporary file
                template = Template(template_str).render(machine_id=self.machine_id,
                                                         **self.template_params)
                f_job.write(template)
                f_job.flush()

                # Execute the job
                return subprocess.run(["python3", "-m", "executor.client", "-w", "run", f_job.name],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                                    timeout=600).returncode
        except Exception as e:
            traceback.print_exc()
            return JobStatus.SETUP_FAIL.value

    def run(self):
        mid = self.machine_id

        register_template = os.getenv('EXECUTOR_REGISTRATION_JOB', None)
        bootloop_template = os.getenv('EXECUTOR_BOOTLOOP_JOB', None)

        if register_template is None or bootloop_template is None:
            return

        # Start by forcing the machine to register itself to make sure the
        # its configuration is up to date (especially the serial console
        # port). Loop until it succeeds!
        while True:
            print(f"SergentHartman/{mid} - Perform the first registration")

            status = JobStatus(self.run_job(register_template))
            if status != JobStatus.PASS:
                delay = str_to_int(os.getenv("SERGENT_HARTMAN_REGISTRATION_RETRIAL_DELAY", None), 120)
                print(f"SergentHartman/{mid} - First registration failed with status {status.name}. Retrying in {delay} second(s)")
                time.sleep(delay)
            else:
                print(f"SergentHartman/{mid} - Registration succeeded, moving on to the boot loop")
                break

        # Start the qualifying loop
        self.statuses = defaultdict(int)
        for i in range(self.boot_loop_counts):
            status = JobStatus(self.run_job(bootloop_template))
            self.statuses[status] += 1

            statuses_str = [f"{status.name}: {values}" for status, values in self.statuses.items()]
            print(f"SergentHartman/{mid} - loop {i+1}/{self.boot_loop_counts} - statuses {statuses_str}: Execute one more round!")

        # Update MaRS
        ready_for_service = self.statuses[JobStatus.PASS] >= self.qualifying_rate
        params = {
            "ready_for_service": ready_for_service
        }
        r = requests.patch(self.mars_machine_url, json=params)
        r.raise_for_status()

        print(f"SergentHartman/{mid}: Reported to MaRS that the machine is {'' if ready_for_service else 'NOT '}ready for service")

        sys.exit(0 if ready_for_service else 1)


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
        self.sergent_hartman = None

        # Outside -> Inside communication
        self.job_ready = Event()
        self.job_config = None
        self.job_console = None

        self.boots = BootsClient(boots_url=os.getenv('BOOTS_URL', "http://localhost:8087"))

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

    def log(self, msg):
        if self.job_console is not None:
            self.job_console.log(msg)

    def _cache_remote_artifact(self, f_type, start_url, continue_url):
        f_name_base = f"{f_type}-{self.machine_id}"

        if start_url == continue_url:
            self.remote_url_to_local_cache_mapping[start_url] = f"http://10.42.0.1:9000/boot/{f_name_base}"
            self.log(f'Caching {start_url} into minio...\n')
            self.minio_cache.save_boot_artifact(start_url, f_name_base)
        else:
            self.remote_url_to_local_cache_mapping[start_url] = f"http://10.42.0.1:9000/boot/{f_name_base}-start"
            self.remote_url_to_local_cache_mapping[continue_url] = f"http://10.42.0.1:9000/boot/{f_name_base}-continue"
            self.log(f'Caching {start_url} into minio...\n')
            self.minio_cache.save_boot_artifact(start_url, f"{f_name_base}-start")
            self.log(f'Caching {continue_url} into minio...\n')
            self.minio_cache.save_boot_artifact(continue_url, f"{f_name_base}-continue")

    def _cache_remote_artifacts(self):
        deploy_strt = self.job_config.deployment_start
        deploy_cnt = self.job_config.deployment_start

        self._cache_remote_artifact("kernel", deploy_strt.kernel_url,
                                    deploy_cnt.kernel_url)
        self._cache_remote_artifact("initramfs", deploy_strt.initramfs_url,
                                    deploy_cnt.initramfs_url)

    def summon_sergent_hartman(self):
        if self.sergent_hartman is not None:
            if self.sergent_hartman.is_alive():
                # Nothing to do!
                return
            elif self.sergent_hartman.exitcode is not None:
                self.ready_for_service = self.sergent_hartman.exitcode == 0
            else:
                self.sergent_hartman.kill()
            self.sergent_hartman = None

        if self.ready_for_service:
            return

        template_params = {
            "ready_for_service": self.ready_for_service,
            "tags": set(self.tags),
            "local_tty_device": self.local_tty_device,
        }
        boot_loop_counts = str_to_int(os.getenv("SERGENT_HARTMAN_BOOT_COUNT", None), 5)
        qualifying_rate = str_to_int(os.getenv("SERGENT_HARTMAN_QUALIFYING_BOOT_COUNT", None), 5)
        self.sergent_hartman = SergentHartman(machine_id=self.machine_id,
                                                mars_base_url=self.mars_base_url(),
                                                template_params=template_params,
                                                boot_loop_counts=boot_loop_counts,
                                                qualifying_rate=qualifying_rate)
        self.sergent_hartman.start()

    def run(self):
        def session_init():
            # Reset the state
            self.job_config = None
            self.job_console = None

            # Cut the power to the machine, we do not need it
            self.pdu_port.set(PDUState.OFF)

            # Wait for a job to be set
            self.state = MachineState.IDLE
            if not self.job_ready.wait(1):
                return False
            self.job_ready.clear()

            # Mark the start time to now()
            self.job_start_time = datetime.now()

            # Connect to the client's endpoint, to relay the serial console
            self.job_console.start()

            self.state = MachineState.RUNNING

            return True

        def set_boot_config(deployment):
            # Allow the kernel cmdline to reference some machine attributes
            template = Template(deployment.kernel_cmdline)
            kernel_cmdline = template.render(machine_id=self.machine_id,
                                             tags=self.tags,
                                             local_tty_device=self.local_tty_device)

            self.boots.set_config(mac_addr=self.machine_id,
                                  kernel_path=self.remote_url_to_local_cache_mapping.get(deployment.kernel_url),
                                  initramfs_path=self.remote_url_to_local_cache_mapping.get(deployment.initramfs_url),
                                  kernel_cmdline=kernel_cmdline)

        def session_end():
            self.job_config = None

            ## Signal to the job that we reached the end of the execution
            if self.job_console is not None:
                self.job_console.close()
                self.job_console = None

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
                self.log(f"Setting up the boot configuration\n")
                set_boot_config(deployment)
                self.log(f"Power up the machine, enforcing {self.pdu_port.min_off_time} seconds of down time\n")
                self.pdu_port.set(PDUState.ON)

                # Start the boot, and enable the timeouts!
                self.log(f"Boot the machine\n")
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
                    self.log(f"Hit the timeout {timeout} --> {decision}\n")
                    abort = abort or not retry

                # Check if the DUT asked us to reboot
                if self.job_console.needs_reboot:
                    retry = timeouts.boot_cycle.retry()
                    retries_str = f"{timeouts.boot_cycle.retried}/{timeouts.boot_cycle.retries}"
                    decision = f"Boot cycle {retries_str}, go ahead!" if retry else "Exceeded boot loop count, aborting!"
                    self.log(f"The DUT asked us to reboot: {decision}\n")
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

            # If the machine is not ready for service, start a background task
            # that will queue jobs until it gets qualified
            if not self.ready_for_service:
                self.summon_sergent_hartman()

            try:
                if not session_init():
                    continue
                self.log(f"Starting the job: {self.job_config}\n\n")

                execute_job()
            except Exception:
                self.log(f"An exception got caught: {traceback.format_exc()}\n")

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
                                                       m.get('min_off_time', 5))
            machine = cls.update_or_create(m.get("mac_address"),
                                           ready_for_service=m.get('ready_for_service', False),
                                           tags=set(m.get('tags', [])),
                                           pdu_port=pdu_port,
                                           local_tty_device=m.get("local_tty_device"))

            # Remove the machine from the list of local-only machines
            local_only_machines.discard(machine)

        # Delete all the machines that are not found in MaRS, nor have a console
        # associated with them
        for machine in local_only_machines:
            if machine.console is None:
                del self._machines[machine.machine_id]

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
