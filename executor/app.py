#!/usr/bin/env python3

# Add the parent folder to the python path
import sys
import os
sys.path.append(os.path.abspath('{}/../'.format(os.path.dirname(__file__))))

from salad import salad
from executor import Machine
from job import Job

import traceback
import threading
import flask


app = flask.Flask(__name__)


def get_machine_or_fail(machine_id):
    machine = Machine.get_by_id(machine_id)
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
    def ser(machine):
        return {
            "state": machine.state.name,
            "ready_for_service": machine.ready_for_service,
            "has_pdu_assigned": machine.pdu_port is not None,
            "local_tty_device": machine.local_tty_device,
            "tags": list(machine.tags)
        }

    return {
        "machines": dict([(m.machine_id, ser(m)) for m in Machine.known_machines()]),
    }


@app.route('/api/v1/jobs', methods=['POST'])
def post_job():
    error_code = 200

    job_params = flask.request.json

    metadata = job_params["metadata"]
    job = Job(job_params["job"])

    machine, reason = Machine.find_suitable_machine(job.target)
    if machine is None:
        error_code = 400
    else:
        endpoint = (flask.request.remote_addr, metadata.get("callback_port"))
        machine.start_job(job, endpoint)

    response = {
        # TODO: Store the job in memory, and show the ID here
        "reason": reason
    }
    return flask.make_response(flask.jsonify(response), error_code)


if __name__ == '__main__':  # pragma: nocover
    # Start the monitoring of serial consoles
    salad.start()

    # Create all the workers based on the machines found in MaRS
    Machine.sync_machines_with_mars()

    # Start flask
    app.run(host='0.0.0.0', port=os.getenv("EXECUTOR_PORT", 8003))

    # Shutdown
    Machine.shutdown_all_workers()
    salad.stop()
