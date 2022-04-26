from enum import Enum
from datetime import datetime, timedelta
from marshmallow import Schema, fields, post_load
from marshmallow.exceptions import ValidationError
from jinja2 import Template
import yaml
import re

from . import config


class Target:
    class Schema(Schema):
        id = fields.Str()
        tags = fields.List(fields.Str())

        @post_load
        def make(self, data, **kwargs):
            if 'id' not in data and 'tags' not in data:
                raise ValueError("The target is neither identified by tags or id. "
                                 "Use empty tags to mean 'any machines'.")

            return Target(**data)

    def __init__(self, id: str = None, tags: list[str] = None):
        self.id = id
        self.tags = tags if tags is not None else []

    def __str__(self):
        return f"<Target: id={self.id}, tags={self.tags}>"

    @classmethod
    def from_job(cls, data):

        schema = cls.Schema()
        return schema.load(data)


class Timeout:
    class Schema(Schema):
        days = fields.Float(missing=0)
        hours = fields.Float(missing=0)
        minutes = fields.Float(missing=0)
        seconds = fields.Float(missing=0)
        milliseconds = fields.Float(missing=0)
        retries = fields.Int(strict=True, missing=0)

        @post_load
        def make(self, data, **kwargs):
            timeout = timedelta(days=data.get("days", 0),
                                hours=data.get("hours", 0),
                                minutes=data.get("minutes", 0),
                                seconds=data.get("seconds", 0),
                                milliseconds=data.get("milliseconds", 0))
            return Timeout(self.context.get('name'), timeout=timeout, retries=data.get('retries'))

    def __init__(self, name: str, timeout: timedelta, retries: int) -> None:
        self.name = name
        self.timeout = timeout
        self.retries = retries

        self.started_at = None
        self.retried = 0

    @property
    def active_for(self):
        if self.started_at is not None:
            return datetime.now() - self.started_at
        else:
            return None

    @property
    def is_started(self):
        return self.started_at is not None

    @property
    def has_expired(self):
        active_for = self.active_for
        return active_for is not None and active_for > self.timeout

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
        schema = Timeout.Schema(context={"name": name})
        return schema.load(data)


class Timeouts:
    class Type(Enum):
        OVERALL = "overall"
        INFRA_SETUP = "infra_setup"
        INFRA_TEARDOWN = "infra_teardown"
        BOOT_CYCLE = "boot_cycle"
        CONSOLE = "console_activity"
        FIRST_CONSOLE_MSG = "first_console_activity"

    class Schema(Schema):
        overall = fields.Nested(Timeout.Schema(context={"name": "overall"}))
        infra_setup = fields.Nested(Timeout.Schema(context={"name": "infra_setup"}))
        infra_teardown = fields.Nested(Timeout.Schema(context={"name": "infra_teardown"}))
        boot_cycle = fields.Nested(Timeout.Schema(context={"name": "boot_cycle"}))
        console_activity = fields.Nested(Timeout.Schema(context={"name": "console_activity"}))
        first_console_activity = fields.Nested(Timeout.Schema(context={"name": "first_console_activity"}))
        watchdogs = fields.Dict(keys=fields.Str(), values=fields.Nested(Timeout.Schema()))

        @post_load
        def make(self, data, **kwargs):
            timeouts = dict(self.context.get('default_timeouts'))
            for t_type, t_data in data.items():
                timeouts[t_type] = t_data

            watchdogs = data.get("watchdogs", {})
            for name, wd in watchdogs.items():
                watchdogs[name].name = name

            return Timeouts(timeouts, watchdogs=data.get("watchdogs"))

    def __init__(self, timeouts, watchdogs=None):
        for t_type in Timeouts.Type:
            timeout = timeouts.get(t_type.value)
            if timeout is None:
                timeout = Timeout(name=t_type.value, timeout=timedelta.max, retries=0)

            # Sanity check the timeout
            if t_type in [self.Type.OVERALL, self.Type.INFRA_TEARDOWN] and timeout.retries != 0:
                raise ValueError("Neither the overall nor the teardown timeout can have retries")

            setattr(self, t_type.value, timeout)

        if watchdogs is None:
            watchdogs = {}
        self.watchdogs = watchdogs

    def __iter__(self):
        for t_type in Timeouts.Type:
            yield getattr(self, t_type.value)

        for wd in self.watchdogs.values():
            yield wd

    @property
    def expired_list(self):
        expired = []
        for timeout in self:
            if timeout.has_expired:
                expired.append(timeout)
        return expired

    @property
    def has_expired(self):
        return len(self.expired_list) > 0

    @classmethod
    def from_job(cls, data, defaults=None):
        schema = cls.Schema(context={"default_timeouts": defaults if defaults is not None else {}})
        return schema.load(data)


class Pattern:
    class Schema(Schema):
        regex = fields.Str()

        @post_load
        def make(self, data, **kwargs):
            if regex := data.get('regex', None):
                return Pattern(regex)

            raise ValueError("Console patterns require the 'regex' attribute")

    def __init__(self, regex):
        try:
            self.regex = re.compile(regex.encode())
        except re.error as e:
            raise ValueError(f"Console pattern '{regex}' is not a valid regular expression: {e.msg}")

    def __str__(self):
        return f"{self.regex.pattern}"

    @classmethod
    def from_job(cls, data):
        schema = cls.Schema()
        return schema.load(data)


class Watchdog(Schema):
    class Schema(Schema):
        start = fields.Nested(Pattern.Schema())
        reset = fields.Nested(Pattern.Schema())
        stop = fields.Nested(Pattern.Schema())

        @post_load
        def make(self, data, **kwargs):
            for field in ["start", "reset", "stop"]:
                if field not in data or data.get(field) is None:
                    raise ValueError("The fields start, reset, and stop need to be specified for watchdogs")

            return Watchdog(**data)

    def __init__(self, start, reset, stop):
        self.start_pattern = start
        self.reset_pattern = reset
        self.stop_pattern = stop

        self.timeout = None

    def set_timeout(self, timeout):
        self.timeout = timeout

    def process_line(self, line):
        # Do not parse lines if no timeout is associated
        if self.timeout is None:
            return {}

        if not self.timeout.is_started:
            if self.start_pattern.regex.search(line):
                self.timeout.start()
                return {"start"}
        else:
            if self.reset_pattern.regex.search(line):
                self.timeout.reset()
                return {"reset"}
            elif self.stop_pattern.regex.search(line):
                self.timeout.stop()
                return {"stop"}

        return {}

    def stop(self):
        if self.timeout is not None:
            self.timeout.stop()

    @classmethod
    def from_job(cls, data):
        schema = cls.Schema()
        return schema.load(data)


class ConsoleState:
    class Schema(Schema):
        session_end = fields.Nested(Pattern.Schema(), missing=None)
        session_reboot = fields.Nested(Pattern.Schema(), missing=None)
        job_success = fields.Nested(Pattern.Schema(), missing=None)
        job_warn = fields.Nested(Pattern.Schema(), missing=None)
        machine_unfit_for_service = fields.Nested(Pattern.Schema(), missing=None)
        watchdogs = fields.Dict(keys=fields.Str(), values=fields.Nested(Watchdog.Schema()), missing=None)

        @post_load
        def make(self, data, **kwargs):
            default_patterns = {
                "session_end": Pattern("^\\[[\\d \\.]{12}\\] reboot: Power Down$"),
                "session_reboot": None,
                "job_success": None,
                "job_warn": None,
                "machine_unfit_for_service": None,
            }

            # Use the default patterns, if not set
            for name in default_patterns:
                if data.get(name) is None:
                    data[name] = default_patterns[name]

            return ConsoleState(**data)

    def __init__(self, session_end, session_reboot, job_success, job_warn, machine_unfit_for_service,
                 watchdogs=None):
        self.session_end = session_end
        self.session_reboot = session_reboot
        self.job_success = job_success
        self.job_warn = job_warn
        self.machine_unfit_for_service = machine_unfit_for_service
        self.watchdogs = {} if watchdogs is None else watchdogs

        self._patterns = {
            "session_end": session_end.regex,
        }

        if session_reboot is not None:
            self._patterns["session_reboot"] = session_reboot.regex

        if job_success is not None:
            self._patterns["job_success"] = job_success.regex

        if job_warn is not None:
            self._patterns["job_warn"] = job_warn.regex

        if machine_unfit_for_service is not None:
            self._patterns["machine_unfit_for_service"] = machine_unfit_for_service.regex

        self._matched = set()

    def process_line(self, line):
        # Try matching all the patterns
        matched = set()
        for name, regex in self._patterns.items():
            if regex.search(line):
                matched.add(name)
        self._matched.update(matched)

        # Try matching the watchdogs
        for name, wd in self.watchdogs.items():
            _matched = wd.process_line(line)
            matched.update({f"{name}.{m}" for m in _matched})

        return matched

    def reset_per_boot_state(self):
        self._matched.discard("session_reboot")

    @property
    def session_has_ended(self):
        return "session_end" in self._matched or "unfit_for_service" in self._matched

    @property
    def needs_reboot(self):
        return "session_reboot" in self._matched

    @property
    def machine_is_unfit_for_service(self):
        return "machine_unfit_for_service" in self._matched

    @property
    def job_status(self):
        if "session_end" not in self._matched:
            return "INCOMPLETE"

        if "job_success" in self._patterns:
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
        schema = cls.Schema()
        return schema.load(data)


def _multiline_string(lines):
    if isinstance(lines, str):
        return lines
    elif isinstance(lines, list):
        return " ".join(lines)
    else:
        assert False


class Deployment:
    def __init__(self, kernel_url=None, initramfs_url=None, kernel_cmdline=None):
        self.kernel_url = kernel_url
        self.kernel_cmdline = kernel_url
        self.initramfs_url = initramfs_url

    def update(self, data):
        if (kernel_url := data.get('kernel', {}).get('url')) is not None:
            self.kernel_url = kernel_url

        if (kernel_cmdline := data.get('kernel', {}).get('cmdline')) is not None:
            self.kernel_cmdline = kernel_cmdline

        if (initramfs_url := data.get('initramfs', {}).get('url')) is not None:
            self.initramfs_url = initramfs_url

    def __str__(self):
        return f"""<Deployment:
    kernel_url: {self.kernel_url}
    initramfs_url: {self.initramfs_url}
    kernel_cmdline: {self.kernel_cmdline}>
"""


class Job:
    class Schema(Schema):
        class DeploymentsSchema(Schema):
            class DeploymentSchema(Schema):
                class KernelSchema(Schema):
                    url = fields.Str()
                    cmdline = fields.Method("get_cmdline", deserialize="load_cmdline")

                    def get_cmdline(self, obj):  # pragma: nocover
                        return obj.kernel_cmdline

                    def load_cmdline(self, value):
                        return _multiline_string(value)

                class InitramfsSchema(Schema):
                    url = fields.Str()

                kernel = fields.Nested(KernelSchema())
                initramfs = fields.Nested(InitramfsSchema())

            start = fields.Nested(DeploymentSchema(), required=True)
            cont = fields.Nested(DeploymentSchema(), data_key="continue", attribute="continue")

        version = fields.Int(strict=True, missing=1)
        deadline = fields.DateTime(missing=datetime.max)
        target = fields.Nested(Target.Schema(), missing=Target())
        timeouts = fields.Nested(Timeouts.Schema(), missing=None)
        console_patterns = fields.Nested(ConsoleState.Schema(), required=True)
        deployment = fields.Nested(DeploymentsSchema(), required=True)

        @post_load
        def make(self, data, **kwargs):
            # Timeouts
            if data.get('timeouts') is None:
                data['timeouts'] = Timeouts(self.context.get('default_timeouts'))

            # Deployments
            deployment = data.pop('deployment', {})

            deployment_start = Deployment()
            deployment_start.update(deployment['start'])
            data['deployment_start'] = deployment_start

            # Source the default 'continue' deployment from the start one, then
            # update with the continue one.
            deployment_continue = Deployment()
            deployment_continue.update(deployment['start'])
            deployment_continue.update(deployment.get('continue', {}))
            data['deployment_continue'] = deployment_continue

            data['bucket'] = self.context.get('bucket')

            job = Job(**data)

            # Associate all the timeouts to their respective watchdogs
            for name, wd in job.console_patterns.watchdogs.items():
                wd.set_timeout(job.timeouts.watchdogs.get(name))

            return job

    def __init__(self, version, deadline, target, timeouts, console_patterns, deployment_start,
                 deployment_continue, bucket=None):
        self.version = version
        self.deadline = deadline
        self.target = target
        self.timeouts = timeouts
        self.console_patterns = console_patterns
        self.deployment_start = deployment_start
        self.deployment_continue = deployment_continue

    @classmethod
    def from_job(cls, job_yml, bucket=None):
        j = yaml.safe_load(job_yml)

        default_timeouts = {
            "overall": Timeout(name="overall", timeout=timedelta(hours=6), retries=0),
            "infra_teardown": Timeout(name="infra_teardown", timeout=timedelta(minutes=10), retries=0),
        }

        try:
            schema = cls.Schema(context={
                'default_timeouts': default_timeouts,
                'bucket': bucket,
            })
            return schema.load(j)
        except ValidationError as e:
            raise ValueError(str(e))

    @classmethod
    def render_with_resources(cls, job_str, machine, bucket=None):
        template_params = {
            "ready_for_service": machine.ready_for_service,
            "machine_id": machine.id,
            "machine": machine.safe_attributes,
            "machine_tags": machine.tags,
            "local_tty_device": machine.local_tty_device,
            **{k.lower(): v for k, v in config.job_environment_vars().items()},
        }

        if bucket:
            dut_creds = bucket.credentials('dut')

            template_params["minio_url"] = bucket.minio.url
            template_params["job_bucket"] = bucket.name
            template_params["job_bucket_access_key"] = dut_creds.username
            template_params["job_bucket_secret_key"] = dut_creds.password

        rendered_job_str = Template(job_str).render(**template_params)
        return cls.from_job(rendered_job_str)

    @classmethod
    def from_path(cls, job_template_path, machine, bucket=None):
        with open(job_template_path, "r") as f_template:
            template_str = f_template.read()
            return Job.render_with_resources(template_str, machine, bucket)

    def __str__(self):
        if len(self.timeouts.watchdogs) == 0:
            timeout_watchdogs = "None"
        else:
            timeout_watchdogs = ""
            for name, wd in self.timeouts.watchdogs.items():
                timeout_watchdogs += f"\n            {name}: {wd}"

        if len(self.console_patterns.watchdogs) == 0:
            patterns_watchdogs = "None"
        else:
            patterns_watchdogs = ""
            for name, wd in self.console_patterns.watchdogs.items():
                patterns_watchdogs += f"\n            {name}:"
                patterns_watchdogs += f"\n                start: {wd.start_pattern}"
                patterns_watchdogs += f"\n                reset: {wd.reset_pattern}"
                patterns_watchdogs += f"\n                stop:  {wd.stop_pattern}"

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
        watchdogs:              {timeout_watchdogs}

    console patterns:
        session_end:               {self.console_patterns.session_end}
        session_reboot:            {self.console_patterns.session_reboot}
        job_success:               {self.console_patterns.job_success}
        job_warn:                  {self.console_patterns.job_warn}
        machine_unfit_for_service: {self.console_patterns.machine_unfit_for_service}
        watchdogs:              {patterns_watchdogs}

    start deployment:
        kernel_url:     {self.deployment_start.kernel_url}
        initramfs_url:  {self.deployment_start.initramfs_url}
        kernel_cmdline: {self.deployment_start.kernel_cmdline}

    continue deployment:
        kernel_url:     {self.deployment_continue.kernel_url}
        initramfs_url:  {self.deployment_continue.initramfs_url}
        kernel_cmdline: {self.deployment_continue.kernel_cmdline}>"""
