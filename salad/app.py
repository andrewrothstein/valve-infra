#!/usr/bin/env python3

from salad import Machine, SerialConsoleStream

import traceback
import threading
import flask


app = flask.Flask(__name__)


class SerialLoop(threading.Thread):
    def run(self):
        SerialConsoleStream.listen_to_all_serial_ports()


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


@app.route('/v1/machines', methods=['GET'])
def get_machine_list():
    return {
        "machines": Machine.known_machines()
    }


@app.route('/v1/machines/<machine_id>/sessions', methods=['GET'])
def get_session_list(machine_id):
    machine = get_machine_or_fail(machine_id)
    return {
        "sessions": list(machine.sessions.keys())
    }


@app.route('/v1/machines/<machine_id>/sessions/<session_id>/sources', methods=['GET'])
def get_session_sources(machine_id, session_id):
    machine = get_machine_or_fail(machine_id)

    session = machine.sessions.get(session_id)
    if session is None:
        raise ValueError(f"The session '{session_id}' is unavailable")

    # hardcode to serial for now
    return {"sources": ["serial"]}


@app.route('/v1/machines/<machine_id>/sessions/<session_id>/sources/<source_id>', methods=['GET'])
def get_session_logs(machine_id, session_id, source_id):
    machine = get_machine_or_fail(machine_id)

    session = machine.sessions.get(session_id)
    if session is None:
        raise ValueError(f"The session '{session_id}' is unavailable")

    if source_id != "serial":
        raise ValueError(f"The source '{source_id}' is unavailable")

    return session.raw_logs

if __name__ in ['__main__', 'app']:  # pragma: nocover
    serial_loop = SerialLoop()
    serial_loop.start()

    # Start flask
    app.run()
