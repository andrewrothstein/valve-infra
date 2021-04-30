#!/usr/bin/env python3

try:
    from functools import cached_property
except:
    from backports.cached_property import cached_property
from getpass import getpass

import argparse
import base64
import hashlib
import humanize
import os
import re
import requests
import sys

from enum import Enum
from PIL import Image
from gfxinfo import GFXInfo

class App:
    def __init__(self, app_blob):
        self.id = app_blob.get("id")
        self.name = app_blob.get("name")
        self.steamappid = app_blob.get("appid")

    def matches(self, app_id):
        return str(self.id) == app_id or str(self.name) == app_id or str(self.steamappid) == app_id

    def __str__(self):
        return f"<App: ID={self.id}, SteamID={self.steamappid}, name={self.name}>"

    def __repr__(self):
        return str(self)

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
                raise ValueError("The URL is missing from the 'direct_upload' key")

            self.headers = direct_upload.get('headers')
            if self.headers is None:
                raise ValueError("The headers are missing from the 'direct_upload' key")

        self.signed_id = blob_dict.get("signed_id")
        if self.signed_id is None:
            raise ValueError("The signed_id is from the blob-creation response")

        self.record_type = BlobType.from_str(blob_dict.get("record_type"))

        if not self.new and self.record_type != BlobType.UNKNOWN:
            self.record = blob_dict.get("record")

    def upload(self, f):
        r = requests.put(self.url, headers=self.headers, data=f)
        r.raise_for_status()

class Trace:
    def __init__(self, trace_blob):
        self.id = trace_blob.get("id")
        self.filename = trace_blob.get("filename")
        self.metadata = trace_blob.get("metadata")
        self.obsolete = trace_blob.get("obsolete")
        self.frames_to_capture = trace_blob.get("frames_to_capture")
        self.url = trace_blob.get("url")
        self.size = trace_blob.get("file_size", -1)

    @property
    def machine_tags(self):
        try:
            return list(self.metadata.get("machine_tags", []))
        except Exception as e:
            print(e)
            return []

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
        return humanize.naturalsize(self.size, binary=True)

    def __str__(self):
        return f"<Trace {self.id}, {self.filename}, size {self.human_size}>"


class Client:
    def __init__(self, url, username=None):
        self.url = url
        self.username = username

        self._login_cookie = None

    @cached_property
    def machine_tags(self):
        return GFXInfo().machine_tags()

    def login(self):
        if self._login_cookie is None:
            password = os.environ.get("VALVETRACESPASSWORD", None)
            if self.username is None or password is None:
                print(f"Please provide the credentials to the service at {self.url}:")
                if self.username is None:
                    self.username = input("User email: ")

                if password is None:
                    password = getpass()

            r = requests.post(f"{self.url}/api/v1/login", allow_redirects=False,
                              json={"user": {"username": self.username, "password": password}})
            # TODO: Make sure to return error 401 if the credentials are invalid
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
        r.raise_for_status()

        return r.json()

    def list_apps(self):
        apps = list()
        for game in self._get("/api/v1/games"):
            apps.append(App(game))

        return apps

    def create_app(self, name, steamappid=None):
        for app in self.list_apps():
            if app.name == name and app.steamappid == steamappid:
                raise ValueError(f"The app named '{name}' already exists: {app}")

        r = self._post("/api/v1/games", {"game": {"name": name, "appid": steamappid}})

        return App(r)

    def list_traces(self, filter_machine_tags=[]):
        tags = [re.compile(t) for t in filter_machine_tags]

        traces = list()
        for trace_blob in self._get("/api/v1/traces"):
            trace = Trace(trace_blob)

            if trace.matches_tags(tags):
                traces.append(trace)

        return traces

    def get_trace(self, trace_name):
        for trace in self.list_traces():
            if trace.filename == trace_name:
                return trace

        raise ValueError(f"Could not find a trace named '{trace_name}' in the service")

    def download_trace(self, trace_name, output_folder):
        trace = self.get_trace(trace_name)

        trace_path = os.path.join(output_folder, trace_name)
        with open(trace_path, 'wb') as f:
            with requests.get(trace.url, stream=True) as r:
                r.raise_for_status()

                # Read all the available data, then write to disk
                for chunk in r.iter_content(None):
                    f.write(chunk)

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

    def _upload_blob(self, filepath, name, data_checksum):
        with open(filepath, "rb") as f:
            # Check the file size
            f.seek(0, os.SEEK_END)
            file_size = f.tell()
            f.seek(0, os.SEEK_SET)

            # Ask the website for the URL of where to upload the file
            r_blob = self._post("/rails/active_storage/direct_uploads",
                                 {"blob": {"filename": name, "byte_size": file_size,
                                           "content_type": "application/octet-stream",
                                           "checksum": data_checksum}})
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

    def upload_trace(self, app_id, filepath, frame_ids, machine_tags=None):
        if machine_tags is None:
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
            return Trace(blob.record)


        # Create the trace from the blob
        r = self._post("/api/v1/traces/",
                    params={"trace": {"upload": blob.signed_id, "game_id": app.id,
                                      "metadata": {"machine_tags": machine_tags},
                                      "frames_to_capture": frame_ids
                                      }})

        return Trace(r)

    def _upload_frame_blob(self, filepath, name):
        image_md5 = hashlib.md5(Image.open(filepath).convert(mode="RGBA").tobytes())
        img_checksum = base64.b64encode(image_md5.digest()).decode()
        # Check if frame already exists on server
        r = self._post("/api/v1/image_checksum", {"checksum": img_checksum})
        if "accepted" not in r:
            return Blob(r, new=False)

        # Generate the MD5 hash for the bucket
        data_checksum = self._data_checksum(filepath)

        return self._upload_blob(filepath, name, data_checksum)

    def upload_frames(self, trace_id, frames, machine_tags=None):
        if machine_tags is None:
            machine_tags = list(self.machine_tags)

        for frame in frames:
            file_name = os.path.basename(frame)
            pattern = r'(?P<frame_id>\d+$)'
            without_ext, _ = os.path.splitext(frame)
            m = re.search(pattern, without_ext)
            if m is None:
                print(f"Couldn't identify \"{frame}\" 's frame id. Skipping ...")
                continue
            frame_id = int(m.groupdict({}).get('frame_id'))
            blob = self._upload_frame_blob(frame, file_name)
            r = self._post("/api/v1/traces/" + str(trace_id) + "/trace_frames/" + str(frame_id) + "/frame_outputs",
                            params={"frame_output": {"upload": blob.signed_id, "trace_id": trace_id,
                            "metadata": {"machine_tags": machine_tags}, "trace_frame_id": frame_id}})

def entrypoint():
    parser = argparse.ArgumentParser(prog='valvetraces')
    parser.add_argument('--username', help='Username you want to use in the service')
    parser.add_argument('-u', '--url', default="https://linux-perf.steamos.cloud", help='URL to the service')

    subparsers = parser.add_subparsers(dest='cmd')
    login_parser = subparsers.add_parser('login', help='Log in the valve traces service')

    list_app_parser = subparsers.add_parser('list_apps', help='List the applications defined in the service')

    create_app_parser = subparsers.add_parser('create_app', help='Create a new application in the service')
    create_app_parser.add_argument("name", help="Name of the application you want to create")
    create_app_parser.add_argument("--steamappid", help="Steam's appid associated to this application")

    list_parser = subparsers.add_parser('list', help='List the traces available in the service')
    list_parser.add_argument('-t', '--tag', dest="machine_tags", action='append',
                             help='Limit results to traces that have machine tags matching this regular expression (can be repeated)')

    download_parser = subparsers.add_parser('download', help='Download a trace from the service')
    download_parser.add_argument('-o', '--output_folder', default="./", help='Folder where to output the trace')
    download_parser.add_argument('trace', help='Path to the trace you want to upload')

    add_tags_parser = argparse.ArgumentParser(add_help=False)
    add_tags_parser.add_argument('-t',
                                 '--tag',
                                 dest="machine_tags",
                                 action='append',
                                 help=('If none provided, the machine tags '
                                       'attached to the file(s) to be uploaded '
                                       'will be generated in the machine '
                                       'running this command. If provided, '
                                       'just attach the specified machine tag '
                                       'to the trace to be uploaded (can be '
                                       'repeated).'))

    upload_trace_parser = subparsers.add_parser('upload_trace',
                                                parents=[add_tags_parser],
                                                help='Upload a trace')
    upload_trace_parser.add_argument('-f', '--frame', action='append', required=True, dest="frames", type=int,
                                     help='ID of the frame that should be captured from this trace (can be repeated)')
    upload_trace_parser.add_argument('app_id',
                                     help='Name/steam app ID of the application/game/benchmark you want to upload a trace for')
    upload_trace_parser.add_argument('trace', help='Path to the trace you want to upload')

    upload_frames_parser = subparsers.add_parser('upload_frames',
                                                 parents=[add_tags_parser],
                                                 help='Upload frames')
    upload_frames_parser.add_argument('--trace-id', required=True, type=int,
                                      help='ID of the trace')
    upload_frames_parser.add_argument('frames', nargs='+',
                                      help=('Path(s) to the frame(s) '
                                            'you want to upload'))

    args = parser.parse_args()

    # Execute the right command
    client = Client(url=args.url, username=args.username)
    if args.cmd == "login":
        client.login()
    elif args.cmd == "list_apps":
        for app in client.list_apps():
            print(str(app))
    elif args.cmd == "create_app":
        app = client.create_app(args.name, args.steamappid)
        print(f"Successfully created the app {str(app)}")
    elif args.cmd == "list":
        for trace in client.list_traces(filter_machine_tags=args.machine_tags or []):
            print(trace)
    elif args.cmd == "download":
        path = client.download_trace(args.trace, args.output_folder)
        print(f"The trace got saved at '{path}'")
    elif args.cmd == "upload_trace":
        client.upload_trace(args.app_id, args.trace, args.frames, args.machine_tags)
    elif args.cmd == "upload_frames":
        client.upload_frames(args.trace_id, args.frames, args.machine_tags)
    else:
        parser.print_help(sys.stderr)


if __name__ == '__main__':
    entrypoint()
