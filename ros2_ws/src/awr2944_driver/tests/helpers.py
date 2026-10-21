import os
from pathlib import Path
import pty
import select
import struct
import threading
import time

from awr2944_driver.protocol import StreamDecoder

PACKAGE = Path(__file__).resolve().parents[1]
RAW = (PACKAGE / 'data' / 'synthetic_uart.bin').read_bytes()
FRAMES = StreamDecoder().feed(RAW)


def ethernet_bytes(frames=FRAMES):
    return b''.join(struct.pack('<IH', len(f.points), 0) +
                    b''.join(struct.pack('<4f', p.x, p.y, p.z, p.velocity) for p in f.points)
                    for f in frames)


def wait_until(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError('Timed out waiting for test condition')


class FakeCLI:
    def __init__(self, state=0, enet=False, callback=None, stop_failures=0):
        self.master, self.slave = pty.openpty()
        self.path = os.ttyname(self.slave)
        self.state, self.enet, self.callback = state, enet, callback
        self.stop_failures = stop_failures
        self.commands, self.errors = [], []
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        pending = bytearray()
        try:
            while not self.stop.is_set():
                if not select.select([self.master], [], [], 0.1)[0]:
                    continue
                pending.extend(os.read(self.master, 4096))
                while b'\n' in pending:
                    line, _, rest = pending.partition(b'\n')
                    pending[:] = rest
                    command = line.decode().strip()
                    if not command:
                        os.write(self.master, b'\r\nmmwDemo:/>')
                        continue
                    self.commands.append(command)
                    extra = ''
                    if command == 'version':
                        extra = 'Platform: AWR294X\nmmWave SDK Version: 04.07.02.01\n'
                    elif command == 'queryDemoStatus':
                        extra = f'Sensor State: {self.state}\n'
                    elif command == 'help':
                        extra = ('\tenetStreamCfg:\t<isEnabled> <ip octets>\r\n' if self.enet
                                 else '\tsensorStart:\t<doReconfig>\r\n')
                    elif command == 'queryLocalIp':
                        extra = 'Local IP Address: 192.168.1.200\n'
                    elif command.startswith('sensorStart'):
                        self.state = 2
                    elif command == 'sensorStop':
                        if self.stop_failures:
                            self.stop_failures -= 1
                            extra = "'s' is not recognized as a CLI command\n"
                        else:
                            self.state = 3
                    os.write(self.master, (command + '\n' + extra + 'Done\nmmwDemo:/>').encode())
                    if self.callback:
                        self.callback(command)
        except Exception as exc:
            if not self.stop.is_set():
                self.errors.append(exc)

    def close(self):
        self.stop.set()
        self.thread.join(2)
        os.close(self.master)
        os.close(self.slave)
