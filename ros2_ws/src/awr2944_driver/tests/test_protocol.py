import csv
from pathlib import Path
import struct

import pytest

from awr2944_driver.protocol import MAGIC, StreamDecoder, parse_packet

CAPTURE = Path(__file__).resolve().parents[1] / 'data'


@pytest.fixture(scope='module')
def raw():
    return (CAPTURE / 'synthetic_uart.bin').read_bytes()


@pytest.mark.parametrize('chunk_size', [1, 7, 39, 40, 511, 8192, 1000000])
def test_synthetic_80_frame_stream_at_arbitrary_boundaries(raw, chunk_size):
    decoder = StreamDecoder()
    frames = []
    for start in range(0, len(raw), chunk_size):
        frames.extend(decoder.feed(raw[start:start + chunk_size]))
    assert [frame.number for frame in frames] == list(range(1, 81))
    assert sum(len(frame.points) for frame in frames) == 2400
    assert decoder.invalid_packets == decoder.discarded_bytes == len(decoder.buffer) == 0
    assert frames[0].sdk_version == '4.6.2.1'


def test_every_point_matches_independent_fixture_csv(raw):
    points = [(frame.number, point) for frame in StreamDecoder().feed(raw) for point in frame.points]
    with (CAPTURE / 'synthetic_points.csv').open() as file:
        reference = list(csv.DictReader(file))
    assert len(reference) == len(points)
    for (number, point), row in zip(points, reference):
        assert number == int(row['frame'])
        assert (point.x, point.y, point.z, point.velocity, point.snr, point.noise) == pytest.approx(
            [float(row[k]) for k in ('x_m', 'y_m', 'z_m', 'doppler_m_s', 'snr_db', 'noise_db')])


def test_noise_corrupt_header_and_split_magic_resynchronize(raw):
    decoder = StreamDecoder()
    corrupt = MAGIC + struct.pack('<8I', 0x04060201, 0xffffffff, 0x2944, 0, 0, 0, 0, 0)
    assert decoder.feed(b'garbage' + corrupt + raw[:5]) == []
    frames = decoder.feed(raw[5:])
    assert len(frames) == 80
    assert decoder.invalid_packets == 1
    assert decoder.discarded_bytes == len(b'garbage') + len(corrupt)


def test_invalid_tlv_does_not_publish_corrupt_cloud(raw):
    size = struct.unpack_from('<I', raw, 12)[0]
    corrupt = bytearray(raw[:size])
    struct.pack_into('<I', corrupt, 44, size + 1)
    decoder = StreamDecoder()
    frames = decoder.feed(corrupt + raw[size:])
    assert len(frames) == 79
    assert frames[0].number == 2
    assert decoder.invalid_packets == 1


def test_zero_point_frame_is_valid():
    packet = MAGIC + struct.pack('<8I', 0x04070001, 40, 0x2944, 123, 0, 0, 0, 0)
    assert parse_packet(packet).points == ()


def test_truncated_frame_is_retained_until_complete(raw):
    size = struct.unpack_from('<I', raw, 12)[0]
    decoder = StreamDecoder()
    assert decoder.feed(raw[:size - 1]) == []
    assert len(decoder.feed(raw[size - 1:size])) == 1


def test_nonfinite_point_rejected(raw):
    size = struct.unpack_from('<I', raw, 12)[0]
    packet = bytearray(raw[:size])
    struct.pack_into('<f', packet, 48, float('nan'))
    with pytest.raises(ValueError, match='Non-finite'):
        parse_packet(packet)
