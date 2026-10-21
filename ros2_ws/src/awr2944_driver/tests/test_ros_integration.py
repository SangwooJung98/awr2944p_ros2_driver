"""Real DDS serialization, services, and all three input paths; no radar hardware."""
import json
import math
import os
import pty
import socket
import struct
import threading
import time

import pytest
import rclpy
from rclpy.context import Context
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import PointCloud2
from std_msgs.msg import String
from std_srvs.srv import Trigger

from awr2944_driver.node import RadarNode
from .helpers import FakeCLI, FRAMES, PACKAGE, RAW, ethernet_bytes


@pytest.mark.parametrize('mode', ['replay', 'uart', 'ethernet'])
def test_real_ros_points_and_services(mode):
    context = Context()
    rclpy.init(context=context)
    executor = SingleThreadedExecutor(context=context)
    observer = Node('radar_test_observer', context=context)
    finished = threading.Event()
    senders, fds, sender_errors = [], [], []
    emulator, driver = None, None
    params = {'transport': mode, 'auto_start': False,
              'config_file': str(PACKAGE / 'config/usb_4_6_2.cfg'),
              'max_run_seconds': 0.0, 'data_timeout': 5.0}

    def send_frames(writer, ethernet=False):
        try:
            offset = 0
            for frame in FRAMES:
                if finished.is_set():
                    return
                raw = ethernet_bytes([frame]) if ethernet else RAW[offset:offset + frame.packet_bytes]
                offset += frame.packet_bytes
                # Intentionally split the count/magic header across writes.
                writer(raw[:3])
                writer(raw[3:])
                time.sleep(0.025)
        except Exception as exc:
            if not finished.is_set():
                sender_errors.append(exc)

    def start_uart(command):
        if command == 'sensorStart':
            thread = threading.Thread(target=send_frames, args=(lambda b: os.write(fds[0], b),), daemon=True)
            senders.append(thread)
            thread.start()

    if mode == 'replay':
        params.update(replay_file=str(PACKAGE / 'data/synthetic_uart.bin'), replay_rate_hz=40.0)
    elif mode == 'uart':
        fds.extend(pty.openpty())
        emulator = FakeCLI(callback=start_uart)
        params.update(cli_port=emulator.path, data_port=os.ttyname(fds[1]))
    else:
        with socket.socket() as reserve:
            reserve.bind(('127.0.0.1', 0))
            port = reserve.getsockname()[1]
        params.update(configure_sensor=False, host_ip='127.0.0.1', radar_ip='127.0.0.1', tcp_port=port)

    received, infos = [], []
    try:
        driver = RadarNode(namespace='radar', context=context,
                           parameter_overrides=[Parameter(k, value=v) for k, v in params.items()])
        observer.create_subscription(PointCloud2, '/radar/points', received.append, qos_profile_sensor_data)
        observer.create_subscription(String, '/radar/frame_info', lambda m: infos.append(json.loads(m.data)),
                                     qos_profile_sensor_data)
        executor.add_node(driver)
        executor.add_node(observer)

        def spin_until(predicate, timeout=8):
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline and not predicate():
                executor.spin_once(timeout_sec=0.02)
            assert predicate(), driver.session.snapshot()

        spin_until(lambda: driver.cloud_publisher.get_subscription_count() == 1 and
                   driver.info_publisher.get_subscription_count() == 1)
        assert driver.session.snapshot()['state'] == 'idle'
        assert driver.session.thread is None  # Default never touches hardware.
        start = observer.create_client(Trigger, '/radar/start')
        stop = observer.create_client(Trigger, '/radar/stop')
        assert start.wait_for_service(timeout_sec=3)
        future = start.call_async(Trigger.Request())
        spin_until(future.done)
        assert future.result().success
        if mode == 'ethernet':
            spin_until(lambda: driver.session.snapshot()['state'] == 'connecting')
            def tcp_sender():
                try:
                    with socket.create_connection(('127.0.0.1', port)) as connection:
                        send_frames(connection.sendall, ethernet=True)
                        finished.wait(8)
                except Exception as exc:
                    if not finished.is_set():
                        sender_errors.append(exc)
            thread = threading.Thread(target=tcp_sender, daemon=True)
            senders.append(thread)
            thread.start()
        spin_until(lambda: len(received) == 80 and len(infos) == 80)
        assert sum(cloud.width for cloud in received) == 2400
        assert driver.queue_drops == 0
        for cloud, expected in zip(received, FRAMES):
            assert cloud.header.frame_id == 'radar_link'
            assert cloud.header.stamp.sec > 0
            assert cloud.width == len(expected.points)
            assert cloud.point_step == 32 and cloud.row_step == 32 * cloud.width
            for actual, point in zip(struct.iter_unpack('<8f', bytes(cloud.data)), expected.points):
                assert actual[:4] == (point.y, -point.x, point.z, point.velocity)
                assert actual[7] == pytest.approx(math.sqrt(point.x**2 + point.y**2 + point.z**2))
                if mode == 'ethernet':
                    assert all(math.isnan(value) for value in actual[4:7])
                else:
                    assert actual[4:7] == pytest.approx((point.snr, point.noise, point.snr))
        assert all(info['time_source'] == 'host_receive' for info in infos)
        if mode == 'ethernet':
            assert all(info['metadata_source'] == 'host_sequence' for info in infos)
            assert all(info['cpu_cycles'] is None for info in infos)
        future = stop.call_async(Trigger.Request())
        spin_until(future.done)
        assert future.result().success
        spin_until(lambda: not driver.session.thread.is_alive())
        if mode == 'uart':
            assert driver.session.snapshot()['stop_confirmed']
            assert 'sensorStop' in emulator.commands
            assert emulator.commands[-1] == 'queryDemoStatus'
            assert emulator.state == 3
        assert not sender_errors
    finally:
        if driver:
            driver.destroy_node()
        finished.set()
        for thread in senders:
            thread.join(2)
        if emulator:
            emulator.close()
        for fd in fds:
            os.close(fd)
        observer.destroy_node()
        executor.shutdown()
        rclpy.shutdown(context=context)
