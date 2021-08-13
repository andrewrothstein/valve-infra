#!/usr/bin/env python3

import traceback
import requests
import config
import click
import flask
import json

from executor import SergentHartman, MachineState
from gitlab_runner import GitlabRunnerAPI
from mars import MarsClient, Machine
from boots import BootService
from client import JobStatus
from job import Job, Target


class CustomJSONEncoder(flask.json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, JobStatus):
            return obj.name
        elif isinstance(obj, SergentHartman):
            return {
                "is_active": obj.is_active,
                "is_registered": obj.is_machine_registered,
                "boot_loop_counts": obj.boot_loop_counts,
                "qualifying_rate": obj.qualifying_rate,
                "current_loop_count": obj.cur_loop,
                "statuses": dict([(s.name, val) for s, val in obj.statuses.items()]),
            }
        elif isinstance(obj, MachineState):
            return obj.name
        elif isinstance(obj, Machine):
            return {
                "state": obj.executor.state,
                "ready_for_service": obj.ready_for_service,
                "has_pdu_assigned": obj.pdu_port is not None,
                "local_tty_device": obj.local_tty_device,
                "tags": list(obj.tags),
                "training": obj.executor.sergent_hartman
            }

        return super().default(obj)


app = flask.Flask(__name__)
app.json_encoder = CustomJSONEncoder


@app.errorhandler(ValueError)
def handle_valueError_exception(error):
    traceback.print_exc()
    response = flask.jsonify({"error": str(error)})
    response.status_code = 400
    return response


@app.route('/api/v1/machines', methods=['GET'])
def get_machine_list():
    with app.app_context():
        mars = flask.current_app.mars

    return {
        "machines": dict([(m.id, m) for m in mars.known_machines])
    }


def proxy_request_to_mars(url):
    r = requests.request(flask.request.method, url, json=flask.request.json)
    return r.content, r.status_code, {'Content-Type': r.headers['content-type']}


@app.route('/api/v1/machine/', methods=['GET', 'POST'])
def machine_proxy():
    with app.app_context():
        mars = flask.current_app.mars
    return proxy_request_to_mars(f"{mars.mars_base_url}/api/v1/machine/")


@app.route('/api/v1/machine/<machine_id>/', methods=['GET', 'PATCH'])
def machine_detail_proxy(machine_id):
    with app.app_context():
        mars = flask.current_app.mars
    return proxy_request_to_mars(f"{mars.mars_base_url}/api/v1/machine/{machine_id}/")


@app.route('/api/v1/jobs', methods=['POST'])
def post_job():
    def find_suitable_machine(target):
        with app.app_context():
            mars = flask.current_app.mars

        mars.sync_machines()

        wanted_tags = set(target.tags)

        # If the target id is specified, check the tags
        if target.id is not None:
            machine = mars.get_machine_by_id(target.id)
            if machine is None:
                return None, 404, f"Unknown machine with ID {target.id}"
            elif not wanted_tags.issubset(machine.tags):
                return None, 406, (f"The machine {target.id} does not matching tags "
                                   f"(asked: {wanted_tags}, actual: {machine.tags})")
            elif machine.executor.state != MachineState.IDLE:
                return None, 409, (f"The machine {target.id} is unavailable: "
                                   f"Current state is {machine.executor.state.name}")
            return machine, 200, None
        else:
            found_a_candidate_machine = False
            for machine in mars.known_machines:
                if not wanted_tags.issubset(machine.tags):
                    continue

                found_a_candidate_machine = True
                if machine.executor.state == MachineState.IDLE:
                    return machine, 200, "success"

            if found_a_candidate_machine:
                return None, 409, f"All machines matching the tags {wanted_tags} are busy"
            else:
                return None, 406, f"No machines found matching the tags {wanted_tags}"

    class JobRequest:
        def __init__(self, request, version, raw_job, target, callback_endpoint,
                     job_bucket_initial_state_tarball_file=None, job_id=None):
            self.request = request
            self.version = version
            self.raw_job = raw_job
            self.target = target
            self.callback_endpoint = callback_endpoint

            # Clients may specify a starting state for the job bucket,
            # this will be a tarball that is extracted prior to the
            # job starting.
            self.job_bucket_initial_state_tarball_file = job_bucket_initial_state_tarball_file

            # The executor will ensure job IDs are unique, but use the
            # client-provided prefix for as a naming convention.
            self.job_id = job_id

            # Callback validation
            if callback_endpoint[0] is None:
                raise ValueError("callback's host cannot be None. Leave empty to get the default value")
            if callback_endpoint[1] is None:
                raise ValueError("callback's port cannot be None")

        @classmethod
        def parse(cls, request):
            if request.mimetype == "application/json":
                return JSONJobRequest(request)
            elif request.mimetype == "multipart/form-data":
                return MultipartJobRequest(request)
            else:
                raise ValueError("Unknown job request format")

    # DEPRECATED: To be removed when we are sure all the clients out there have been updated
    class JSONJobRequest(JobRequest):
        def __init__(self, request):
            job_params = request.json
            metadata = job_params["metadata"]
            job = Job.from_job(job_params["job"])

            # Use the client-provided host callback if available, or default to the remote addr
            remote_addr = metadata.get("callback_host", flask.request.remote_addr)
            endpoint = (remote_addr, metadata.get("callback_port"))

            super().__init__(request=request, version=0, raw_job=job_params["job"],
                             target=job.target, callback_endpoint=endpoint)

    class MultipartJobRequest(JobRequest):
        def __init__(self, request):
            metadata_file = request.files.get('metadata')
            if metadata_file is None:
                raise ValueError("No metadata file found")

            if metadata_file.mimetype != "application/json":
                raise ValueError("The metadata file has the wrong mimetype: "
                                 "{metadata_file.mimetype}} instead of application/json")

            try:
                metadata = json.loads(metadata_file.read())
            except json.JSONDecodeError as e:
                raise ValueError(f"The metadata file is not a valid JSON file: {e.msg}")

            version = metadata.get('version')
            if version == 1:
                self.parse_v1(request, metadata)
            else:
                raise ValueError(f"Invalid request version {version}")

        def parse_v1(self, request, metadata):
            # Get the job file, and check its mimetype
            job_file = request.files['job']
            if job_file.mimetype != "application/x-yaml":
                raise ValueError("The metadata file has the wrong mimetype: "
                                 "{job_file.mimetype}} instead of application/x-yaml")

            initial_state_tarball_file = request.files.get('job_bucket_initial_state_tarball_file', None)
            if initial_state_tarball_file and initial_state_tarball_file.mimetype != "application/octet-stream":
                raise ValueError("The job_bucket_initial_state_tarball file has the wrong mimetype: "
                                 "{initial_state_tarball_file.mimetype}} instead of application/octet-stream")

            # Create a Job object
            raw_job = job_file.read().decode()
            job = Job.from_job(raw_job)

            # Get the target that will run the job. Use the job's target by default,
            # but allow the client to override the target
            if "target" in metadata:
                target = metadata.get('target', {})
                job_target = Target(target.get('id'), target.get('tags', []))
            else:
                job_target = job.target

            # Use the client-provided host callback if available, or default to the remote addr
            callback = metadata.get('callback', {})
            remote_addr = callback.get("host", request.remote_addr)
            endpoint = (remote_addr, callback.get("port"))

            super().__init__(request=request, version=1, raw_job=raw_job,
                             target=job_target, callback_endpoint=endpoint,
                             job_bucket_initial_state_tarball_file=initial_state_tarball_file,
                             job_id=metadata.get('job_id'))

    parsed = JobRequest.parse(flask.request)

    machine, error_code, error_msg = find_suitable_machine(parsed.target)
    if machine is not None:
        machine.executor.start_job(parsed)

    if parsed.version == 0:
        response = {
            "reason": error_msg
        }
    elif parsed.version == 1:
        response = {
            # protocol version
            "version": 1,
            "error_msg": error_msg

            # TODO: Store the job in memory, and show the ID here
        }
    return flask.make_response(flask.jsonify(response), error_code)


@click.group()
@click.option('--gitlab-url', envvar='GITLAB_URL', default='https://gitlab.freedesktop.org')
@click.option('--gitlab-conf-file', envvar='GITLAB_CONF_FILE')
@click.option('--gitlab-access-token', envvar='GITLAB_ACCESS_TOKEN')
@click.option('--gitlab-registration-token', envvar='GITLAB_REGISTRATION_TOKEN')
@click.option('--gitlab-generic-runner/--no-gitlab-generic-runner', default=True)
@click.option('--farm-name', required=True, envvar='FARM_NAME')
@click.pass_context
def cli(ctx, gitlab_url, gitlab_conf_file, gitlab_access_token,
        gitlab_registration_token, gitlab_generic_runner, farm_name):  # pragma: nocover
    # ensure that ctx.obj exists and is a dict (in case `cli()` is called
    # by means other than the `if` block below)
    ctx.ensure_object(dict)

    if gitlab_conf_file is not None and gitlab_access_token is not None and gitlab_registration_token is not None:
        ctx.obj['GITLAB_RUNNER_API'] = GitlabRunnerAPI(gitlab_url, gitlab_conf_file, gitlab_access_token,
                                                       gitlab_registration_token, farm_name,
                                                       expose_generic_runner=gitlab_generic_runner)
    else:
        print(("WARNING: The runners won't be exposed on GitLab because the default configuration file, "
               "and/or the access/registration tokens are not set"))

    ctx.obj['FARM_NAME'] = farm_name


@cli.command()
@click.pass_context
def run(ctx):  # pragma: nocover
    # Start the network boot service
    boots = BootService()

    # Create all the workers based on the machines found in MaRS
    mars = MarsClient(config.MARS_URL, boots, gitlab_runner_api=ctx.obj.get('GITLAB_RUNNER_API'))
    mars.start()

    # Start flask
    with app.app_context():
        flask.current_app.mars = mars
    app.run(host=config.EXECUTOR_HOST, port=config.EXECUTOR_PORT)

    # Shutdown
    mars.stop(wait=True)
    boots.stop()


@cli.group()
@click.pass_context
def gitlab(ctx):  # pragma: nocover
    # ensure that ctx.obj exists and is a dict (in case `cli()` is called
    # by means other than the `if` block below)
    ctx.ensure_object(dict)

    if "GITLAB_API" not in ctx.obj:
        print("ERROR: Can't use the gitlab command without GitLab support")
        ctx.abort()


@gitlab.command()
@click.pass_context
def remove_runners(ctx,):  # pragma: nocover
    gl = ctx.obj['GITLAB_RUNNER'].gl
    farm_name = ctx.obj['FARM_NAME']

    runners = list(filter(lambda r: r.description.startswith(f'{farm_name}-'),
                          gl.runners.list(all=True)))
    if not click.confirm(f'About to remove {len(runners)} runners for the '
                         f' {farm_name} farm, are you sure?',
                         default=False):
        return

    for runner in runners:
        if runner.description.startswith(f'{farm_name}-'):
            print(f"removing {runner.description}")
            runner.delete()


if __name__ == '__main__':  # pragma: nocover
    cli()
