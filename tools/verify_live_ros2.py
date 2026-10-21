#!/usr/bin/env python3
"""Start a bounded live ROS session and record received PointCloud2 evidence."""
import argparse
import csv
from datetime import datetime
import json
import math
from pathlib import Path
import struct
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from diagnostic_msgs.msg import DiagnosticArray
from sensor_msgs.msg import PointCloud2
from std_msgs.msg import String
from std_srvs.srv import Trigger


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--transport', choices=('uart', 'ethernet'), default='uart',
                        help='Require this live transport in frame metadata')
    parser.add_argument('--timeout', type=float, default=75)
    parser.add_argument('--stop-after', type=float, default=0,
                        help='Request stop this many seconds after the first cloud; zero waits for the node timer')
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    rclpy.init()
    node = Node('radar_live_verifier')
    clouds, info, diagnostics = [], [], []
    point_file = (output / 'points.csv').open('w', newline='')
    meta_file = (output / 'frames.jsonl').open('w')
    writer = csv.writer(point_file)
    writer.writerow(['cloud_index', 'host_stamp_ns', 'x', 'y', 'z', 'velocity',
                     'snr', 'noise', 'intensity', 'range'])
    started = datetime.now().astimezone().isoformat()
    errors = []

    def on_cloud(message):
        if message.point_step != 32 or message.row_step != 32 * message.width or message.is_bigendian:
            errors.append('Unexpected PointCloud2 layout')
            return
        stamp = message.header.stamp.sec * 1000000000 + message.header.stamp.nanosec
        points = list(struct.iter_unpack('<8f', bytes(message.data)))
        if len(points) != message.width or not all(math.isfinite(v) for p in points for v in p[:4]):
            errors.append('Invalid Cartesian payload')
        clouds.append({'received_monotonic': time.monotonic(), 'stamp_ns': stamp,
                       'points': message.width, 'frame_id': message.header.frame_id})
        writer.writerows((len(clouds), stamp, *point) for point in points)

    def on_info(message):
        item = json.loads(message.data)
        info.append(item)
        meta_file.write(json.dumps(item) + '\n')

    def on_diagnostics(message):
        for status in message.status:
            if status.name == '/radar/awr2944':
                values = {v.key: v.value for v in status.values}
                values['message'] = status.message
                diagnostics.append(values)
                (output / 'status.json').write_text(json.dumps(values, indent=2))

    node.create_subscription(PointCloud2, '/radar/points', on_cloud, qos_profile_sensor_data)
    node.create_subscription(String, '/radar/frame_info', on_info, qos_profile_sensor_data)
    node.create_subscription(DiagnosticArray, '/radar/diagnostics', on_diagnostics, 10)
    start_client = node.create_client(Trigger, '/radar/start')
    stop_client = node.create_client(Trigger, '/radar/stop')
    begin = time.monotonic()
    last_log = begin
    start_accepted = False
    try:
        if not start_client.wait_for_service(timeout_sec=5):
            raise RuntimeError('Start service unavailable')
        # Let DDS discover the subscribers before enabling the radar.
        while time.monotonic() - begin < 1.0:
            rclpy.spin_once(node, timeout_sec=0.1)
        discovery_deadline = time.monotonic() + 5
        while node.count_publishers('/radar/points') != 1 and time.monotonic() < discovery_deadline:
            rclpy.spin_once(node, timeout_sec=0.1)
        if node.count_publishers('/radar/points') != 1:
            raise RuntimeError('Expected exactly one /radar/points publisher; stop duplicate drivers first')
        future = start_client.call_async(Trigger.Request())
        rclpy.spin_until_future_complete(node, future, timeout_sec=5)
        if not future.done() or not future.result().success:
            raise RuntimeError('Start request failed')
        start_accepted = True
        # Ignore diagnostics from a previous failed session received before the
        # start acknowledgement. The node publishes its current state each second.
        diagnostics.clear()
        print(future.result().message, flush=True)
        deadline = time.monotonic() + args.timeout
        stop_requested = False
        while time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.1)
            if (args.stop_after and clouds and not stop_requested and
                    time.monotonic() - clouds[0]['received_monotonic'] >= args.stop_after):
                stop_client.call_async(Trigger.Request())
                stop_requested = True
            status = diagnostics[-1] if diagnostics else {}
            if status.get('state') == 'error':
                errors.append(status.get('detail', 'Driver error'))
                break
            if status.get('state') == 'stopped' and clouds:
                break
            if time.monotonic() - last_log >= 5:
                print(json.dumps({'state': status.get('state'), 'clouds': len(clouds),
                                  'points': sum(c['points'] for c in clouds),
                                  'temperature_c': status.get('temperature_c'),
                                  'invalid_packets': status.get('invalid_packets')}), flush=True)
                last_log = time.monotonic()
        else:
            errors.append('Verification deadline exceeded')
    except Exception as exc:
        errors.append(str(exc))
    finally:
        state = diagnostics[-1].get('state') if diagnostics else None
        if start_accepted and state not in ('stopped', 'error') and stop_client.wait_for_service(timeout_sec=2):
            future = stop_client.call_async(Trigger.Request())
            rclpy.spin_until_future_complete(node, future, timeout_sec=3)
            deadline = time.monotonic() + 7
            while time.monotonic() < deadline:
                rclpy.spin_once(node, timeout_sec=0.1)
                if diagnostics and diagnostics[-1].get('state') in ('stopped', 'error'):
                    break
        point_file.close()
        meta_file.close()
        rate = ((len(clouds) - 1) / (clouds[-1]['received_monotonic'] - clouds[0]['received_monotonic'])
                if len(clouds) > 1 else 0)
        temperatures = [max(f['temperature']['raw_values_c']) for f in info
                        if f.get('temperature', {}).get('valid') and f['temperature'].get('raw_values_c')]
        expected_metadata = 'sensor' if args.transport == 'uart' else 'host_sequence'
        if not info:
            errors.append('No frame metadata received to verify the live source')
        if any(f.get('transport') != args.transport or f.get('metadata_source') != expected_metadata
               for f in info):
            errors.append(f'Received data from a source other than live {args.transport}')
        sensor_frames = [f['frame_number'] for f in info if f.get('metadata_source') == 'sensor']
        host_frames = [f['frame_number'] for f in info if f.get('metadata_source') == 'host_sequence']
        report = {'started_at': started, 'finished_at': datetime.now().astimezone().isoformat(),
                  'source': 'live_usb_ros2' if args.transport == 'uart' else 'live_ethernet_ros2',
                  'transport': args.transport, 'clouds_received': len(clouds),
                  'metadata_received': len(info), 'points_received': sum(c['points'] for c in clouds),
                  'measured_rate_hz': rate,
                  'points_per_cloud_min': min((c['points'] for c in clouds), default=0),
                  'points_per_cloud_max': max((c['points'] for c in clouds), default=0),
                  'first_sensor_frame': sensor_frames[0] if sensor_frames else None,
                  'last_sensor_frame': sensor_frames[-1] if sensor_frames else None,
                  'first_host_sequence': host_frames[0] if host_frames else None,
                  'last_host_sequence': host_frames[-1] if host_frames else None,
                  'sensor_frame_gaps_observable': args.transport == 'uart',
                  'reported_temperature_min_c': min(temperatures, default=None),
                  'reported_temperature_max_c': max(temperatures, default=None),
                  'final_diagnostics': diagnostics[-1] if diagnostics else {}, 'errors': errors}
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(report, indent=2), flush=True)
        node.destroy_node()
        rclpy.shutdown()
    return 0 if clouds and not errors else 1


if __name__ == '__main__':
    raise SystemExit(main())
