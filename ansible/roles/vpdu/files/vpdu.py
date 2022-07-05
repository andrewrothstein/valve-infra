#!/usr/bin/env python3

import argparse
from datetime import datetime
import enum
import os
import socketserver
import struct
import subprocess
import sys

BRIDGE = 'vivianbr0'
SALAD_TCP_CONSOLE_PORT = os.getenv("SALAD_TCPCONSOLE_PORT", 8100)
NUM_PORTS = 16
DUT_DISK_SIZE = '32G'
VPDU_DIR = os.getenv("VPDU_DIR", "./tmp_vpdu")
os.makedirs(VPDU_DIR, exist_ok=True)
OUTLETS = []


def log(msg, *args):
    print(msg % args)

def check_bridge():
    global BRIDGE
    try:
        subprocess.check_call(['ip', 'link', 'show', BRIDGE])
    except:
        subprocess.check_call(['ip', 'link', 'add', 'name', BRIDGE, 'type', 'bridge'])
        subprocess.check_call(['ip', 'addr', 'add', '10.42.0.1/24', 'dev', BRIDGE])
        subprocess.check_call(['ip', 'link', 'set', BRIDGE, 'up'])


class PowerState(enum.IntEnum):
    ON = 3
    OFF = 4
    ERROR = 5


def gen_mac(index):
    counter = format(index, '02x')
    return f'52:54:00:11:22:{counter}'



def get_disk(index):
    hda = f'{VPDU_DIR}/dut_disk{index}.qcow2'
    if not os.path.exists(hda):
        subprocess.run(['qemu-img', 'create', '-f', 'qcow2', hda, DUT_DISK_SIZE],
                        stdout=subprocess.DEVNULL)
    return hda


OUTLETS = [
    {'mac': gen_mac(i),
     'disk': get_disk(i),
     'monitor_port': 4444 + i,
     'state': PowerState.OFF} for i in range(16)
]

def cleanup(signum=-1, frame=-1):
    # You can not log inside the signal handler, buffered writers are not reentrant.
    global OUTLETS
    for machine in OUTLETS:
        os.remove(machine['disk'])
    sys.exit(0)


def reset_stdout():
    try:
        device = os.ttyname(sys.stdout)
        subprocess.call(["stty", "sane", "-F", device])
    except:
        pass


class PowerState(enum.IntEnum):
    ON = 3
    OFF = 4
    ERROR = 5


class DUT:
    def __init__(self, mac, disk):
        self.disk = disk
        log_name = datetime.now().strftime(f'{VPDU_DIR}/dut-log-{mac.replace(":", "")}-%H%M%S-%d%m%Y.log')
        cmd = [
            'qemu-system-x86_64',
            '-machine', 'q35,accel=kvm',
            '-m', '2048',
            '-smp', '2,sockets=2,cores=1,threads=1',
            '-hda', disk,
            '-vga', 'virtio',
            '-boot', 'n',
            '-nic', f'bridge,br=vivianbr0,mac={mac},model=virtio-net-pci',
            # Not decided if I want this feature, can be handy though!
            # '-serial', 'mon:telnet::4444,server=on,wait=off',
            '-chardev', f'socket,id=saladtcp,host=localhost,port={SALAD_TCP_CONSOLE_PORT},server=off,logfile={log_name}',
            '-device', 'pci-serial,chardev=saladtcp',
        ]
        log('starting DUT: %s', ' '.join(cmd))
        self.qemu = subprocess.Popen(cmd)

    def stop(self):
        # TODO, graceful, like the gateway code.
        self.qemu.terminate()
        self.qemu.wait()


def gen_mac(index):
    counter = format(index, '02x')
    return f'52:54:00:11:22:{counter}'


class PDUTCPHandler(socketserver.StreamRequestHandler):
    def handle(self):
        log("client: %s", self.client_address[0])
        try:
            data = self.rfile.read(4)
            if len(data) != 4:
                raise ValueError
            payload = int.from_bytes(data[:4], byteorder='big')
            log("payload: %s  %s", hex(payload), bin(payload))
        except ValueError:
            log("Bad input: %s", data)
            self.wfile.write(b'\x00')
            self.request.close()
            return

        # Protocol
        # [0:1] operation
        # [2:12] PDU port (0-1023)
        # [13:31] reserved, MUST BE CHECKED TO BE 0s
        # E.g., turn 2 off
        #   echo -e '\x00\x00\x00\x0A' | nc localhost 9191
        # And then on again,
        #   echo -e '\x00\x00\x00\x09' | nc localhost 9191
        cmd = payload & 0x03
        port = (payload & 0x1FFC) >> 2
        shutdown = (payload & 0x2000) == 0x2000
        reserved = (payload & 0xFFFFC000) >> 13
        assert(reserved == 0)

        if shutdown:
            setattr(self.server, '_BaseServer__shutdown_request', True)

        if not (port >= 0 and port < len(OUTLETS)):
            log("port %d out of range", port)
            self.wfile.write(b'\x00')
            return

        machine = OUTLETS[port]
        assert(machine)

        log("cmd=%s on port=%d", hex(cmd), port)

        if cmd & 0x03 == 3:
            log("status for port=%d", port)
            self.wfile.write(struct.pack('!B', int(machine['state'])))
        elif cmd & 0x01:
            log("turning port=%d ON", port)
            if machine['state'] == PowerState.ON:
                log('already ON')
                self.wfile.write(b'\x01')
            else:
                machine['instance'] = DUT(machine['mac'],
                                          machine['disk'])
                machine['state'] = PowerState.ON
                self.wfile.write(b'\x01')
                log("port=%d turned ON", port)
        elif cmd & 0x02:
            log("turning port=%d OFF", port)
            if machine['state'] == PowerState.OFF:
                log("already off")
                self.wfile.write(b'\x01')
            else:
                assert(machine['instance'])
                machine['instance'].stop()
                machine['state'] = PowerState.OFF
                self.wfile.write(b'\x01')
                log("port %d turned OFF", port)
        else:
            assert(cmd == 0)
            log("return num ports")
            self.wfile.write(struct.pack('!B', len(OUTLETS)))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog='Virtual PDU')
    parser.add_argument('--host', default='localhost')
    parser.add_argument('--port', default=9191, type=int)
    parser.add_argument('--num-ports', default=16, type=int)
    parser.add_argument('--log-file', default='vpdu.log', type=str)
    parser.add_argument('--log-level', default='INFO', type=str)
    parser.add_argument('--salad-console-port', default=8100, type=int)
    parser.add_argument('--dut-disk-size', default='32G', type=str,
                        help='In the format expected by qemu-img. Default 32G')

    args = parser.parse_args()

    SALAD_TCP_CONSOLE_PORT = args.salad_console_port
    DUT_DISK_SIZE = args.dut_disk_size

    OUTLETS = [
        {'mac': gen_mac(i),
         'disk': get_disk(i),
         'monitor_port': 4444 + i,
         'state': PowerState.OFF} for i in range(args.num_ports)
    ]

    socketserver.TCPServer.allow_reuse_address = True
    try:
        log("OK. Waiting for connections...")
        with socketserver.TCPServer((args.host, args.port), PDUTCPHandler) as server:
            server.allow_reuse_address = True
            server.serve_forever()
    except KeyboardInterrupt:
        log("Interrupt")
        pass
    finally:
        for machine in OUTLETS:
            os.remove(machine['disk'])
