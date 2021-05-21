import time
import socket
import struct
from contextlib import contextmanager
from argparse import ArgumentParser

parser = ArgumentParser()
parser.add_argument('--host', default='localhost')
parser.add_argument('--port', default=9191, type=int)
parser.add_argument('--outlet', type=int)
parser.add_argument('--all', action='store_true')
parser.add_argument('--status', action='store_true')
parser.add_argument('--reboot', action='store_true')
parser.add_argument('--on', action='store_true')
parser.add_argument('--off', action='store_true')
args = parser.parse_args()

print("Connecting to %s:%d" % (args.host, args.port))

@contextmanager
def conn(host, port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    s.connect((host, port))
    try:
        yield s
    finally:
        s.close()


with conn(args.host, args.port) as c:
    c.sendall((0).to_bytes(4, byteorder='big'))
    num_ports = int(c.recv(1)[0])


if args.outlet:
    assert(args.outlet >= 0 and args.outlet <= num_ports)

print(num_ports, "outlets available on the PDU")
if args.status:
    cmd = args.outlet << 2 | 0x03
    with conn(args.host, args.port) as s:
        s.sendall(cmd.to_bytes(4, byteorder='big'))
        state = int(s.recv(1)[0])
    print("port state %x" % state)
    if state == 0x03:
        print("ON")
    elif state == 0x04:
        print("OFF")
    elif state == 0x05:
        print("UNKNOWN")
    else:
        assert(False)
if args.off or args.reboot:
    if args.all:
        print("turning off all ports")
        for outlet in range(num_ports):
            cmd = (outlet << 2) | 0x02
            with conn(args.host, args.port) as s:
                s.sendall(cmd.to_bytes(4, byteorder='big'))
                assert(s.recv(1)[0] == 0x01)
                print('%2d turned off' % outlet)
    else:
        cmd = (args.outlet << 2) | 0x02
        with conn(args.host, args.port) as s:
            s.sendall(cmd.to_bytes(4, byteorder='big'))
            assert(s.recv(1)[0] == 0x01)
            print(args.outlet, "turned off")
if args.on or args.reboot:
    if args.all:
        print("turning on all ports")
        for outlet in range(num_ports):
            cmd = (outlet << 2) | 0x01
            with conn(args.host, args.port) as s:
                s.sendall(cmd.to_bytes(4, byteorder='big'))
                assert(s.recv(1)[0] == 0x01)
                print('%2d turned on' % outlet)
    else:
        cmd = (args.outlet << 2) | 0x01
        with conn(args.host, args.port) as s:
            s.sendall(cmd.to_bytes(4, byteorder='big'))
            assert(s.recv(1)[0] == 0x01)
            print(args.outlet, "turned on")
