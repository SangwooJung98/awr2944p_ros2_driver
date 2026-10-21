#!/usr/bin/env python3
"""Generate deterministic synthetic UART frames and an independent CSV oracle."""
import argparse
import csv
import io
from pathlib import Path
import struct


def generate():
    stream = bytearray()
    text = io.StringIO(newline='')
    writer = csv.writer(text, lineterminator='\n')
    writer.writerow(['frame', 'x_m', 'y_m', 'z_m', 'doppler_m_s', 'snr_db', 'noise_db'])
    for frame in range(1, 81):
        points, side = bytearray(), bytearray()
        phase = (frame - 1) % 40
        shift = (phase if phase < 20 else 40 - phase) / 10.0 - 1.0
        for index in range(30):
            xyzv = ((index % 6 - 2.5) / 8.0 + shift,
                    3.0 + (index // 6) / 8.0, (index % 5 - 2) / 8.0,
                    0.5 if phase < 20 else -0.5)
            snr, noise = 180 + index, 70 + index % 3
            points.extend(struct.pack('<4f', *xyzv))
            side.extend(struct.pack('<2h', snr, noise))
            writer.writerow([frame, *xyzv, snr * 0.1, noise * 0.1])
        stats = struct.pack('<6I', 2000, 1000, 97000, 50, 20, 10)
        temperature = struct.pack('<iI10h', 0, frame * 100, *([35] * 10))
        payload = b''.join(struct.pack('<II', kind, len(body)) + body
                           for kind, body in [(1, points), (7, side), (6, stats), (9, temperature)])
        total = (40 + len(payload) + 31) // 32 * 32
        header = bytes.fromhex('0201040306050807') + struct.pack(
            '<8I', 0x04060201, total, 0x2944, frame, frame * 100000, 30, 4, 0)
        stream.extend(header + payload + bytes(total - 40 - len(payload)))
    return {'synthetic_uart.bin': bytes(stream), 'synthetic_points.csv': text.getvalue().encode()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Check committed fixtures without modifying them')
    args = parser.parse_args()
    output = Path(__file__).resolve().parents[1] / 'ros2_ws/src/awr2944_driver/data'
    output.mkdir(parents=True, exist_ok=True)
    for name, data in generate().items():
        path = output / name
        if args.check:
            if not path.is_file() or path.read_bytes() != data:
                raise SystemExit(f'Fixture differs: {path}')
        else:
            path.write_bytes(data)
    print('Synthetic fixtures: 80 frames, 2400 points; ' + ('verified' if args.check else 'generated'))


if __name__ == '__main__':
    main()
