"""Bounded TI demo command transactions; never flashes the board."""
import re
import time

import serial


class RadarCLI:
    def __init__(self, path, baud=115200, logger=None):
        self.path, self.baud = path, baud
        self.logger = logger or (lambda _: None)
        self.port = None

    def open(self):
        port = serial.Serial(port=None, baudrate=self.baud, timeout=0.05,
                             write_timeout=1, exclusive=True)
        port.dtr, port.rts, port.port = True, False, self.path
        try:
            port.open()
            port.reset_input_buffer()
            self.port = port
            self.synchronize()
        except Exception:
            port.close()
            self.port = None
            raise

    def synchronize(self):
        """Finish any stale input line and consume both CR/LF prompts at open.

        Clearing the host RX buffer alone does not clear the firmware's CLI
        input line after a USB reconnect. Never retry configuration/start here.
        """
        time.sleep(0.1)  # Allow XDS110's UART line coding to settle.
        self.port.write(b'\r\n')
        self.port.flush()
        response = bytearray()
        deadline = time.monotonic() + 2.0
        last_data = time.monotonic()
        while time.monotonic() < deadline:
            chunk = self.port.read(min(self.port.in_waiting or 1, 4096))
            if chunk:
                response.extend(chunk)
                last_data = time.monotonic()
                if len(response) > 65536:
                    raise RuntimeError('CLI synchronization response too long')
            if b'mmwDemo:/>' in response and time.monotonic() - last_data >= 0.1:
                self.port.reset_input_buffer()
                return
        raise RuntimeError('No mmWave CLI prompt after USB synchronization')

    def close(self):
        if self.port:
            self.port.close()
            self.port = None

    def command(self, line, timeout=3.0):
        if not self.port or not self.port.is_open:
            raise RuntimeError('CLI port is not open')
        self.port.reset_input_buffer()
        self.port.write((line + '\n').encode('ascii'))
        self.port.flush()
        response = bytearray()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            response.extend(self.port.read(min(self.port.in_waiting or 1, 4096)))
            if len(response) > 65536:
                raise RuntimeError(f'CLI response too long: {line.split()[0]}')
            if response.rstrip().endswith(b'mmwDemo:/>') and (
                    b'Done' in response or b'Error' in response or b'not recognized' in response):
                break
        text = response.decode('utf-8', errors='replace')
        self.logger(f'{line} -> {text.strip()}')
        if 'Done' not in text or re.search(r'\b(error|exception|assert|ignored)\b|not recognized', text, re.I):
            raise RuntimeError(f'CLI rejected {line!r}: {text.strip() or "timeout/no response"}')
        return text

    def sensor_state(self, timeout=3.0):
        text = self.command('queryDemoStatus', timeout=timeout)
        match = re.search(r'Sensor State:\s*([0-3])\b', text)
        if not match:
            raise RuntimeError('queryDemoStatus did not report a supported sensor state')
        return int(match.group(1))

    def stop_sensor(self):
        """Re-synchronize the idle USB CLI, then verify RF is actually stopped.

        On this XDS110/SDK combination the first command after streaming can
        arrive truncated. Only the idempotent stop operation is retried, never
        configuration or sensorStart. A Done token alone is not confirmation.
        """
        failures = []
        for attempt in range(2):
            try:
                self.close()
                self.open()
                if self.sensor_state(timeout=1.0) != 2:
                    return
                self.command('sensorStop', timeout=2.0)
                if self.sensor_state(timeout=1.0) != 3:
                    raise RuntimeError('Sensor state did not become STOPPED')
                return
            except Exception as exc:
                failures.append(str(exc))
                self.logger(f'Stop verification attempt {attempt + 1} failed: {exc}')
        raise RuntimeError('; '.join(failures))

    def require_ethernet(self):
        text = self.command('help')
        if not re.search(r'^[ \t]*enetStreamCfg[ \t]*:', text, re.M):
            raise RuntimeError(
                'Firmware help lists no enetStreamCfg command. Ethernet mode requires '
                'the AWR2944P DDM_ENET demo; check the connected board and running firmware.')


def profile_commands(path):
    commands = []
    for raw in path.read_text().splitlines():
        line = raw.split('%', 1)[0].strip()
        if not line or line.startswith('#'):
            continue
        if not line.isascii():
            raise ValueError('Radar profile commands must be ASCII')
        commands.append(line)
    if not any(line.split()[0] == 'profileCfg' for line in commands):
        raise ValueError('No profileCfg in radar configuration')
    if not any(line.split()[0] == 'frameCfg' for line in commands):
        raise ValueError('This driver requires a legacy frameCfg profile')
    if not any(line.split()[0] == 'sensorStart' for line in commands):
        raise ValueError('Configuration has no sensorStart')
    return commands
