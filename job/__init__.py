#!/usr/bin/env python3

from enum import Enum
from datetime import datetime, timedelta

import yaml
import re


class Target:
    def __init__(self, target_id:str=None, tags:list[str]=[]):
        self.target_id = target_id
        self.tags = tags

    def __str__(self):
        return f"<Target: id={self.target_id}, tags={self.tags}>"

    @classmethod
    def from_job(cls, data):
        if 'id' not in data and 'tags' not in data:
            raise ValueError("The target is neither identified by tags or id. Use empty tags to mean 'any machines'.")

        return cls(target_id=data.get('id'),
                   tags=data.get('tags', []))

class Timeout:
    def __init__(self, name: str, timeout: timedelta, retries: int) -> None:
        self.name = name
        self.timeout = timeout
        self.retries = retries

        self.started_at = None
        self.retried = 0

    @property
    def has_expired(self):
        return self.started_at is not None and datetime.now() - self.started_at > self.timeout

    def start(self):
        self.started_at = datetime.now()

    def reset(self, when=None):
        if when is None:
            when = datetime.now()
        self.started_at = when

    def retry(self):
        self.stop()
        self.retried += 1

        return self.retried <= self.retries

    def stop(self):
        self.started_at = None

    def __str__(self):
        return f"<Timeout {self.name}: value={self.timeout}, retries={self.retried}/{self.retries}>"

    @classmethod
    def from_job(cls, name, data):
        timeout = timedelta(days=data.get("days", 0),
                            hours=data.get("hours", 0),
                            minutes=data.get("minutes", 0),
                            seconds=data.get("seconds", 0),
                            milliseconds=data.get("milliseconds", 0))
        return cls(name, timeout, data.get("retries", 0))


class Timeouts:
    class Type(Enum):
        OVERALL = "overall"
        INFRA_SETUP = "infra_setup"
        BOOT_CYCLE = "boot_cycle"
        CONSOLE = "console_activity"
        FIRST_CONSOLE_MSG = "first_console_activity"

    def __init__(self, timeouts):
        for t_type in Timeouts.Type:
            timeout = timeouts.get(t_type.value)
            if timeout is None:
                timeout = Timeout(name=t_type.value, timeout=timedelta.max, retries=0)

            # Sanity check the timeout
            if t_type == self.Type.OVERALL and timeout.retries != 0:
                raise ValueError("The overall timeout cannot have retries")

            setattr(self, t_type.value, timeout)

    def __iter__(self):
        for t_type in Timeouts.Type:
            yield getattr(self, t_type.value)

    @property
    def expired_list(self):
        l = []
        for timeout in self:
            if timeout.has_expired:
                l.append(timeout)
        return l

    @property
    def has_expired(self):
        return len(self.expired_list) > 0

    @classmethod
    def from_job(cls, data, defaults={}):
        timeouts = dict(defaults)

        for t_type, t_data  in data.items():
            timeouts[t_type] = Timeout.from_job(t_type, t_data)

        return cls(timeouts)


class ConsoleState:
    def __init__(self, session_end, session_reboot, job_success, job_warn):
        self.session_end = session_end
        self.session_reboot = session_reboot
        self.job_success = job_success
        self.job_warn = job_warn

        self._regexs = {
            "session_end": re.compile(session_end.encode()),
        }

        if session_reboot is not None:
            self._regexs["session_reboot"] = re.compile(session_reboot.encode())

        if job_success is not None:
            self._regexs["job_success"] = re.compile(job_success.encode())

        if job_warn is not None:
            self._regexs["job_warn"] = re.compile(job_warn.encode())

        self._matched = set()

    def process_line(self, line):
        matched = set()
        for name, regex in self._regexs.items():
            if regex.match(line):
                matched.add(name)

        # Extend the list of matched regex
        self._matched.update(matched)

        return matched

    def reset_per_boot_state(self):
        self._matched.discard("session_reboot")

    @property
    def session_has_ended(self):
        return "session_end" in self._matched

    @property
    def needs_reboot(self):
        return "session_reboot" in self._matched

    @property
    def job_status(self):
        if "session_end" not in self._matched:
            return "INCOMPLETE"

        if "job_success" in self._regexs:
            if "job_success" in self._matched:
                if "job_warn" in self._matched:
                    return "WARN"
                else:
                    return "PASS"
            else:
                return "FAIL"
        else:
            return "COMPLETE"

    @classmethod
    def from_job(cls, data):
        session_end = data.get("session_end", {}).get('regex',
                                                      b"^\\[[\d \\.]{12}\\] reboot: Power Down$")
        session_reboot = data.get("session_reboot", {}).get('regex')
        job_success = data.get("job_success", {}).get('regex')
        job_warn = data.get("job_warn", {}).get('regex')

        return cls(session_end=session_end, session_reboot=session_reboot,
                   job_success=job_success, job_warn=job_warn)


class MultiLineString:
    def __init__(self, lines):
        if isinstance(lines, str):
            self.__str = linescontinue
        elif isinstance(lines, list):
            self.__str = " ".join(lines)
        else:
            raise ValueError(f"Unsupported input type '{type(lines)}'")

    def __str__(self):
        return self.__str


class Deployment:
    def __init__(self):
        self.kernel_url = None
        self.initramfs_url = None
        self.kernel_cmdline = None

    def update(self, data):
        kernel_url = data.get("kernel", {}).get("url")
        if kernel_url is not None:
            self.kernel_url = kernel_url

        kernel_cmdline = data.get("kernel", {}).get('cmdline')
        if kernel_cmdline is not None:
            self.kernel_cmdline = str(MultiLineString(kernel_cmdline))

        initramfs_url = data.get("initramfs", {}).get("url")
        if initramfs_url is not None:
            self.initramfs_url = initramfs_url

    def __str__(self):
        return f"""<Deployment:
    kernel_url: {self.kernel_url}
    initramfs_url: {self.initramfs_url}
    kernel_cmdline: {self.kernel_cmdline}>
"""


class Job:
    def __init__(self, job_yml):
        j = yaml.safe_load(job_yml)

        self.version = j.get("version", 1)

        deadline_str = j.get("deadline")
        self.deadline = datetime.fromisoformat(deadline_str) if deadline_str else datetime.max

        self.target = Target.from_job(j.get('target', {}))

        default_timeouts = {
            "overall": Timeout(name="overall", timeout=timedelta(hours=6), retries=0),
        }
        self.timeouts = Timeouts.from_job(j.get('timeouts', {}), defaults=default_timeouts)

        self.console_patterns = ConsoleState.from_job(j.get('console_patterns', {}))

        self.deployment_start = Deployment()
        self.deployment_start.update(j['deployment']['start'])

        # Source the default 'continue' deployment from the start one, then
        # update with the continue one.
        self.deployment_continue = Deployment()
        self.deployment_continue.update(j['deployment']['start'])
        self.deployment_continue.update(j['deployment'].get('continue', {}))

    def __str__(self):
        return f"""<Job:
    version: {self.version}
    deadline: {self.deadline}
    target: {self.target}

    timeouts:
        overall:                {self.timeouts.overall}
        infra_setup:            {self.timeouts.infra_setup}
        boot_cycle:             {self.timeouts.boot_cycle}
        console_activity:       {self.timeouts.console_activity}
        first_console_activity: {self.timeouts.first_console_activity}

    console patterns:
        session_end:    {self.console_patterns.session_end}
        session_reboot: {self.console_patterns.session_reboot}
        job_success:    {self.console_patterns.job_success}
        job_warn:       {self.console_patterns.job_warn}

    start deployment:
        kernel_url:     {self.deployment_start.kernel_url}
        initramfs_url:  {self.deployment_start.initramfs_url}
        kernel_cmdline: {self.deployment_start.kernel_cmdline}

    continue deployment:
        kernel_url:     {self.deployment_continue.kernel_url}
        initramfs_url:  {self.deployment_continue.initramfs_url}
        kernel_cmdline: {self.deployment_continue.kernel_cmdline}>"""
