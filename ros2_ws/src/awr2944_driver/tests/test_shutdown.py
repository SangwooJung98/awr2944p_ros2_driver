"""A real node subprocess must finish RF stop despite repeated terminal signals."""
import os
import pty
import signal
import subprocess
import sys
import time

from .helpers import FakeCLI, FRAMES, PACKAGE, RAW, wait_until


def test_repeated_sigint_completes_sensor_stop():
    master, slave = pty.openpty()
    def send(command):
        if command == 'sensorStart':
            os.write(master, RAW[:FRAMES[0].packet_bytes])
    emulator = FakeCLI(callback=send)
    proc = subprocess.Popen([
        sys.executable, '-m', 'awr2944_driver.node', '--ros-args',
        '-p', 'auto_start:=true', '-p', f'cli_port:={emulator.path}',
        '-p', f'data_port:={os.ttyname(slave)}',
        '-p', f'config_file:={PACKAGE / "config/usb_4_6_2.cfg"}',
    ], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        wait_until(lambda: emulator.state == 2)
        proc.send_signal(signal.SIGINT)
        time.sleep(0.01)
        proc.send_signal(signal.SIGINT)
        output, _ = proc.communicate(timeout=10)
        assert proc.returncode == 0, output
        assert 'sensorStop' in emulator.commands, output
        assert emulator.commands[-1] == 'queryDemoStatus', output
        assert emulator.state == 3
        assert 'Traceback' not in output
    finally:
        if proc.poll() is None:
            proc.terminate()
            proc.wait(10)
        emulator.close()
        os.close(master)
        os.close(slave)
