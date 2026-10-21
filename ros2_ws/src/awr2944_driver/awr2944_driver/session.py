"""Hardware control and replay, independent of the ROS executor."""
from dataclasses import dataclass
import ipaddress
from pathlib import Path
import threading
import time

from .cli import RadarCLI, profile_commands
from .protocol import EthernetDecoder, StreamDecoder
from .transports import TCPServer, UARTStream


@dataclass(frozen=True)
class Settings:
    transport: str = 'uart'
    config_file: str = ''
    cli_port: str = '/dev/ttyACM0'
    data_port: str = '/dev/ttyACM1'
    cli_baud: int = 115200
    data_baud: int = 3125000
    host_ip: str = '192.168.1.10'
    radar_ip: str = '192.168.1.200'
    tcp_port: int = 7
    configure_sensor: bool = True
    resume_existing_config: bool = False
    connect_timeout: float = 15.0
    data_timeout: float = 3.0
    max_run_seconds: float = 60.0
    max_temperature_c: float = 0.0
    replay_file: str = ''
    replay_rate_hz: float = 10.0
    replay_loop: bool = False

    def validate(self):
        if self.transport not in ('uart', 'ethernet', 'replay'):
            raise ValueError('transport must be uart, ethernet or replay')
        if self.connect_timeout <= 0 or self.data_timeout <= 0 or self.replay_rate_hz <= 0:
            raise ValueError('Timeouts and replay rate must be positive')
        if self.max_run_seconds < 0 or self.max_temperature_c < 0:
            raise ValueError('Run/temperature limits cannot be negative; zero disables the limit')
        if self.transport == 'ethernet':
            ipaddress.IPv4Address(self.host_ip)
            if self.radar_ip:
                ipaddress.IPv4Address(self.radar_ip)
            if not 1 <= self.tcp_port <= 65535:
                raise ValueError('tcp_port must be 1..65535')
            if self.configure_sensor and self.tcp_port != 7:
                raise ValueError('Stock TI firmware connects only to TCP port 7')
            if self.max_temperature_c:
                raise ValueError('Ethernet firmware does not transmit temperature; use max_run_seconds')


class RadarSession:
    def __init__(self, settings, on_frame, logger=None):
        settings.validate()
        self.settings, self.on_frame = settings, on_frame
        self.logger = logger or (lambda _: None)
        self.stop_event = threading.Event()
        self.thread = None
        self.lock = threading.Lock()
        self.configured = False
        self.decoder = None
        self.status = {'state': 'idle', 'detail': 'Waiting for /radar/start',
                       'frames': 0, 'points': 0, 'bytes': 0, 'frame_gaps': 0,
                       'sequence_resets': 0, 'invalid_packets': 0,
                       'discarded_bytes': 0, 'stop_confirmed': False}

    def snapshot(self):
        with self.lock:
            return dict(self.status)

    def update(self, **values):
        with self.lock:
            self.status.update(values)

    def start(self):
        if self.thread and self.thread.is_alive():
            return False, 'A radar session is already active'
        self.stop_event.clear()
        self.update(state='starting', detail='Opening configured transport',
                    frames=0, points=0, bytes=0, frame_gaps=0, sequence_resets=0,
                    invalid_packets=0, discarded_bytes=0, stop_confirmed=False)
        self.thread = threading.Thread(target=self._run, name='radar-receiver', daemon=True)
        self.thread.start()
        return True, 'Start accepted; check /radar/diagnostics for connection result'

    def stop(self):
        self.stop_event.set()
        return True, 'Stop requested; diagnostics reports whether sensorStop was acknowledged'

    def close(self):
        self.stop()
        if self.thread:
            self.thread.join(timeout=25)
        return not self.thread or not self.thread.is_alive()

    def _check_cancel(self):
        if self.stop_event.is_set():
            raise InterruptedError('Stop requested')

    def _configure(self, cli, stream):
        cfg = self.settings
        state = cli.sensor_state()
        if state == 2:
            raise RuntimeError('Sensor is already running; stop its current owner before starting this driver')
        if cfg.transport == 'ethernet':
            cli.require_ethernet()
            self.update(firmware_network=cli.command('queryLocalIp').strip())
            if state == 3:
                raise RuntimeError('Reset the board before a new Ethernet session: stock TI TCP client does not reconnect')
        if state == 3:
            if not (self.configured or cfg.resume_existing_config):
                raise RuntimeError('Sensor was stopped with an unknown configuration. Reset board to apply this profile, '
                                   'or explicitly set resume_existing_config:=true to reuse the board configuration')
            if cfg.transport == 'uart':
                cli.command(f'configDataPort {cfg.data_baud} 0')
            return 'sensorStart 0'
        commands = profile_commands(Path(cfg.config_file))
        for command in commands:
            self._check_cancel()
            if command.split()[0] in ('sensorStart', 'sensorStop', 'enetStreamCfg', 'configDataPort'):
                continue
            cli.command(command)
        if cfg.transport == 'uart':
            cli.command(f'configDataPort {cfg.data_baud} 0')
        else:
            cli.command('enetStreamCfg 1 ' + cfg.host_ip.replace('.', ' '))
            # The firmware attempts TCP connection only once; listener is already open.
            self.update(state='connecting', detail='Waiting for radar TCP client, before enabling RF')
            if not stream.accept(self.stop_event, cfg.connect_timeout):
                raise InterruptedError('Stopped while waiting for TCP')
        return 'sensorStart'

    def _emit(self, frame):
        s = self.snapshot()
        self.update(frames=s['frames'] + 1, points=s['points'] + len(frame.points),
                    invalid_packets=self.decoder.invalid_packets,
                    discarded_bytes=self.decoder.discarded_bytes)
        self.on_frame(frame)

    def _replay(self):
        cfg = self.settings
        path = Path(cfg.replay_file)
        if not path.is_file():
            raise FileNotFoundError(f'Replay file not found: {path}')
        self.update(state='replaying', detail=str(path))
        deadline = time.monotonic()
        while not self.stop_event.is_set():
            self.decoder = StreamDecoder()
            count = 0
            with path.open('rb') as source:
                for chunk in iter(lambda: source.read(65536), b''):
                    self.update(bytes=self.snapshot()['bytes'] + len(chunk))
                    for frame in self.decoder.feed(chunk):
                        if self.stop_event.wait(max(0, deadline - time.monotonic())):
                            return
                        self._emit(frame)
                        count += 1
                        deadline += 1.0 / cfg.replay_rate_hz
            if self.decoder.buffer or self.decoder.invalid_packets or not count:
                raise ValueError('Replay contains truncated/corrupt/no radar frames')
            if not cfg.replay_loop:
                self.update(state='completed', detail='Replay finished')
                return

    def _run(self):
        cfg = self.settings
        cli, stream, own_sensor = None, None, False
        final_state, final_detail = 'stopped', 'Stopped'
        try:
            if cfg.transport == 'replay':
                self._replay()
                final_state = self.snapshot()['state'] if not self.stop_event.is_set() else 'stopped'
                final_detail = self.snapshot()['detail'] if not self.stop_event.is_set() else 'Replay stopped'
                return
            self.decoder = EthernetDecoder() if cfg.transport == 'ethernet' else StreamDecoder()
            if cfg.configure_sensor:
                cli = RadarCLI(cfg.cli_port, cfg.cli_baud, self.logger)
                cli.open()
                self.update(firmware=cli.command('version').strip())
            stream = (TCPServer(cfg.host_ip, cfg.tcp_port, cfg.radar_ip)
                      if cfg.transport == 'ethernet' else UARTStream(cfg.data_port, cfg.data_baud))
            if cli:
                start_command = self._configure(cli, stream)
                self._check_cancel()
                # Mark ownership before sending: a lost ACK must still trigger sensorStop.
                own_sensor = True
                cli.command(start_command, timeout=8.0)
                self.configured = True
            elif cfg.transport == 'ethernet':
                self.update(state='connecting', detail='Passive TCP receiver waiting for externally configured radar')
                if not stream.accept(self.stop_event, cfg.connect_timeout):
                    raise InterruptedError('Stopped while waiting for TCP')
            self.update(state='running', detail='Receiving radar frames')
            started = last_frame = time.monotonic()
            previous = None
            while not self.stop_event.is_set():
                now = time.monotonic()
                if cfg.max_run_seconds and now - started >= cfg.max_run_seconds:
                    final_detail = 'Configured run time reached'
                    break
                chunk = stream.read()
                if chunk:
                    self.update(bytes=self.snapshot()['bytes'] + len(chunk))
                    for frame in self.decoder.feed(chunk):
                        last_frame = time.monotonic()
                        if frame.metadata_source == 'sensor' and previous is not None:
                            delta = (frame.number - previous) & 0xffffffff
                            s = self.snapshot()
                            if 1 < delta < 0x80000000:
                                self.update(frame_gaps=s['frame_gaps'] + delta - 1)
                            elif delta != 1:
                                self.update(sequence_resets=s['sequence_resets'] + 1)
                        previous = frame.number
                        self._emit(frame)
                        temps = frame.temperature
                        if temps.get('valid') and temps.get('raw_values_c'):
                            hottest = max(temps['raw_values_c'])
                            self.update(temperature_c=hottest)
                            if cfg.max_temperature_c and hottest >= cfg.max_temperature_c:
                                raise RuntimeError(f'Configured temperature stop limit reached: {hottest} C')
                if time.monotonic() - last_frame > cfg.data_timeout:
                    raise TimeoutError('No valid point-cloud frames within data_timeout; requesting sensorStop')
        except InterruptedError as exc:
            final_detail = str(exc)
        except Exception as exc:
            final_state, final_detail = 'error', str(exc)
            self.logger(f'ERROR: {exc}')
        finally:
            # Release XDS110's high-rate data port before re-synchronizing CLI.
            # RF is still stopped explicitly below; closing USB alone cannot stop it.
            if stream and cfg.transport == 'uart':
                try:
                    stream.close()
                except Exception as exc:
                    self.logger(f'Data port close failed: {exc}')
            if cli and own_sensor:
                try:
                    cli.stop_sensor()
                    self.update(stop_confirmed=True)
                except Exception as exc:
                    final_state = 'error'
                    final_detail += f'; sensorStop not confirmed: {exc}'
            if stream:
                stream.close()
            if cli:
                cli.close()
            if self.decoder:
                self.update(invalid_packets=self.decoder.invalid_packets,
                            discarded_bytes=self.decoder.discarded_bytes)
            self.update(state=final_state, detail=final_detail)
