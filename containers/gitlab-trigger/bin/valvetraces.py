#!/usr/bin/env -S python3 -u

try:
    from functools import cached_property
except Exception:
    from backports.cached_property import cached_property
from dataclasses import dataclass
from multiprocessing import Pool
from typing import List
import datetime
import base64
import hashlib
import humanize
from functools import partial
import json
import os
import io
import re
import traceback
import requests
import argparse
import sys
import shutil
import minio
from pathlib import Path
import subprocess
from urllib.parse import urlparse
import fnmatch
import operator
import xml.sax.saxutils

from enum import Enum
from PIL import Image

naturalsize = partial(humanize.naturalsize, binary=True)
ensure_dir = partial(os.makedirs, exist_ok=True)


class SanitizedFieldsMixin:
    @classmethod
    def from_api(cls, fields, **kwargs):
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}

        sanitized_kwargs = dict(fields)
        for arg in fields:
            if arg not in valid_fields:
                sanitized_kwargs.pop(arg)

        return cls(**sanitized_kwargs, **kwargs)


@dataclass
class App(SanitizedFieldsMixin):
    id: int
    name: str
    steamappid: str

    def matches(self, app_id):
        return str(self.id) == app_id or str(self.name) == app_id or str(self.steamappid) == app_id

    def __str__(self):
        return f"<App: ID={self.id}, SteamID={self.steamappid}, name={self.name}>"


class BlobType(Enum):
    UNKNOWN = 0
    TRACE = 1
    FRAME = 2

    @staticmethod
    def from_str(label):
        if label is None:
            return BlobType.UNKNOWN

        lowered = label.lower()
        if lowered == 'trace':
            return BlobType.TRACE
        elif lowered == 'frameoutput':
            return BlobType.FRAME
        else:
            return BlobType.UNKNOWN


class Blob:
    def __init__(self, blob_dict, new=True):
        self.new = new
        direct_upload = blob_dict.get("direct_upload")
        if direct_upload is not None:
            self.url = direct_upload.get('url')
            if self.url is None:
                raise ValueError("The URL is missing from the 'direct_upload' dict")

            self.headers = direct_upload.get('headers')
            if self.headers is None:
                raise ValueError("The headers are missing from the 'direct_upload' dict")

        self.signed_id = blob_dict.get("signed_id")
        if self.signed_id is None:
            raise ValueError("The signed_id is missing from the blob-creation response")

        self.record_type = BlobType.from_str(blob_dict.get("record_type"))

        if not self.new and self.record_type != BlobType.UNKNOWN:
            self.record = blob_dict.get("record")

    def upload(self, f):
        r = requests.put(self.url, headers=self.headers, data=f)
        r.raise_for_status()


@dataclass
class Trace(SanitizedFieldsMixin):
    id: int
    filename: str
    metadata: dict
    obsolete: bool
    frames_to_capture: dict
    url: str
    file_size: int

    @property
    def size(self):
        return self.file_size

    @property
    def machine_tags(self):
        try:
            return list(self.metadata.get("machine_tags", []))
        except Exception as e:
            print(e)
            return []

    # TODO: Work on making the traces API do server-side filtering of
    # the metadata. This seems a better interface than pulling all the
    # metadata only to discard potentially a good proportion of it
    # client-side.
    def matches_tags(self, tags, debug=False):
        machine_tags = self.machine_tags

        for wanted_tag in tags:
            found = False
            for machine_tag in machine_tags:
                if wanted_tag.match(machine_tag):
                    if debug:
                        print(f"The wanted tag {wanted_tag} matched the machine tag {machine_tag}")
                    found = True
                    break

            if found:
                continue

            if debug:
                print(f"The wanted tag {wanted_tag} was not matched")
            return False

        return True

    @property
    def human_size(self):
        return naturalsize(self.file_size)

    def __str__(self):
        return f"<Trace {self.id}, {self.filename}, size {self.human_size}>"


class Client:
    def __init__(self, url, username=None):
        self.url = url
        self.username = username

        self._login_cookie = None

    def login(self):
        if self._login_cookie is None:
            password = os.environ.get("VALVETRACESPASSWORD", None)
            if self.username is None or password is None:
                print("ERROR: credentials not specified for valve traces client")
                sys.exit(1)

            r = requests.post(f"{self.url}/api/v1/login", allow_redirects=False,
                              json={"user": {"username": self.username, "password": password}})
            r.raise_for_status()

            self._login_cookie = r.cookies

        return self._login_cookie

    def _get(self, path):
        headers = {'Content-type': 'application/json'}
        r = requests.get(f"{self.url}{path}", allow_redirects=False, cookies=self.login(), headers=headers)
        r.raise_for_status()

        return r.json()

    def _post(self, path, params):
        r = requests.post(f"{self.url}{path}", allow_redirects=False, cookies=self.login(), json=params)

        if r.status_code == 500:
            print(f"Got an error: url={self.url}{path}, params={params}, ret={r.text}")
        elif r.status_code == 409:
            # TODO: Add an option to ignore some errors
            return r.json()

        r.raise_for_status()

        return r.json()

    def list_apps(self):
        apps = list()
        for game in self._get("/api/v1/games"):
            apps.append(App.from_api(game))

        return apps

    def create_app(self, name, steamappid=None):
        for app in self.list_apps():
            if app.name == name and app.steamappid == steamappid:
                raise ValueError(f"The app named '{name}' already exists: {app}")

        r = self._post("/api/v1/games", {"game": {"name": name, "appid": steamappid}})

        return App.from_api(r)

    def list_traces(self, filter_machine_tags):
        tags = [re.compile(t) for t in filter_machine_tags]

        traces = list()
        for trace_blob in self._get("/api/v1/traces"):
            trace = Trace.from_api(trace_blob)

            if trace.matches_tags(tags):
                traces.append(trace)

        return traces

    def get_trace(self, trace_name):
        for trace in self.list_traces([]):
            if trace.filename == trace_name:
                return trace

        raise ValueError(f"Could not find a trace named '{trace_name}' in the service")

    def download_trace(self, trace_name, output_folder):
        trace = self.get_trace(trace_name)

        trace_path = os.path.join(output_folder, trace_name)
        with open(trace_path, 'wb') as f:
            with requests.get(trace.url, stream=True) as r:
                r.raise_for_status()
                content_length = int(r.headers.get('content-length', 0))
                print('Downloading {} of size {}'.format(
                    trace_name,
                    naturalsize(content_length) if content_length > 0 else 'Unknown'))
                total_downloaded = 0
                previous_pc_downloaded = 0
                chunk_size = 1024 * 1024
                # Reading all the available data without limiting the
                # chunk size is problematic when using SSL
                # connections. Limit the chunk size:
                # https://bugs.python.org/issue42853
                for chunk in r.iter_content(chunk_size=chunk_size):
                    f.write(chunk)
                    if content_length == 0:
                        # This shouldn't happen, since the Mango
                        # server returns Content-Length, no progress
                        # info if we don't get a length back from the
                        # server
                        continue
                    total_downloaded += len(chunk)
                    pc_downloaded = int(100.0 * total_downloaded/content_length)
                    # Log roughly every 2% downloaded, or end of stream.
                    if pc_downloaded - previous_pc_downloaded >= 2 or len(chunk) < chunk_size:
                        sys.stdout.write('\rDownloaded {}/{} {:0.2f}%'.format(naturalsize(total_downloaded),
                                                                              naturalsize(content_length),
                                                                              pc_downloaded))
                        sys.stdout.flush()
                        previous_pc_downloaded = pc_downloaded
                sys.stdout.write('\n')
                sys.stdout.flush()
        return trace_path

    def _find_app(self, app_id):
        app_id = str(app_id)

        suitable_apps = []
        for app in self.list_apps():
            if app.matches(app_id):
                suitable_apps.append(app)

        if len(suitable_apps) == 1:
            return suitable_apps[0]
        elif len(suitable_apps) == 0:
            raise ValueError(f"Could not find an app named '{app_id}'")
        else:
            raise ValueError(f"Found more than one application matching the app_id '{app_id}': {suitable_apps}")

    def _data_checksum(self, filepath):
        hash_md5 = hashlib.md5()
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)

            return base64.b64encode(hash_md5.digest()).decode()

    def _upload_blob(self, filepath, name, data_checksum, image_checksum=None):
        with open(filepath, "rb") as f:
            # Check the file size
            f.seek(0, os.SEEK_END)
            file_size = f.tell()
            f.seek(0, os.SEEK_SET)

            # Ask the website for the URL of where to upload the file
            r_blob = self._post("/rails/active_storage/direct_uploads",
                                {"blob": {"filename": name, "byte_size": file_size,
                                          "content_type": "application/octet-stream",
                                          "checksum": data_checksum,
                                          "image_checksum": image_checksum}})
            blob = Blob(r_blob)

            # Send the file to the bucket
            blob.upload(f)

            return blob

    def _upload_trace_blob(self, filepath, name):
        # Generate the MD5 hash for the bucket
        data_checksum = self._data_checksum(filepath)
        # Check if file already exists on server
        r = self._post("/api/v1/checksum", {"checksum": data_checksum})
        if "accepted" not in r:
            return Blob(r, new=False)

        return self._upload_blob(filepath, name, data_checksum)

    def upload_trace(self, app_id, filepath, frame_ids, machine_tags):
        if not machine_tags:
            confirmation_message = ('I confirm the trace is uploaded from '
                                    'the same computer that produced the trace')
            machine_tags = list(self.machine_tags)
        else:
            confirmation_message = ('I confirm the machine tags provided are '
                                    'the ones produced at the same computer '
                                    'that produced the trace to be uploaded')

        app = self._find_app(app_id)
        trace_name = os.path.basename(filepath)

        print(f"""\nWARNING: You are about to upload a trace, please check that the following values are valid:

    Application/Game: {str(app)}
    Trace name: {trace_name}
    IDs of frames to capture: {frame_ids}
    Machine tags: {machine_tags}
""")
        if input(f'{confirmation_message} (y/N)'.format()).lower() != 'y':
            return

        # Upload the blob
        blob = self._upload_trace_blob(filepath, trace_name)
        if blob.record_type != BlobType.TRACE:
            raise ValueError(f'Expected a {BlobType.TRACE} in the blob, '
                             f'gotten {blob.record_type}')
        if not blob.new:
            print('Trace already exists in the server. Skipping upload.')
            return Trace.from_api(blob.record)

        # Create the trace from the blob
        r = self._post("/api/v1/traces/",
                       params={"trace": {"upload": blob.signed_id, "game_id": app.id,
                                         "metadata": {"machine_tags": machine_tags},
                                         "frames_to_capture": frame_ids}})

        return Trace.from_api(r)

    def _upload_frame_blob(self, filepath, name):
        image_md5 = hashlib.md5(Image.open(filepath).convert(mode="RGBA").tobytes())
        img_checksum = base64.b64encode(image_md5.digest()).decode()

        # Check if frame already exists on server
        r = self._post("/api/v1/image_checksum", {"checksum": img_checksum})
        if "id" in r:
            return Blob(r, new=False)

        # Generate the MD5 hash for the bucket
        data_checksum = self._data_checksum(filepath)

        return self._upload_blob(filepath, name, data_checksum,
                                 image_checksum=img_checksum)

    def job_get_or_create(self, name, metadata=None, timeline_metadata=None, is_released_code=False):
        # The object will be created if it does not exist already,
        # otherwise, it will return the job that has the same name
        params = {
            "job": {
                "name": name,
                "metadata": metadata,
                "timeline_metadata": timeline_metadata,
                "is_released_code": is_released_code
            }
        }
        job = self._post("/api/v1/jobs", params=params)
        return Job.from_api(job, client=self)


@dataclass
class Job(SanitizedFieldsMixin):
    client: Client
    id: int
    name: str
    metadata: dict

    def report_trace_execution(self, trace, frame_blobs, metadata=None, status=None, logs_path=None):
        # Create the trace execution
        params = {
            "trace_exec": {
                "job_id": self.id,
                "trace_id": trace.id,
                "metadata": metadata,
                "status": status,
                "logs": None,  # TODO: Needs work!
            },
            "frame_blobs": frame_blobs,
            # TODO: Set the GPU PCI ID
        }
        r = self.client._post("/api/v1/trace_execs", params=params)
        return r.get('id')


def job_id():
    if 'CI_JOB_ID' in os.environ:
        # Be very careful not to pass a plain number as the job ID, everything explodes!
        return f'job-{os.environ["CI_JOB_ID"]}'
    return 'untitled'


def generate_junit_report(job_folder_path):
    def escape_for_report(s):
        # kinda kills escape codes, but makes xmllint happier
        escape_translator = s.maketrans('', '', '\x1b')
        return xml.sax.saxutils.escape(s.translate(escape_translator))

    #  https://www.ibm.com/docs/en/adfz/developer-for-zos/14.1.0?topic=formats-junit-xml-format
    @dataclass
    class TestSuite:
        id: str
        name: str
        tests: int
        failures: int
        time: float

    @dataclass
    class Failure:
        message: str
        detail: str
        type: str

    @dataclass
    class TestCase:
        id: str
        name: str
        return_code: str = "MISSING"
        runtime_seconds: float = 0
        screenshot_filenames: List[str] = dataclass.field(default_factory=list)
        failures: List[Failure] = dataclass.field(default_factory=list)

    testcases = []
    for root, dirs, files in os.walk(job_folder_path):
        if root == job_folder_path:
            continue

        tracename = os.path.basename(root)

        start_time, end_time, retcode = None, None, None

        testcase = TestCase(id=root, name=tracename)

        testcase.screenshot_filenames.extend([os.path.join(root, f) for f in fnmatch.filter(files, "*.png")])
        testcase.screenshot_filenames.extend([os.path.join(root, f) for f in fnmatch.filter(files, "*.bmp")])

        def paste_log_as_failure(failure_type):
            trace_log_path = os.path.join(root, f"{tracename}.log")
            if os.path.exists(trace_log_path):
                with open(trace_log_path, "r") as f:
                    return Failure(message="Job failed to complete", detail=f.read(), type=failure_type)
            else:
                return Failure(message="Job failed to complete", detail="No log available", type=failure_type)

        if '.started' in files and '.done' not in files:
            testcase.failures.append(paste_log_as_failure('DID_NOT_COMPLETE'))
        elif len(testcase.screenshot_filenames) == 0:
            testcase.failures.append(paste_log_as_failure('NO_FRAMES'))

        if '.started' in files and '.done' in files:
            with open(os.path.join(root, '.started'), 'r') as f:
                lines = f.readlines()
                start_time = datetime.datetime.strptime(lines[0].strip(), "%Y-%m-%d %H:%M:%S")

            with open(os.path.join(root, '.done'), 'r') as f:
                lines = f.readlines()
                end_time = datetime.datetime.strptime(lines[0].strip(), "%Y-%m-%d %H:%M:%S")
                retcode = lines[1].strip()

            testcase.runtime_seconds = (end_time - start_time).total_seconds()
            testcase.return_code = retcode

        testcases.append(testcase)

    ntests = len(testcases)
    nfails = sum(len(tc.failures) for tc in testcases)
    total_time = sum(tc.runtime_seconds for tc in testcases)

    junit_report = io.StringIO()
    junit_report.write(f"""<?xml version="1.0" encoding="UTF-8" ?>
  <testsuites id="{job_id()}" name="Valve trace run" tests="{ntests}" failures="{nfails}" time="{total_time}">
    <testsuite id="{job_id()}" name="Valve traces" tests="{ntests}" failures="{nfails}" time="{total_time}">""")
    for tc in testcases:
        junit_report.write(f"""
      <testcase id="{tc.id}" name="{tc.name}" time="{tc.runtime_seconds}">""")
        if len(tc.screenshot_filenames) > 0:
            # You are only allowed on screenshot, it would seem.
            for screenshot_fn in tc.screenshot_filenames[:1]:
                junit_report.write(f"""
        <system-out>[[ATTACHMENT|{screenshot_fn}]]</system-out>
                """)
        for failure in tc.failures:
            junit_report.write(f"""
        <failure message="{failure.message}" type="{failure.type}">
Return code: {tc.return_code}

{escape_for_report(failure.detail)}
        </failure>""")
        junit_report.write("""
     </testcase>""")
    junit_report.write("""
    </testsuite>
  </testsuites>
""")

    return junit_report.getvalue()


def trace_name(trace):
    return f'{trace.id}-{trace.filename}'


def cache_all_traces_to_local_minio(minio_client, minio_bucket, traces):
    if not minio_client.bucket_exists(minio_bucket):
        print(f'ERROR: Bucket {minio_bucket} does not exist.')
        sys.exit(1)

    def exists(c, bucket, object_name, expected_size=-1):
        try:
            assert c.bucket_exists(bucket)
            st = c.stat_object(bucket, object_name)
            if expected_size > 0:
                if not st.size == expected_size:
                    print('%s/%s has an unexpected file size (%s vs %s)' %
                          (bucket, object_name, st.size, expected_size))
                    return False
            return True
        except minio.error.S3Error:
            return False

    for trace in traces:
        object_name = trace_name(trace)
        if exists(minio_client, minio_bucket, object_name, expected_size=trace.size):
            print("%s already exists, skipping caching..." % trace)
        else:
            with requests.get(trace.url, stream=True) as r:
                # print("Request headers: %s", r.headers)  # for caching debugging
                r.raise_for_status()
                print(f'Uploading {trace.filename} of size {naturalsize(trace.size)}...')
                minio_client.put_object(args.bucket, object_name,
                                        r.raw, -1, part_size=10*1024*1024)


def str_to_safe_filename(s):
    """Make a modest effort to transform _s_ into a string that is
    safe to use as a file name. Get rid of the typically annoying
    characters for files."""
    return "".join(i for i in s if i not in r"\/:*?<>| '")


def generate_job_results_folder_name():
    if 'CI_JOB_NAME' in os.environ:
        # Gitlab job IDs can be rather exotic, be safe.
        ci_job_name_safe = str_to_safe_filename(os.environ["CI_JOB_NAME"])
        return f'{ci_job_name_safe}-results'
    else:
        return 'results'


def write_apitrace_commands(trace, exec_filename, dxgi=False):
    apitrace = 'apitrace.exe' if dxgi else 'apitrace'
    trace_filename = os.path.join(args.traces_db, trace_name(trace))
    trace_stem = Path(trace_filename).stem
    rendered_frame_ids = ','.join([str(frame_id) for frame_id in trace.frames_to_capture])
    with open(exec_filename, 'w') as f:
        f.write(f"""#!/bin/sh
set -eu

log() {{
echo "INFO $(date -u +'%F %H:%M:%S') $@"
}}

D=$(dirname "$(readlink -f "$0")")

if [ -e "$D/.started" ]; then
log "Already attempted to run {trace_filename}"
exit 0
fi

date -u +'%F %H:%M:%S' > "$D/.started"

log "Replaying frames ({rendered_frame_ids}) from {trace_filename} ..."
set -x
{apitrace} replay \
--headless \
--snapshot={rendered_frame_ids} \
--snapshot-prefix="$D"/ \
"{trace_filename}" > "$D/{trace_stem}".log 2>&1
retval=$?
set +x

log "Finished replay for {trace_filename}"

cat <<EOF  > "$D/.done"
$(date -u +'%F %H:%M:%S')
$retval
EOF
""")


def write_gfxr_commands(trace, filename):
    with open(filename, 'w') as f:
        f.write(f"""#!/bin/sh
D=$(dirname "$(readlink -f "$0")")

echo "TODO: Dumping {trace_name(trace)} in $D"
""")


def generate_job_commands(trace, path):
    exec_filename = os.path.join(path, 'exec.sh')
    trace_type = Path(trace.filename).suffix
    # apitrace.exe should handle .trace files just fine as well
    # the traces are not all named correctly on the server, some .trace files are actually dxgi traces
    if trace_type == '.trace-dxgi' or trace_type == '.trace':
        write_apitrace_commands(trace, exec_filename, dxgi=True)
    elif trace_type == '.gfxr':
        write_gfxr_commands(trace, exec_filename)
    else:
        print(f'ERROR: Unknown trace type {trace_type}')


class GfxInfo:
    def __init__(self, fields):
        self.machine_tags = fields.get('tags', {})

        self.vram_size_gib = fields.get("vk:vram_size_gib", 0)
        self.gtt_size_gib = fields.get("vk:gtt_size_gib", 0)

        self.driver_name = fields.get("vk:driver:name", "N/A")
        self.driver_version = fields.get('mesa:version', 'N/A')
        self.driver_git_version = fields.get('mesa:git:version', 'N/A')

        self.device_name = fields.get('vk:device:name', 'N/A')
        self.device_type = fields.get('vk:device:type', 'N/A')

    @property
    def all_fields(self):
        return {
            "machine_tags": self.machine_tags,
            "driver": {
                "name": self.driver_name,
                "version": self.driver_version,
                "git_version": self.driver_git_version,
            },
            "device": {
                "name": self.device_name,
                "type": self.device_type,
            },
            "memory": {
                "vram_size_gib": self.vram_size_gib,
                "gtt_size_gib": self.gtt_size_gib,
            }
        }


def upload_frame(client, frame_path):
    file_name = os.path.basename(frame_path)
    blob = client._upload_frame_blob(frame_path, file_name)

    return blob.signed_id


def error_callback(result):
    print(f"ERROR: {result}")


def report_to_valvetraces_website(client, run_name, result_folder):
    def is_postmerge():
        return "CI_MERGE_REQUEST_ID" not in os.environ

    def parse_gfxinfo():
        try:
            with open(f"{result_folder}/gfxinfo.json") as f:
                return GfxInfo(json.loads(f.read()))
        except Exception:
            return GfxInfo({})

    def queue_trace_execution_tasks(pool, dir_entry, gfx_info, trace):
        has_started = False
        has_ended = False
        logs_path = None

        frames_tasks = dict()
        for entry in os.scandir(path=dir_entry.path):
            if entry.name == ".started":
                has_started = True
            elif entry.name == ".done":
                has_ended = True
            elif entry.name.endswith('.log'):
                logs_path = entry.path
            elif entry.name.endswith('.png'):
                try:
                    frame_id = int(Path(entry.name).stem)
                    frames_tasks[frame_id] = pool.apply_async(upload_frame, (client, entry.path), error_callback=error_callback)
                except Exception as e:
                    print(e)

        if has_started:
            status = 0 if has_ended else 1
        else:
            status = None

        return (frames_tasks, status)

    # Get the list of traces
    traces = {str(t.id): t for t in client.list_traces([])}

    # Get the machine tags
    gfx_info = parse_gfxinfo()

    # Create the job in the website
    job = traces_client.job_get_or_create(run_name,
                                          timeline_metadata={"project": os.environ.get('CI_PROJECT_PATH_SLUG')},
                                          is_released_code=is_postmerge())

    # Perform the upload in multiple processes
    with Pool(processes=max(os.cpu_count(), 10)) as pool:
        print("Scan the entire directory structure")
        trace_execs = dict()
        for entry in os.scandir(path=result_folder):
            if entry.is_dir():
                trace = traces.get(entry.name.split('-')[0])
                if trace and f'{trace.id}-{trace.filename}'.startswith(entry.name):
                    trace_execs[trace] = queue_trace_execution_tasks(pool, entry, gfx_info, trace)

        # Create all the trace execution objects
        for trace, params in trace_execs.items():
            frames_tasks, status = params

            try:
                print(f"Uploading the results from {trace}")

                frame_blobs = dict()
                for frame_id, task in frames_tasks.items():
                    if not task.ready():
                        print(f" - Waiting on the upload of the frame {frame_id}")

                    frame_blobs[str(frame_id)] = task.get()

                job.report_trace_execution(metadata=gfx_info.all_fields,
                                        trace=trace,
                                        frame_blobs=frame_blobs,
                                        status=status,
                                        logs_path=None)
            except Exception:
                traceback.print_exc()
                print("Ignoring this trace execution")


def traces_under_gb(traces_list, gb: float):
    """Return a list of traces from `traces_list` that are less than
    `gb` in total size. There's more than one way to solve a
    bin-packing problem like this, here the choice is to return the
    most traces that will fit, rather than the least."""
    max_bytes = gb * 1024**3
    taken_bytes = 0
    selected_traces = []
    for trace in sorted(traces_list, key=operator.attrgetter('size')):
        taken_bytes += trace.size
        if taken_bytes >= max_bytes:
            break
        selected_traces.append(trace)
    return selected_traces


def run_job(traces_client, args):
    if args.access_token is None:
        print("ERROR: No access token given to the client")
        sys.exit(1)

    minio_client = minio.Minio(
        endpoint=urlparse(args.minio_url).netloc,
        access_key=args.user,
        secret_key=args.access_token,
        secure=args.secure)

    traces_to_cache = traces_client.list_traces([])
    if args.max_trace_db_size_gb is not None:
        traces_to_cache = traces_under_gb(traces_to_cache, args.max_trace_db_size_gb)

    if not args.skip_trace_download:
        cache_all_traces_to_local_minio(minio_client, args.bucket, traces_to_cache)

    job_folder_path = generate_job_results_folder_name()
    shutil.rmtree(job_folder_path, ignore_errors=True)
    ensure_dir(job_folder_path)
    # Debugging aid to know which job ID created this job folder.
    open(os.path.join(job_folder_path, f'{job_id()}.job'), 'w').close()
    for trace in traces_to_cache:
        object_name = Path(trace_name(trace)).stem
        trace_job_path = os.path.join(job_folder_path, object_name)
        ensure_dir(trace_job_path)
        generate_job_commands(trace, trace_job_path)

    if not args.generate_job_folder_only:
        if not args.local_run:
            # It is assumed here the job definition has been generated and place in this file.
            # Make it an argument?
            cp = subprocess.call([args.executor_client,
                                  "run",
                                  "-w",  # Wait for the machine to become available
                                  "-a", f"valvetraces:{args.access_token}",
                                  "-g", args.minio_valvetraces_group_name,
                                  "-j", job_id(),
                                  "-s", job_folder_path,
                                  args.executor_job_path])

            print(f"The client exited with the return code {cp}")
        else:
            cmd = f"find {job_folder_path} -name exec.sh -exec sh '{{}}' ';'"
            os.system(cmd)

    with open(os.path.join(job_folder_path, "junit.xml"), "w") as f:
        f.write(generate_junit_report(job_folder_path))

    report_to_valvetraces_website(traces_client, args.run_name, job_folder_path)


def report_results(traces_client, args):
    report_to_valvetraces_website(traces_client, args.run_name, args.results)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(prog='Valve trace runner')
    parser.add_argument("-s", '--valvetraces-url', dest='valvetraces_url',
                        default=os.environ.get("VALVETRACES_SERVER", 'https://linux-perf.steamos.cloud'))
    parser.add_argument("-u", '--valvetraces-user', dest='valvetraces_user',
                        default=os.environ.get("VALVETRACES_USERNAME", None))
    parser.add_argument("-r", '--run-name', dest='run_name', required=True)

    subparsers = parser.add_subparsers()

    run_parser = subparsers.add_parser('run', help='Run the traces and report')
    run_parser.add_argument("-m", '--minio-url', dest='minio_url',
                            default=os.environ.get("VALVETRACES_MINIO_URL", "http://localhost:9000"),
                            help='URL to the Minio service')
    run_parser.add_argument('-u', '--user',
                            default=os.environ.get('VALVETRACES_MINIO_USER', 'valvetraces'),
                            help='User to access Minio with, default is "traces".')
    # REVIEW: Is there a way to have this pick its value from an
    # environment variable *and* be a required argument, that is,
    # absence of the environment variable won't require special casing
    # after argument parsing?
    run_parser.add_argument('-p', '--access-token',
                            default=os.environ.get('VALVETRACES_BUCKET_PASSWORD', None),
                            help='Access token for the traces bucket in the Minio instance.')
    run_parser.add_argument('-b', '--bucket', default=os.environ.get('VALVETRACES_BUCKET', 'valvetraces'),
                            help='The name of the bucket to cache matching traces into. Defaults to "valvetraces"')
    run_parser.add_argument('--traces-db', default=os.environ.get('VALVETRACES_TRACES_DB', '/traces'),
                            help='The path to directory containing all available traces. Defaults to /traces')
    run_parser.add_argument('--executor-client', default=os.environ.get('VALVETRACES_EXECUTOR_CLIENT', 'client.py'),
                            help='The path to the executor client command')
    run_parser.add_argument('--executor-job-path', default=os.environ.get('VALVETRACES_EXECUTOR_JOB', 'b2c.yml.jinja2'),
                            help='The path to the job definition for the executor to run')
    run_parser.add_argument('--minio-valvetraces-group-name', default=os.environ.get('VALVETRACES_GROUP_NAME', "valvetraces-ro"),
                            help="The group name to add the job user to for valve traces bucket access")
    run_parser.add_argument('--local-run', default=False, action='store_true',
                            help="Do not submit any jobs, useful for development")
    run_parser.add_argument('--max-trace-db-size-gb', type=float,
                            help="Stop collecting traces when the total download size would exceed N GB. Useful for quick tests and impoverished DUTs!")
    run_parser.add_argument('--skip-trace-download', default=False, action='store_true',
                            help="Do not attempt to resync remote trace files")
    run_parser.add_argument('--generate-job-folder-only', default=False, action='store_true',
                            help="Do not try to replay the traces, just generate the job folder")
    run_parser.add_argument('--secure', default=False,
                            help='Whether to use TLS to connect to the Minio endpoint. Default is False.')
    run_parser.set_defaults(func=run_job)

    report_parser = subparsers.add_parser('report', help='Report an already-created run')
    report_parser.add_argument('results', help='Folder containing the results to report')
    report_parser.set_defaults(func=report_results)

    args = parser.parse_args()

    if args.valvetraces_user is None:
        print("ERROR: No traces server username specified")
        sys.exit(1)

    traces_client = Client(url=args.valvetraces_url, username=args.valvetraces_user)

    try:
        entrypoint = args.func
    except AttributeError:
        parser.print_help()
        sys.exit(0)

    entrypoint(traces_client, args)
