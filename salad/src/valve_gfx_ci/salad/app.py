#!/usr/bin/env python3

from .tcpserver import SerialConsoleTCPServer
from .salad import salad

import flask
import os


class CustomJSONEncoder(flask.json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, SerialConsoleTCPServer):
            return {
                "id": obj.id,
                "tcp_port": obj.port,
                "has_client": obj.client is not None,
            }

        return super().default(self, obj)


app = flask.Flask(__name__)
app.json_encoder = CustomJSONEncoder


@app.route('/api/v1/machine', methods=['GET'])
def machines():
    return {
        "machines": dict([(m.id, m) for m in salad.machines]),
    }


@app.route('/api/v1/machine/<machine_id>', methods=['GET'])
def machine_id(machine_id):
    machine = salad.get_or_create_machine(machine_id)
    return CustomJSONEncoder().encode(machine)


def run():
    salad.start()
    app.run(host='0.0.0.0', port=os.getenv("SALAD_PORT", 8005))
    salad.stop()


if __name__ == '__main__':  # pragma: nocover
    run()
