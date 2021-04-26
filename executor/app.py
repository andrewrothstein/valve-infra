#!/usr/bin/env python3

import traceback
import flask
import sys
import os

# Add the parent folder to the python path
sys.path.append(os.path.abspath('{}/../'.format(os.path.dirname(__file__))))

from executor import Executor, SergentHartman, MachineState
from job import Job
from client import JobStatus

from mars import MarsClient, Machine


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
    return {
        "machines": dict([(m.id, m) for m in mars.known_machines])
    }


@app.route('/api/v1/jobs', methods=['POST'])
def post_job():
    def find_suitable_machine(target):
        mars.sync_machines()

        wanted_tags = set(target.tags)

        # If the target_id is specified, check the tags
        if target.target_id is not None:
            machine = mars.get_machine_by_id(target.target_id)
            if machine is None:
                return None, 404, f"Unknown machine with ID {target.target_id}"
            elif not wanted_tags.issubset(machine.tags):
                return None, 406, f"The machine {target.target_id} does not matching tags (asked: {wanted_tags}, actual: {machine.tags})"
            elif machine.executor.state != MachineState.IDLE:
                return None, 409, f"The machine {target.target_id} is unavailable: Current state is {machine.state.name}"
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
    job = Job(job_params["job"])

    machine, error_code, reason = find_suitable_machine(job.target)
    if machine is not None:
        endpoint = (flask.request.remote_addr, metadata.get("callback_port"))
        machine.executor.start_job(job, endpoint)

    response = {
        # TODO: Store the job in memory, and show the ID here
        "reason": reason
    }
    return flask.make_response(flask.jsonify(response), error_code)


if __name__ == '__main__':  # pragma: nocover
    # Create all the workers based on the machines found in MaRS
    mars = MarsClient()
    mars.start()

    # Start flask
    app.run(host='0.0.0.0', port=os.getenv("EXECUTOR_PORT", 8003))

    # Shutdown
    mars.stop(wait=True)
