#!/usr/bin/env python3

import traceback
import click
import flask

from executor import SergentHartman, MachineState
from gitlab_runner import GitlabRunnerAPI
from mars import MarsClient, Machine
from client import JobStatus
from job import Job
from logger import logger


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


def get_machine_or_fail(machine_id):
    machine = MarsClient.get_machine_by_id(machine_id)
    if machine is None:
        raise ValueError(f"Unknown machine ID '{machine_id}'")
    return machine


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

    job_params = flask.request.json
    metadata = job_params["metadata"]
    job = Job.from_job(job_params["job"])
    logger.debug("raw job:\n%s", job)
    machine, error_code, reason = find_suitable_machine(job.target)
    if machine is not None:
        endpoint = (flask.request.remote_addr, metadata.get("callback_port"))
        # Bit nasty to render twice, but better than duplicating
        # template render in the various call-sites within
        # executor. Rendering it up front reduces the chances for
        # mistakes. (Meta-point: using an HTTP query to specify the
        # "target" could avoid this duplication of work, and might
        # actually make more sense)
        job = Job.render_with_machine(job_params["job"], machine)
        logger.debug("renderered job:\n%s", job)
        machine.executor.start_job(job, endpoint)

    response = {
        # TODO: Store the job in memory, and show the ID here
        "reason": reason
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
@click.option('--mars-url', envvar='MARS_URL', default="http://127.0.0.1")
@click.option('--host', envvar='EXECUTOR_HOST', default="0.0.0.0")
@click.option('--port', envvar='EXECUTOR_PORT', type=int, default=8003)
@click.pass_context
def run(ctx, mars_url, host, port):  # pragma: nocover
    # Create all the workers based on the machines found in MaRS
    mars = MarsClient(mars_url, gitlab_runner_api=ctx.obj.get('GITLAB_RUNNER_API'))
    mars.start()

    # Start flask
    with app.app_context():
        flask.current_app.mars = mars
    app.run(host=host, port=port)

    # Shutdown
    mars.stop(wait=True)


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
