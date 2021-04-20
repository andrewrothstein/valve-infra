#!/usr/bin/env python3

from threading import Thread, Event

import traceback
import requests
import flask
import time
import sys
import os

# Add the parent folder to the python path
sys.path.append(os.path.abspath('{}/../'.format(os.path.dirname(__file__))))

from salad import salad
from executor import Machine, SergentHartman, MachineState
from job import Job
from client import JobStatus


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
                obj.machine_id: {
                    "state": obj.state,
                    "ready_for_service": obj.ready_for_service,
                    "has_pdu_assigned": obj.pdu_port is not None,
                    "local_tty_device": obj.local_tty_device,
                    "tags": list(obj.tags),
                    "training": obj.sergent_hartman
                }
            }

        return super().default(self, obj)


app = flask.Flask(__name__)
app.json_encoder = CustomJSONEncoder


class MaRS(Thread):
    def __init__(self):
        super().__init__()
        self.stop_event = Event()

    def stop(self, wait=True):
        self.stop_event.set()
        if wait:
            self.join()

    def run(self):
        while True:
            try:
                Machine.sync_machines_with_mars()

                # Wait for 5 seconds, with the ability to exit every second
                for i in range(5):
                    time.sleep(1)
                    if self.stop_event.is_set():
                        return
            except Exception:
                traceback.print_exc()


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
    return {
        "machines": Machine.known_machines()
    }


@app.route('/api/v1/jobs', methods=['POST'])
def post_job():
    job_params = flask.request.json

    metadata = job_params["metadata"]
    job = Job(job_params["job"])

    machine, error_code, reason = Machine.find_suitable_machine(job.target)
    if machine is not None:
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
    mars_poller = MaRS()
    mars_poller.start()

    # Start flask
    app.run(host='0.0.0.0', port=os.getenv("EXECUTOR_PORT", 8003))

    # Shutdown
    mars_poller.stop(wait=False)
    Machine.shutdown_all_workers()
    salad.stop()
    mars_poller.join()
