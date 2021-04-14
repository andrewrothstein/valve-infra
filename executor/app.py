#!/usr/bin/env python3

from threading import Thread, Event
from urllib3.util.retry import Retry

import traceback
import requests
import flask
import time
import sys
import os

# Add the parent folder to the python path
sys.path.append(os.path.abspath('{}/../'.format(os.path.dirname(__file__))))

from salad import salad
from executor import Machine
from job import Job


app = flask.Flask(__name__)


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
            Machine.sync_machines_with_mars()

            # Wait for 5 seconds, with the ability to exit every second
            for i in range(5):
                time.sleep(1)
                if self.stop_event.is_set():
                    return


def requests_retry_setup():
    s = requests.Session()

    retries = Retry(total=5,
                    backoff_factor=0.1,
                    status_forcelist=[500, 502, 503, 504])

    s.mount('http://', requests.adapters.HTTPAdapter(max_retries=retries))
    s.mount('https://', requests.adapters.HTTPAdapter(max_retries=retries))


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
    # Make sure that any HTTP/HTTPS request done in this process get retried
    requests_retry_setup()

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
