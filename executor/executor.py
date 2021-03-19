#!/usr/bin/env python3

from datetime import datetime, timedelta
from threading import Thread, Event
from enum import Enum
from salad import salad, JobSession
from pdu import PDU, PDUState
from bootsclient import BootsClient

import traceback
import requests
import socket
import time
import yaml
import os


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


class Machine(Thread):
    _machines = dict()

    def __init__(self, machine_id, ready_for_service=False, tags=[], pdu_port=None,
                 local_tty_device=None):
        super().__init__()

        # Machine
        self.machine_id = machine_id
        self.pdu_port = pdu_port
        self.state = MachineState.WAIT_FOR_CONFIG
        self.ready_for_service = ready_for_service
        self.tags = set(tags)
        self.local_tty_device = local_tty_device

        # Outside -> Inside communication
        self.job_ready = Event()
        self.job_config = None
        self.job_console = None

        # Boots
        self.boots = BootsClient(boots_url=os.getenv('BOOTS_URL', "http://localhost:8087"))
        self._boots_url_to_name = {}

        # Add the machine to the list of machines
        self._machines[self.machine_id] = self

        # Start the background thread that will manage the machine
        self.stop_event = Event()
        self.start()

    def __del__(self):
        try:  # pragma: nocover
            del self._machines[self.machine_id]
        except Exception as e:
            print(e)

    @property
    def ready_for_jobs(self):
        return self.pdu_port is not None

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

    def _boots_download_target(self, f_type, start_url, continue_url):
        f_name_base = f"{f_type}-{self.machine_id}"

        if start_url == continue_url:
            self._boots_url_to_name[start_url] = f_name_base
            return [self.boots.download_kernel(name=f_name_base, url=start_url)]
        else:
            self._boots_url_to_name[start_url] = f"{f_name_base}-start"
            self._boots_url_to_name[continue_url] = f"{f_name_base}-continue"

            return [self.boots.download_kernel(name=self._boots_url_to_name[start_url], url=start_url),
                    self.boots.download_kernel(name=self._boots_url_to_name[continue_url], url=continue_url)]

    def _prepare_report_progress(self, task_count, pending_tasks):
        task_completed = task_count - len(pending_tasks)
        tasks_str = ", ".join([str(t) for t in pending_tasks])
        remaining_str = "" if task_completed == task_count else f" Remaining tasks: {tasks_str}"
        self.log(f"[{task_completed}/{task_count}] downloads completed.{remaining_str}\n")

    def _boots_prepare(self):
        pending_tasks = []

        deploy_strt = self.job_config.deployment_start
        deploy_cnt = self.job_config.deployment_start
        pending_tasks.extend(self._boots_download_target("kernel", deploy_strt.kernel_url,
                                                         deploy_cnt.kernel_url))
        pending_tasks.extend(self._boots_download_target("initramfs", deploy_strt.initramfs_url,
                                                         deploy_cnt.initramfs_url))

        task_count = len(pending_tasks)
        self._prepare_report_progress(task_count, pending_tasks)
        while len(pending_tasks) > 0:
            time.sleep(0.1)

            for task in list(pending_tasks):
                task.update()
                if task.is_finished:
                    pending_tasks.remove(task)
                    self._prepare_report_progress(task_count, pending_tasks)

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
            self._boots_prepare()
            timeouts.infra_setup.stop()

            # Keep on resuming until success, timeouts' retry limits is hit, or the entire executor is going down
            deployment = self.job_config.deployment_start
            while not self.stop_event.is_set() and not timeouts.overall.has_expired and not self.job_console.is_over:
                self.job_console.reset_per_boot_state()

                # Make sure the machine shuts down
                self.pdu_port.set(PDUState.OFF)

                # Set up the deployment
                self.log(f"Setting up the boot configuration\n")
                self.boots.set_config(mac_addr=self.machine_id,
                              kernel_path=self._boots_url_to_name.get(deployment.kernel_url),
                              initramfs_path=self._boots_url_to_name.get(deployment.initramfs_url),
                              kernel_cmdline=deployment.kernel_cmdline)

                self.log(f"Power up the machine, enforcing {self.pdu_port.delay} seconds of down time\n")
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
            # Wait until the machine is ready for jobs
            if not self.ready_for_jobs:
                time.sleep(1)
                continue

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
        def get_PDU_or_create_from_MaRS_URL(mars_pdu_url, pdu_port):
            pdu = pdus.get(mars_pdu_url)
            if pdu is None:
                r = requests.get(mars_pdu_url)
                r.raise_for_status()

                p = r.json()
                pdu = PDU.create(p.get('pdu_model'), p.get('name'), p.get('config', {}))

            for port in pdu.ports:
                if str(port.port_id) == str(pdu_port):
                    return port

            return None

        pdus = dict()

        mars_base_url = os.getenv('MARS_URL', "http://127.0.0.1")
        r = requests.get(f"{mars_base_url}/api/v1/machine/")
        r.raise_for_status()

        local_only_machines = set(cls.known_machines())
        for m in r.json():
            # Ignore retired machines
            if m.get('is_retired', False):
                continue

            pdu_port = get_PDU_or_create_from_MaRS_URL(m.get('pdu'), m.get('pdu_port_id'))
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
               return None, f"Unknown machine with ID {target.target_id}"
            elif not wanted_tags.issubset(machine.tags):
                return None, f"The machine {target.target_id} does not matching tags (asked: {wanted_tags}, actual: {machine.tags})"
            elif machine.state != MachineState.IDLE:
                return None, f"The machine {target.target_id} is unavailable: Current state is {machine.state.name}"
            return machine, None
        else:
            for machine in cls.known_machines():
                if not wanted_tags.issubset(machine.tags):
                    continue

                if machine.state == MachineState.IDLE:
                    return machine, "success"

        return None, f"No available machines found matching the tags {wanted_tags}"

    @classmethod
    def shutdown_all_workers(cls):
        machines = cls.known_machines()

        # Signal all the workers we want to stop
        for machine in machines:
            machine.stop_event.set()

        # Wait for all the workers to stop
        for machine in machines:
            machine.join()
