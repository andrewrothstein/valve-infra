#!/usr/bin/env python3

from serial.tools import list_ports as serial_list_port
from functools import cached_property, cache
from collections import namedtuple
from gfxinfo import find_gpu, VulkanInfo
from gfxinfo import amdgpu
import multiprocessing
import netifaces
import argparse
import requests
import serial
import time
import sys
import re
import os


NetworkConf = namedtuple("NetworkConf", ['mac', 'ipv4', 'ipv6'])


class MachineInfo():
    def __init__(self, cache_directory):
        self.gpu = find_gpu(cache_directory)
        if not self.gpu:
            raise Exception('No suitable GPU in this machine')
        else:
            print(self.gpu)

    @property
    def machine_base_name(self):
        return self.gpu.base_name.lower()

    @cached_property
    def machine_tags(self):
        tags = self.gpu.tags

        if info := VulkanInfo.construct():
            tags.add(f"vk:VRAM:{info.VRAM_heap.GiB_size}_GiB")

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
            ser.write(b"\nSALAD.ping\n")
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
            print("Found a tty device at", first_port_found)
            self.send_through_local_tty_device(f"SALAD.machine_id={mac_addr}\n",
                                               tty_device=first_port_found)
        else:
            print("WARNING: Found no serial port!")

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
        import termios

        # stdin is closed by multiprocessing, re-open it!
        sys.stdin = os.fdopen(0)

        # Remove any input we might have received thus far
        termios.tcflush(sys.stdin, termios.TCIFLUSH)

        # Send the ping
        sys.stdout.write("\nSALAD.ping\n")
        sys.stdout.flush()

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
parser.add_argument('-a', dest='cache_directory', default='/tmp',
                    help='Directory into which GPU-specific PCI ID databases are cached')
parser.add_argument('-m', '--mars_host', dest='mars_host', default="10.42.0.1",
                    help='URL to the machine registration service MaRS')
parser.add_argument('--no-tty', dest="no_tty", action="store_true",
                    help="Do not discover/check the existence of a serial connection to SALAD")
parser.add_argument('action', help='Action this script should do',
                    choices=['register', 'check', 'cache'])
args = parser.parse_args()


if args.action == "register":
    info = MachineInfo(args.cache_directory)
    params = info.to_machine_registration_request(ignore_local_tty_device=args.no_tty)

    r = requests.post(f"http://{args.mars_host}/api/v1/machine/", json=params)
    if r.status_code == 400:
        mac_address = params['mac_address']
        r = requests.patch(f"http://{args.mars_host}/api/v1/machine/{mac_address}/", json=params)

    status = "complete" if r.status_code == 200 else "failed"
    info.send_through_local_tty_device(f"MaRS: Registration {status}\n")

    sys.exit(0 if r.status_code == 200 else 1)

elif args.action == "cache":
    drv_file = amdgpu.download_supported_pci_devices(args.cache_directory)
    print("Cached %d bytes of AMDGPU PCI IDs" % len(drv_file))

elif args.action == "check":
    info = MachineInfo(args.cache_directory)
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
