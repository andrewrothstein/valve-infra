#!/usr/bin/env python3

from serial.tools import list_ports as serial_list_port
from functools import cached_property
from collections import namedtuple
from gfxinfo import GFXInfo, AMDGPU
import multiprocessing
import netifaces
import argparse
import requests
import psutil
import serial
import time
import sys
import re
import os


NetworkConf = namedtuple("NetworkConf", ['mac', 'ipv4', 'ipv6'])


class MachineInfo(GFXInfo):
    @property
    def machine_base_name(self):
        return self.amdgpu.gfx_version.lower()

    @cached_property
    def machine_tags(self):
        tags = set()

        tags.add(f"amdgpu:family::{self.amdgpu.family}")
        tags.add(f"amdgpu:codename::{self.amdgpu.codename}")
        tags.add(f"amdgpu:gfxversion::{self.amdgpu.gfx_version}")

        if self.amdgpu.is_APU:
            tags.add("amdgpu:APU")

        return tags

    @property
    def default_gateway_nif_addrs(self):
        _, gw_nif = netifaces.gateways().get('default', {}).get(netifaces.AF_INET, (None, None))

        addrs = netifaces.ifaddresses(gw_nif)
        mac = addrs[netifaces.AF_LINK][0]['addr']
        ipv4 = addrs.get(netifaces.AF_INET, [{}])[0].get('addr')
        ipv6 = addrs.get(netifaces.AF_INET6, [{}])[0].get('addr')

        return NetworkConf(mac, ipv4, ipv6)

    def send_through_local_tty_device(self, msg, tty_device=None):
        if tty_device is None:
            tty_device = self.local_tty_device

        if tty_device is not None:
            with serial.Serial(tty_device, baudrate=115200, timeout=1) as ser:
                ser.write(msg.encode())

    @cached_property
    def local_tty_device(self):
        def ping_serial_port(port):
            ser = serial.Serial(port, baudrate=115200, timeout=1)

            # Make sure we start from a clean slate
            ser.reset_input_buffer()

            # Send a ping, and wait for the pong
            ser.write(b"SALAD.ping\n")
            is_answer_pong = (ser.readline() == b"SALAD.pong\n")

            sys.exit(0 if is_answer_pong else 42)

        # Get all available ports
        ports = serial_list_port.comports()
        if len(ports) == 0:
            return None

        # Find all the available ports
        pending_processes = {}
        for port in [p.device for p in ports]:
            p = multiprocessing.Process(target=ping_serial_port, args=(port,))
            p.start()
            pending_processes[p] = port

        # Find out which one is connected
        first_port_found = None
        while first_port_found is None and len(pending_processes) > 0:
            # Wait for a process to die (better than polling)
            time.sleep(0.01) # os.wait()

            # Check the state of all the pending processes
            for p in list(pending_processes.keys()):
                if p.exitcode is not None:
                    # Remove the process from the pending list
                    port = pending_processes.pop(p)
                    if p.exitcode == 0:
                        first_port_found = port
                        break

        # Kill all the processes we created, then wait for them to die
        for p in pending_processes:
            p.terminate()
        for p in pending_processes:
            p.join()

        # Complete the association on the other side
        if first_port_found is not None:
            mac_addr = info.default_gateway_nif_addrs.mac
            self.send_through_local_tty_device(f"SALAD.machine_id={mac_addr}\n",
                                               tty_device=first_port_found)

        return first_port_found

    def to_machine_registration_request(self, ignore_local_tty_device=False):
        addrs = self.default_gateway_nif_addrs

        ret = {
            "base_name": self.machine_base_name,
            "tags": list(self.machine_tags),
            "mac_address": addrs.mac,
            "ip_address": addrs.ipv4,
        }

        if not ignore_local_tty_device:
            # Get the name of the local tty device (strip /dev/)
            tty_dev_name = self.local_tty_device
            if tty_dev_name is not None and tty_dev_name.startswith("/dev/"):
                tty_dev_name = tty_dev_name[5:]

            ret["local_tty_device"] = tty_dev_name

        return ret

def serial_console_works():
    def check_serial_console():
        # stdin is closed by multiprocessing, re-open it!
        sys.stdin = os.fdopen(0)
        sys.stdin.flush()

        # Send the ping
        print("SALAD.ping")

        # Wait for the pong!
        is_answer_pong = re.match(r"^SALAD.pong\r?\n$", sys.stdin.readline())
        sys.exit(0 if is_answer_pong else 42)

    # Start a process that will try to print and read
    p = multiprocessing.Process(target=check_serial_console)
    p.start()
    p.join(1)

    if p.exitcode == 0:
        return True
    elif p.exitcode is None:
        p.terminate()

    return False

parser = argparse.ArgumentParser()
parser.add_argument('-a', dest='amdgpu_drv_path', default=None,
                    help='Path to an up-to-date amdgpu_drv.c file')
parser.add_argument('-m', '--mars_host', dest='mars_host', default="10.42.0.1",
                    help='URL to the machine registration service MaRS')
parser.add_argument('--no-tty', dest="no_tty", action="store_true",
                    help="Do not discover/check the existence of a serial connection to SALAD")
# FIXME: Port hardcoding isn't great.
parser.add_argument('--sgt_hartman', dest='sgt_hartman_host',
                    default="10.42.0.1:8001",
                    help='URL to the machine registration service MaRS')
parser.add_argument('action', help='Action this script should do',
                    choices=['register', 'cache_dbs', 'check', 'sgt_hartman'])
args = parser.parse_args()

info = MachineInfo(amdgpu_drv_path=args.amdgpu_drv_path)
if args.action == "register":
    params = info.to_machine_registration_request(ignore_local_tty_device=args.no_tty)

    r = requests.post(f"http://{args.mars_host}/api/v1/machine/", json=params)
    if r.status_code == 400:
        mac_address = params['mac_address']
        r = requests.patch(f"http://{args.mars_host}/api/v1/machine/{mac_address}/", json=params)

    status = "complete" if r.status_code == 200 else "failed"
    info.send_through_local_tty_device(f"MaRS: Registration {status}\n")

    sys.exit(0 if r.status_code == 200 else 1)

elif args.action == "cache_dbs":
    if args.amdgpu_drv_path is None:
        print("ERROR: Please set the amdgpu_drv_path (-a)", file=sys.stderr)
        sys.exit(1)

    with open(args.amdgpu_drv_path, 'w') as f:
        f.write(AMDGPU.download_pciid_db())

elif args.action == "check":
    mac_addr = info.default_gateway_nif_addrs.mac

    # Get the expected configuration
    r = requests.get(f"http://{args.mars_host}/api/v1/machine/{mac_addr}/")
    r.raise_for_status()
    expected_conf = r.json()

    # Generate the configuration
    local_config = info.to_machine_registration_request(ignore_local_tty_device=True)
    has_differences = False
    for key, value in local_config.items():
        expected_value = expected_conf.get(key)
        if (type(expected_value) != type(value) or \
            (type(value) is list and set(expected_value) != set(value)) or \
            (type(value) is not list and expected_value != value)):
            has_differences = True
            print(f"Mismatch for '{key}': {value} vs the expected {expected_value}")

    # Check that the serial console is working
    if not args.no_tty:
        if serial_console_works():
            print(f"SALAD.machine_id={mac_addr}")
        else:
            has_differences = True
            print(f"The configured console is not connected to SALAD")

    if not has_differences:
        print("No differences found!")

    sys.exit(0 if not has_differences else 1)

elif args.action == "sgt_hartman":
    mac_addr = info.default_gateway_nif_addrs.mac

    r = requests.get(f"http://{args.sgt_hartman_host}/rollcall/{mac_addr}")
    r.raise_for_status()
    print(r.content)
    sys.exit(0)
