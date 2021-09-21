from datetime import datetime
import enum
import os
import socket
import socketserver
import struct
import subprocess
import sys
import time

BRIDGE = 'br0'


def check_bridge():
    global BRIDGE
    try:
        subprocess.check_call(['ip', 'link', 'show', BRIDGE])
    except:
        subprocess.check_call(['ip', 'link', 'add', 'name', BRIDGE, 'type', 'bridge'])
        subprocess.check_call(['ip', 'addr', 'add', '10.42.0.1/24', 'dev', BRIDGE])
        subprocess.check_call(['ip', 'link', 'set', BRIDGE, 'up'])


def get_disk(index):
    hda = f'dut_disk{index}.qcow2'
    if not os.path.exists(hda):
        subprocess.run(['qemu-img', 'create', '-f', 'qcow2', hda, '32G'])
    return hda


class PowerState(enum.IntEnum):
    ON = 3
    OFF = 4
    ERROR = 5


def gen_mac(index):
    counter = format(index, '02x')
    return f'52:54:00:11:22:{counter}'


check_bridge()
OUTLETS = [
    {'mac': gen_mac(i),
     'disk': get_disk(i),
     'serial_sock': f'/run/salad_socks/machine{i}.socket',
     'state': PowerState.OFF} for i in range(16)
]

def cleanup():
    global OUTLETS
    for machine in OUTLETS:
        os.remove(machine['disk'])


def reset_stdout():
    try:
        device = os.ttyname(sys.stdout)
        subprocess.call(["stty", "sane", "-F", device])
    except:
        pass


class DUT:
    def __init__(self, mac, disk, serial_sock):
        self.disk = disk
        log_name = datetime.now().strftime(f'dut-log-{mac.replace(":", "")}-%H%M%S-%d%m%Y.log')
        cmd = [
                'qemu-system-x86_64',
                '-machine', 'pc-q35-6.0,accel=kvm',
                '-m', '1024',
                '-smp', '2,sockets=2,cores=1,threads=1',
                '-hda', disk,
	        '-chardev', f'file,id=logfile,path={log_name}',
                '-chardev', f'socket,id=foo,path={serial_sock},server=on,wait=off,logfile={log_name}',
                '-device', 'pci-serial,chardev=foo',
                '-nic', f'bridge,br=vivianbr0,mac={mac},model=virtio-net-pci',
                '-vga', 'virtio',
             ]
        print('starting DUT:', ' '.join(cmd))
        self.qemu = subprocess.Popen(cmd)


    def stop(self):
        self.qemu.terminate()
        self.qemu.wait()
        reset_stdout()


class PDUTCPHandler(socketserver.StreamRequestHandler):
    def handle(self):
        print("client: {}".format(self.client_address[0]))
        try:
            data = self.rfile.read(4)
            if len(data) != 4:
                raise ValueError
            payload = int.from_bytes(data[:4], byteorder='big')
            print("payload:", hex(payload))
        except ValueError:
            print("Bad input", data)
            self.wfile.write(b'\x00')
            self.request.close()
            return

        # Protocol
        # [0:2) operation
        # [2:12) PDU port (0-1023)
        # [12:32) reserved, MUST BE CHECKED TO BE 0s
        # E.g., turn 2 off
        #   echo -e '\x00\x00\x00\x0A' | nc localhost 9191
        # And then on again,
        #   echo -e '\x00\x00\x00\x09' | nc localhost 9191
        cmd = payload & 0x03
        port = (payload & 0x1FFC) >> 2
        reserved = (payload & 0xFFFFE000) >> 12
        assert(reserved == 0)

        if not (port >= 0 and port < len(OUTLETS)):
            print(port, "out of range")
            self.wfile.write(b'\x00')
            return

        machine = OUTLETS[port]
        assert(machine)

        print("cmd=", hex(cmd), "port=", port)

        if cmd & 0x03 == 3:
            print(f"status for {port}")
            self.wfile.write(struct.pack('!B', int(machine['state'])))
        elif cmd & 0x01:
            print(f"turning {port} ON")
            if machine['state'] == PowerState.ON:
                print('already ON')
                self.wfile.write(b'\x01')
            else:
                machine['instance'] = DUT(machine['mac'],
                                          machine['disk'],
                                          machine['serial_sock'])
                machine['state'] = PowerState.ON
                self.wfile.write(b'\x01')
                print(port, "turned ON")
        elif cmd & 0x02:
            print(f"turning {port} OFF")
            if machine['state'] == PowerState.OFF:
                print("already off")
                self.wfile.write(b'\x01')
            else:
                assert(machine['instance'])
                machine['instance'].stop()
                machine['state'] = PowerState.OFF
                self.wfile.write(b'\x01')
                print(port, "turned OFF")
        else:
            assert(cmd == 0)
            print("return num ports")
            self.wfile.write(struct.pack('!B', len(OUTLETS)))


if __name__ == "__main__":
    HOST, PORT = "localhost", 9191

    # Create the server, binding to localhost on port 9999
    try:
        socketserver.TCPServer.allow_reuse_address = True
        with socketserver.TCPServer((HOST, PORT), PDUTCPHandler) as server:
            server.allow_reuse_address = True
            server.serve_forever()
    except KeyboardInterrupt:
        print("Wait while resources are cleared...")
        cleanup()
