import math
import socket
import struct
import threading

import pytest

from awr2944_driver.protocol import EthernetDecoder
from awr2944_driver.transports import TCPServer
from .helpers import FRAMES, ethernet_bytes


@pytest.mark.parametrize('chunk_size', [1, 5, 6, 37, 4096, 999999])
def test_sdk_ethernet_framing(chunk_size):
    # Encoded from deterministic synthetic detections; transport is emulated.
    raw = ethernet_bytes()
    decoder = EthernetDecoder()
    frames = []
    for offset in range(0, len(raw), chunk_size):
        frames.extend(decoder.feed(raw[offset:offset + chunk_size]))
    assert len(frames) == 80
    assert sum(len(f.points) for f in frames) == 2400
    assert not decoder.buffer
    for actual, expected in zip(frames, FRAMES):
        assert actual.metadata_source == 'host_sequence'
        assert actual.sdk_version == 'unknown'
        assert actual.temperature == {}
        for a, e in zip(actual.points, expected.points):
            assert (a.x, a.y, a.z, a.velocity) == (e.x, e.y, e.z, e.velocity)
            assert math.isnan(a.snr) and math.isnan(a.noise)


def test_empty_frame_and_invalid_headers():
    assert EthernetDecoder().feed(struct.pack('<IH', 0, 0))[0].points == ()
    for invalid in (struct.pack('<IH', 65537, 0), struct.pack('<IH', 4, 1),
                    struct.pack('<IH4f', 1, 0, math.nan, 0, 0, 0)):
        with pytest.raises(ValueError):
            EthernetDecoder().feed(invalid)


def test_real_tcp_fragmentation_and_disconnect():
    server = TCPServer('127.0.0.1', 0, '127.0.0.1')
    raw = ethernet_bytes(FRAMES[:3])
    def client():
        with socket.create_connection(server.address) as connection:
            for offset in range(0, len(raw), 13):
                connection.sendall(raw[offset:offset + 13])
    sender = threading.Thread(target=client)
    sender.start()
    try:
        assert server.accept(threading.Event(), 2)
        decoder, frames = EthernetDecoder(), []
        with pytest.raises(ConnectionError, match='closed'):
            while True:
                frames.extend(decoder.feed(server.read()))
        assert [len(f.points) for f in frames] == [len(f.points) for f in FRAMES[:3]]
    finally:
        sender.join(2)
        server.close()
