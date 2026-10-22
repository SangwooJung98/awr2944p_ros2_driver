#!/usr/bin/env python3
"""Check installed resources and ROS replay without a radar or graphical display."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time

from ament_index_python.packages import get_package_prefix, get_package_share_directory
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import PointCloud2
from std_msgs.msg import String


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ros-domain-id', type=int, default=174,
                        help='Unused ROS domain for this check (default: 174)')
    args = parser.parse_args()
    os.environ['ROS_DOMAIN_ID'] = str(args.ros_domain_id)
    os.environ['ROS_LOCALHOST_ONLY'] = '1'
    share = Path(get_package_share_directory('awr2944_driver'))
    resources = ['package.xml', 'LICENSE', 'rviz/radar.rviz',
                 'config/ethernet_4_7_2.cfg', 'config/usb_4_6_2.cfg',
                 'data/synthetic_uart.bin', 'data/synthetic_points.csv',
                 'launch/ethernet.launch.py', 'launch/usb.launch.py',
                 'launch/replay.launch.py']
    for resource in resources:
        if not (share / resource).is_file():
            raise RuntimeError(f'Missing installed resource: {share / resource}')
    for package, executable in [('rviz2', 'rviz2'), ('tf2_ros', 'static_transform_publisher')]:
        path = Path(get_package_prefix(package)) / 'lib' / package / executable
        if not path.is_file():
            raise RuntimeError(f'Missing executable: {path}')
    for launch in ('usb', 'ethernet', 'replay'):
        subprocess.run(['ros2', 'launch', 'awr2944_driver',
                        f'{launch}.launch.py', '--show-args'],
                       check=True, stdout=subprocess.PIPE, text=True, timeout=15)

    rclpy.init()
    observer = Node('radar_installation_check')
    received, metadata = [], []
    observer.create_subscription(PointCloud2, '/radar/points',
                                 lambda msg: received.append((time.monotonic(), msg)),
                                 qos_profile_sensor_data)
    observer.create_subscription(String, '/radar/frame_info',
                                 lambda msg: metadata.append(json.loads(msg.data)),
                                 qos_profile_sensor_data)
    process = None
    report = None

    def spin_until(predicate, timeout=15):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError('Replay launch exited before the check completed')
            if predicate():
                return
            rclpy.spin_once(observer, timeout_sec=0.05)
        raise RuntimeError('Timed out waiting for replay discovery or points')

    try:
        with tempfile.TemporaryFile(mode='w+') as log:
            try:
                process = subprocess.Popen([
                    'ros2', 'launch', 'awr2944_driver', 'replay.launch.py',
                    'rviz:=false', 'replay_loop:=true',
                ], stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                spin_until(lambda: len(received) >= 20 and len(metadata) >= 20)
                if (observer.count_publishers('/radar/points') != 1 or
                        any(item.get('transport') != 'replay' for item in metadata)):
                    raise RuntimeError('Another driver is using this ROS domain; choose an unused domain')
                expected_fields = ['x', 'y', 'z', 'velocity', 'snr', 'noise', 'intensity', 'range']
                for _, cloud in received:
                    if (cloud.width != 30 or cloud.point_step != 32 or
                            len(cloud.data) != 30 * 32 or cloud.header.frame_id != 'radar_link' or
                            [field.name for field in cloud.fields] != expected_fields):
                        raise RuntimeError('Unexpected synthetic PointCloud2 layout')
                report = {'result': 'PASS', 'package_share': str(share),
                          'resources': len(resources), 'launch_files': 3,
                          'clouds': len(received), 'points': sum(msg.width for _, msg in received),
                          'rate_hz': round((len(received) - 1) /
                                           (received[-1][0] - received[0][0]), 2)}
            finally:
                if process and process.poll() is None:
                    process.send_signal(signal.SIGINT)
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait(timeout=5)
                if not report or (process and process.returncode != 0):
                    log.seek(0)
                    print(log.read())
            if process.returncode != 0:
                raise RuntimeError(f'Replay did not shut down cleanly: {process.returncode}')
    finally:
        observer.destroy_node()
        rclpy.shutdown()
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
