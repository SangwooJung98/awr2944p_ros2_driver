"""TI SDK 4.x UART TLVs and DDM_ENET Cartesian stream.

The header and TLV lengths follow TI's SDK/Visualizer. TLV lengths exclude
the 8-byte TLV header. There is no packet checksum in this wire format.
"""
from dataclasses import dataclass
import math
import struct

MAGIC = bytes.fromhex('0201040306050807')
HEADER_SIZE = 40
MAX_PACKET_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class Point:
    x: float
    y: float
    z: float
    velocity: float
    snr: float = math.nan
    noise: float = math.nan


@dataclass(frozen=True)
class Frame:
    version: int
    platform: int
    number: int
    cpu_cycles: int
    subframe: int
    points: tuple
    packet_bytes: int
    stats: dict
    temperature: dict
    metadata_source: str = 'sensor'

    @property
    def sdk_version(self):
        if self.metadata_source != 'sensor':
            return 'unknown'
        return '.'.join(str((self.version >> shift) & 255) for shift in (24, 16, 8, 0))


def parse_packet(packet):
    if len(packet) < HEADER_SIZE or packet[:8] != MAGIC:
        raise ValueError('Missing mmWave header')
    version, size, platform, number, cycles, count, ntlv, subframe = struct.unpack_from('<8I', packet, 8)
    if size != len(packet) or not HEADER_SIZE <= size <= MAX_PACKET_BYTES:
        raise ValueError('Invalid total packet length')
    if ntlv > 64 or count > 65536:
        raise ValueError('Unreasonable TLV or point count')
    offset, coords, side, stats, temperature = HEADER_SIZE, None, None, {}, {}
    seen = set()
    for _ in range(ntlv):
        if offset + 8 > size:
            raise ValueError('Truncated TLV header')
        kind, length = struct.unpack_from('<II', packet, offset)
        offset += 8
        if length > size - offset:
            raise ValueError('TLV payload exceeds packet')
        body = memoryview(packet)[offset:offset + length]
        if kind in (1, 7) and kind in seen:
            raise ValueError('Duplicate point/side-info TLV')
        seen.add(kind)
        if kind == 1:
            if length != count * 16:
                raise ValueError('Point count and Cartesian payload length differ')
            coords = tuple(struct.iter_unpack('<4f', body))
            if not all(math.isfinite(value) for point in coords for value in point):
                raise ValueError('Non-finite Cartesian point or velocity')
        elif kind == 7:
            if length != count * 4:
                raise ValueError('Side-info count differs from point count')
            side = tuple(struct.iter_unpack('<2h', body))
        elif kind == 6:
            if length != 24:
                raise ValueError('Unexpected SDK 4.x statistics TLV size')
            stats = dict(zip(
                ('processing_us', 'transmit_us', 'frame_margin_us', 'chirp_margin_us',
                 'active_cpu_percent', 'interframe_cpu_percent'),
                struct.unpack_from('<6I', body)))
        elif kind == 9:
            if length < 8 or (length - 8) % 2:
                raise ValueError('Malformed temperature TLV')
            valid, device_ms = struct.unpack_from('<iI', body)
            names = ('rx0', 'rx1', 'rx2', 'rx3', 'tx0', 'tx1', 'tx2', 'pm', 'dig0', 'dig1')
            values = [v[0] for v in struct.iter_unpack('<h', body[8:])]
            temperature = {'valid': valid == 0, 'device_time_ms': device_ms,
                           'sensors_c': dict(zip(names, values)), 'raw_values_c': values}
        offset += length
    if coords is None and count:
        raise ValueError('Detected points TLV missing')
    points = tuple(Point(*point, *(tuple(value * 0.1 for value in side[i]) if side else (math.nan, math.nan)))
                   for i, point in enumerate(coords or ()))
    return Frame(version, platform, number, cycles, subframe, points, size, stats, temperature)


class StreamDecoder:
    """Incremental framing, including split magic words and concatenated packets."""
    def __init__(self):
        self.buffer = bytearray()
        self.invalid_packets = 0
        self.discarded_bytes = 0
        self.last_error = ''

    def reset(self):
        self.discarded_bytes += len(self.buffer)
        self.buffer.clear()

    def feed(self, data):
        self.buffer.extend(data)
        result = []
        while len(self.buffer) >= len(MAGIC):
            pos = self.buffer.find(MAGIC)
            if pos < 0:
                self.discarded_bytes += len(self.buffer) - 7
                del self.buffer[:-7]
                break
            if pos:
                self.discarded_bytes += pos
                del self.buffer[:pos]
            if len(self.buffer) < HEADER_SIZE:
                break
            size = struct.unpack_from('<I', self.buffer, 12)[0]
            count, ntlv = struct.unpack_from('<II', self.buffer, 28)
            if not HEADER_SIZE <= size <= MAX_PACKET_BYTES or count > 65536 or ntlv > 64:
                self.invalid_packets += 1
                self.last_error = 'Invalid frame header'
                self.discarded_bytes += 1
                del self.buffer[0]
                continue
            if len(self.buffer) < size:
                break
            try:
                frame = parse_packet(bytes(self.buffer[:size]))
            except ValueError as exc:
                self.invalid_packets += 1
                self.last_error = str(exc)
                self.discarded_bytes += 1
                del self.buffer[0]
                continue
            del self.buffer[:size]
            result.append(frame)
        return result


class EthernetDecoder:
    """SDK 4.7.2 enet_tcpclient.c: uint32 count + uint16 zero + count*4 floats.

    No magic, checksum, timestamp, sequence number, or side info is transmitted.
    Decoding must begin at the start of a TCP connection. A malformed frame is
    fatal: searching for a plausible count could silently invent radar points.
    """
    def __init__(self, max_points=65536):
        self.buffer = bytearray()
        self.max_points = max_points
        self.sequence = 0
        self.invalid_packets = 0
        self.discarded_bytes = 0
        self.last_error = ''

    def feed(self, data):
        self.buffer.extend(data)
        result = []
        while len(self.buffer) >= 6:
            count, reserved = struct.unpack_from('<IH', self.buffer)
            if count > self.max_points or reserved != 0:
                self.invalid_packets += 1
                raise ValueError('Invalid TI Ethernet header; reset sensor and reconnect (no resync marker)')
            size = 6 + 16 * count
            if len(self.buffer) < size:
                break
            coords = tuple(struct.iter_unpack('<4f', self.buffer[6:size]))
            if not all(math.isfinite(value) for point in coords for value in point):
                self.invalid_packets += 1
                raise ValueError('Non-finite Ethernet Cartesian point')
            del self.buffer[:size]
            self.sequence += 1
            result.append(Frame(0, 0, self.sequence, 0, 0,
                                tuple(Point(*p) for p in coords), size, {}, {},
                                metadata_source='host_sequence'))
        return result
