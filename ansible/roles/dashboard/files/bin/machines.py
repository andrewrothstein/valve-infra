#!/usr/bin/env python3
# coding: utf-8

import json
import sys
import urllib.request
import urllib.parse
import urwid

host = "http://localhost"

def fetch_pdus_machines():
    dashboard = {}
    pdus = {}
    machines = {}
    wait_for_config = []

    try:
        with urllib.request.urlopen(f'{host}/api/v1/pdus') as resp:
            pdus = json.loads(resp.read())

    except urllib.error.URLError as e:
        sys.exit(f"urllib error requesting pdus: {e.reason}")

    if not pdus or ("pdus" not in pdus):
        sys.exit("error reading pdus")

    for pdu, ports in pdus["pdus"].items():
        dashboard[pdu] = ports["ports"]

    try:
        with urllib.request.urlopen(f'{host}/api/v1/machines') as resp:
            machines = json.loads(resp.read())

    except urllib.error.URLError as e:
        sys.exit(f"urllib error requesting machines: {e.reason}")

    if not machines or ("machines" not in machines):
        sys.exit("error reading machines")

    for mac, machine in machines["machines"].items():
        name = machine["pdu"]["name"]
        port_id = machine["pdu"]["port_id"]

        # Handle machines without PDU configuration
        if name is None or port_id is None:
            wait_for_config.append({"ip_address": machine["ip_address"],
                                    "mac_address": machine["mac_address"],
                                    })
        else:
            dashboard[name][port_id].update(machine)

    if wait_for_config:
        pdu_name = "Unknown, fix your configuration file manually"
        dashboard[pdu_name] = {}
        fake_port_id = 100
        for m in wait_for_config:
            dashboard[pdu_name][fake_port_id] = m
            fake_port_id += 1

    return dashboard


def post_request(url, data=None):
    if data:
        request = urllib.request.Request(url, data=data, method="POST")
        request.add_header('Content-Type', 'application/json')
    else:
        request = urllib.request.Request(url, method="POST")

    try:
        resp = urllib.request.urlopen(request, timeout=10)
    except urllib.error.URLError as e:
        if data is None:
            return None, f"There was some unexpected issue ({e.reason})"
        else:
            return None, f"There is a discovery process running already ({e.reason})"

    return resp, resp.read()


class Dashboard:
    palette = [
        ('body', 'light gray', 'black', 'standout'),
        ('header', 'black', 'dark blue', 'bold'),
        ('pdu', 'black', 'dark blue', ('standout', 'underline')),
        ('bttn_discover', 'black', 'dark green'),
        ('bttn_cancel', 'black', 'dark red'),
        ('bttn_retire', 'black', 'yellow'),
        ('buttn_activate', 'black', 'dark cyan'),
        ('buttnf', 'white', 'dark blue', 'bold'),
        ]

    def button_press(self, button, data):
        button = button.get_label()

        if button == "DISCOVER":
            post_dict = {
                "pdu": data.get('pdu'),
                "port_id": data.get('port')
                }
            url = f"{host}/api/v1/machine/discover"
            post_data = json.dumps(post_dict).encode()
            resp, message = post_request(url, post_data)

        else:
            if button == "RETIRE":
                url = f"{host}/api/v1/machine/{data.get('mac_address')}/retire"
            elif button == "ACTIVATE":
                url = f"{host}/api/v1/machine/{data.get('mac_address')}/activate"
            elif button == "CANCEL":
                url = f"{host}/api/v1/machine/{data.get('mac_address')}/cancel_job"

            resp, message = post_request(url)

        if type(message) == bytes:
            message = ''.join(map(chr, message))
        self.info_line = " " + button + ": " + message

    def setup_view(self):

        dashboard = fetch_pdus_machines()

        blank = urwid.Divider()

        # Make list to feed to ListBox
        listbox_content = []

        self.header_line = " Control this dashboard with your mouse or " \
            "keys UP / DOWN / PAGE UP / PAGE DOWN / ENTER"

        listbox_content.append(urwid.AttrWrap(urwid.Text(self.header_line), 'header'))
        listbox_content.append(urwid.AttrWrap(urwid.Text(self.info_line), 'header'))

        listbox_content.append(blank)

        for pdu, ports in dashboard.items():
            listbox_content.append(urwid.Padding(
                urwid.Text(("pdu", f"PDU name : {pdu}")), left=1, right=0, min_width=20))

            list_columns = []
            for num, machine in ports.items():
                state = machine.get('state')

                list_columns = [('fixed', 10, urwid.Text(f" Port {num}:"))]

                if state == "TRAINING":
                    boot_loop_counts = machine.get('training').get('boot_loop_counts')
                    current_loop_count = machine.get('training').get('current_loop_count')
                    stext=f"{state} {current_loop_count}/{boot_loop_counts}"
                else:
                    stext = f"{state}"
                list_columns.append(('fixed', 15, urwid.Text(stext)))

                name = machine.get('full_name', "")
                list_columns.append(urwid.Text(name))

                button_data = {
                    "pdu": pdu,
                    "port": num,
                    "mac_address": machine.get('mac_address'),
                    }

                if state == "OFF":
                    list_columns.append(('fixed', 14,
                        urwid.AttrWrap(urwid.Button("DISCOVER", self.button_press, button_data),
                                       'bttn_discover', 'buttnf')))
                elif state == "IDLE" and not machine.get('is_retired'):
                    list_columns.append(('fixed', 14,
                        urwid.AttrWrap(urwid.Button("RETIRE", self.button_press, button_data),
                                       'bttn_retire', 'buttnf')))
                elif machine.get('is_retired'):
                    list_columns.append(('fixed', 14,
                        urwid.AttrWrap(urwid.Button("ACTIVATE", self.button_press, button_data),
                                       'buttn_activate', 'buttnf')))
                elif state == "RUNNING":
                    list_columns.append(('fixed', 14,
                        urwid.AttrWrap(urwid.Button("CANCEL", self.button_press, button_data),
                                       'bttn_cancel', 'buttnf')))

                listbox_content.append(urwid.Columns(list_columns, min_width=10))

            listbox_content.append(blank)

        listbox_content.append(blank)

        listbox = urwid.ListBox(urwid.SimpleListWalker(listbox_content))
        return listbox

    def main(self):
        self.info_line = ""
        self.widget = self.setup_view()
        self.loop = urwid.MainLoop(widget=self.widget, palette=self.palette)
        self.loop.set_alarm_in(1, self.refresh)
        # Set focus on first port of the PDU
        self.loop.widget.set_focus(4)
        self.loop.run()

    def refresh(self, loop=None, data=None):
        focus = self.loop.widget.get_focus()[-1]
        self.loop.widget = self.setup_view()
        self.loop.set_alarm_in(1, self.refresh)
        self.loop.widget.set_focus(focus)


if '__main__' == __name__:
    Dashboard().main()
