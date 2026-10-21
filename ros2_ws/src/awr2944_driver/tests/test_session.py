import os
import pty
import socket
import threading
import time
from collections import deque

import pytest

from awr2944_driver.cli import RadarCLI
from awr2944_driver.session import RadarSession, Settings
from awr2944_driver.transports import TCPServer
from .helpers import FakeCLI, FRAMES, PACKAGE, RAW, ethernet_bytes, wait_until


def test_cli_and_missing_ethernet_firmware():
    emulator = FakeCLI()
    cli = RadarCLI(emulator.path)
    try:
        cli.open()
        assert cli.sensor_state() == 0
        with pytest.raises(RuntimeError, match='no enetStreamCfg'):
            cli.require_ethernet()
    finally:
        cli.close()
        emulator.close()
    assert not emulator.errors


@pytest.mark.parametrize('help_text,supported', [
    ('Command: Help Description\r\n\tenetStreamCfg:\t<isEnabled> <remoteIpD> <remoteIpC> <remoteIpB> <remoteIpA>\r\nDone\r\nmmwDemo:/>', True),
    ('help\n  enetStreamCfg : <isEnabled>\nDone\nmmwDemo:/>', True),
    ('enetStreamCfg: <isEnabled>\nDone\nmmwDemo:/>', True),
    ('help\n\tsensorStart: <doReconfig>\nDone\nmmwDemo:/>', False),
    ('help\n\totherCommand: mentions enetStreamCfg: in its description\nDone\nmmwDemo:/>', False),
])
def test_ethernet_capability_accepts_ti_help_indentation(help_text, supported):
    cli = RadarCLI('unused')
    cli.command = lambda _: help_text
    if supported:
        cli.require_ethernet()
    else:
        with pytest.raises(RuntimeError, match='no enetStreamCfg'):
            cli.require_ethernet()


def test_cli_synchronizes_stale_input_before_first_command():
    class Port:
        def __init__(self):
            self.reads = deque([b"garbage is not recognized\r\nmmwDemo:/>",
                                b'\n\nmmwDemo:/>'])
            self.writes = []
            self.resets = 0
        @property
        def in_waiting(self):
            return len(self.reads[0]) if self.reads else 0
        def write(self, data):
            self.writes.append(data)
        def flush(self):
            pass
        def read(self, _):
            if self.reads:
                return self.reads.popleft()
            time.sleep(0.05)
            return b''
        def reset_input_buffer(self):
            self.resets += 1
    cli = RadarCLI('unused')
    cli.port = Port()
    cli.synchronize()
    assert cli.port.writes == [b'\r\n']
    assert not cli.port.reads
    assert cli.port.resets == 1


def test_stop_reconnects_and_verifies_after_truncated_command():
    emulator = FakeCLI(state=2, stop_failures=1)
    cli = RadarCLI(emulator.path)
    try:
        cli.open()
        cli.stop_sensor()
        assert emulator.state == 3
        assert emulator.commands.count('sensorStop') == 2
        assert emulator.commands[-1] == 'queryDemoStatus'
    finally:
        cli.close()
        emulator.close()


def test_uart_commands_stream_stop_and_resume():
    master, slave = pty.openpty()
    def send(command):
        if command.startswith('sensorStart'):
            # A PTY has a small buffer; send one full real packet after ACK.
            os.write(master, RAW[:FRAMES[0].packet_bytes])
    emulator = FakeCLI(callback=send)
    frames = []
    session = RadarSession(Settings(cli_port=emulator.path, data_port=os.ttyname(slave),
                          config_file=str(PACKAGE / 'config/usb_4_6_2.cfg'),
                          max_run_seconds=0.2, data_timeout=1.0), frames.append)
    try:
        for count in (1, 2):
            assert session.start()[0]
            wait_until(lambda: not session.thread.is_alive())
            assert session.snapshot()['state'] == 'stopped', session.snapshot()
            assert session.snapshot()['stop_confirmed']
            assert len(frames) == count
        assert 'sensorStart 0' in emulator.commands
        assert emulator.commands.count('flushCfg') == 1
        assert emulator.commands.count('sensorStop') == 2
    finally:
        session.close()
        emulator.close()
        os.close(master)
        os.close(slave)


def test_no_data_requests_rf_stop():
    master, slave = pty.openpty()
    emulator = FakeCLI()
    session = RadarSession(Settings(cli_port=emulator.path, data_port=os.ttyname(slave),
                          config_file=str(PACKAGE / 'config/usb_4_6_2.cfg'),
                          data_timeout=0.2), lambda _: None)
    try:
        session.start()
        wait_until(lambda: not session.thread.is_alive())
        assert session.snapshot()['state'] == 'error'
        assert session.snapshot()['stop_confirmed']
        assert 'No valid' in session.snapshot()['detail']
    finally:
        session.close()
        emulator.close()
        os.close(master)
        os.close(slave)


def test_ethernet_control_connects_before_rf(monkeypatch):
    servers = []
    def high_port_server(host, port, peer):
        assert port == 7
        server = TCPServer(host, 0, peer)  # Only privileged bind is substituted.
        servers.append(server)
        return server
    monkeypatch.setattr('awr2944_driver.session.TCPServer', high_port_server)
    connections = []
    def react(command):
        if command.startswith('enetStreamCfg'):
            connections.append(socket.create_connection(servers[0].address))
        elif command == 'sensorStart':
            assert connections
            connections[0].sendall(ethernet_bytes(FRAMES[:2]))
    emulator = FakeCLI(enet=True, callback=react)
    received = []
    session = RadarSession(Settings(transport='ethernet', host_ip='127.0.0.1', radar_ip='127.0.0.1',
                          cli_port=emulator.path, config_file=str(PACKAGE / 'config/ethernet_4_7_2.cfg'),
                          max_run_seconds=0.2, data_timeout=1.0), received.append)
    try:
        session.start()
        wait_until(lambda: not session.thread.is_alive())
        assert len(received) == 2, session.snapshot()
        assert session.snapshot()['stop_confirmed']
        assert emulator.commands.index('enetStreamCfg 1 127 0 0 1') < emulator.commands.index('sensorStart')
        session.start()
        wait_until(lambda: not session.thread.is_alive())
        assert 'Reset the board' in session.snapshot()['detail']
    finally:
        session.close()
        emulator.close()
        for connection in connections:
            connection.close()


def test_stop_during_tcp_accept():
    with socket.socket() as reserve:
        reserve.bind(('127.0.0.1', 0))
        port = reserve.getsockname()[1]
    session = RadarSession(Settings(transport='ethernet', configure_sensor=False,
                          host_ip='127.0.0.1', radar_ip='127.0.0.1', tcp_port=port), lambda _: None)
    session.start()
    wait_until(lambda: session.snapshot()['state'] == 'connecting')
    start = time.monotonic()
    assert session.close()
    assert time.monotonic() - start < 1
    assert session.snapshot()['state'] == 'stopped'


def test_unsafe_or_unsupported_parameter_combinations():
    with pytest.raises(ValueError, match='port 7'):
        Settings(transport='ethernet', tcp_port=7007).validate()
    with pytest.raises(ValueError, match='temperature'):
        Settings(transport='ethernet', max_temperature_c=70.0).validate()


def test_replay_loop_preserves_frame_period(tmp_path):
    path = tmp_path / 'one-frame.bin'
    path.write_bytes(RAW[:FRAMES[0].packet_bytes])
    times = []
    def receive(_):
        times.append(time.monotonic())
        if len(times) == 4:
            session.stop()
    session = RadarSession(Settings(transport='replay', replay_file=str(path),
                                   replay_loop=True, replay_rate_hz=10.0), receive)
    session.start()
    wait_until(lambda: not session.thread.is_alive())
    assert len(times) == 4
    assert all(b - a >= 0.075 for a, b in zip(times, times[1:]))
