"""ROS2 PointCloud2 node for AWR2944P UART, TI Ethernet, and recorded UART data."""
from dataclasses import fields
import json
from pathlib import Path
import queue
import signal
import threading

from ament_index_python.packages import get_package_share_directory
from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus, KeyValue
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from rclpy.signals import SignalHandlerOptions
from rcl_interfaces.msg import ParameterDescriptor
from sensor_msgs.msg import PointCloud2, Temperature
from std_msgs.msg import String
from std_srvs.srv import Trigger

from .messages import make_cloud, stamp_from_ns
from .session import RadarSession, Settings


class RadarNode(Node):
    def __init__(self, **kwargs):
        super().__init__('awr2944', **kwargs)
        defaults = Settings()
        descriptor = ParameterDescriptor(read_only=True)
        values = {f.name: self.declare_parameter(f.name, getattr(defaults, f.name), descriptor).value
                  for f in fields(Settings)}
        auto_start = self.declare_parameter('auto_start', False, descriptor).value
        self.frame_id = self.declare_parameter('frame_id', 'radar_link', descriptor).value
        self.coordinates = self.declare_parameter('coordinates', 'ros', descriptor).value
        if self.coordinates not in ('ros', 'ti'):
            raise ValueError('coordinates must be ros or ti')
        if not values['config_file']:
            share = Path(get_package_share_directory('awr2944_driver'))
            name = 'ethernet_4_7_2.cfg' if values['transport'] == 'ethernet' else 'usb_4_6_2.cfg'
            values['config_file'] = str(share / 'config' / name)
        self.frames = queue.Queue(maxsize=8)
        self.queue_drops = 0
        self.cloud_publisher = self.create_publisher(PointCloud2, 'points', qos_profile_sensor_data)
        self.info_publisher = self.create_publisher(String, 'frame_info', qos_profile_sensor_data)
        self.temperature_publisher = self.create_publisher(Temperature, 'temperature', qos_profile_sensor_data)
        self.diagnostics_publisher = self.create_publisher(DiagnosticArray, 'diagnostics', 10)
        self.session = RadarSession(Settings(**values), self._receive_frame,
                                    lambda message: self.get_logger().info(message))
        self.create_service(Trigger, 'start', self._start)
        self.create_service(Trigger, 'stop', self._stop)
        self.create_timer(0.01, self._publish_frames)
        self.create_timer(1.0, self._publish_diagnostics)
        self.get_logger().info(f"{values['transport']} driver ready; auto_start={auto_start}. "
                               'Timestamps are host receive times; coordinates=' + self.coordinates)
        if auto_start:
            self.session.start()

    def _receive_frame(self, frame):
        item = (frame, self.get_clock().now().nanoseconds)
        try:
            self.frames.put_nowait(item)
        except queue.Full:
            try:
                self.frames.get_nowait()
            except queue.Empty:
                pass
            self.queue_drops += 1
            self.frames.put_nowait(item)

    def _start(self, request, response):
        response.success, response.message = self.session.start()
        return response

    def _stop(self, request, response):
        response.success, response.message = self.session.stop()
        return response

    def _publish_frames(self):
        for _ in range(8):
            try:
                frame, stamp = self.frames.get_nowait()
            except queue.Empty:
                break
            cloud = make_cloud(frame, self.frame_id, stamp, self.coordinates)
            self.cloud_publisher.publish(cloud)
            info = {
                'transport': self.session.settings.transport,
                'stamp_ns': stamp, 'time_source': 'host_receive',
                'frame_number': frame.number, 'metadata_source': frame.metadata_source,
                'subframe': frame.subframe if frame.metadata_source == 'sensor' else None,
                'sdk_version': frame.sdk_version,
                'cpu_cycles': frame.cpu_cycles if frame.metadata_source == 'sensor' else None,
                'points': len(frame.points), 'packet_bytes': frame.packet_bytes,
                'statistics': frame.stats, 'temperature': frame.temperature,
            }
            self.info_publisher.publish(String(data=json.dumps(info, allow_nan=False)))
            if frame.temperature.get('valid') and frame.temperature.get('raw_values_c'):
                self.temperature_publisher.publish(Temperature(
                    header=cloud.header, temperature=float(max(frame.temperature['raw_values_c'])),
                    variance=0.0))

    def _publish_diagnostics(self):
        status = self.session.snapshot()
        status.update(publish_queue_drops=self.queue_drops, transport=self.session.settings.transport,
                      time_source='host_receive',
                      sensor_sequence_available=self.session.settings.transport != 'ethernet')
        level = DiagnosticStatus.ERROR if status['state'] == 'error' else DiagnosticStatus.OK
        if status['invalid_packets'] or self.queue_drops:
            level = max(level, DiagnosticStatus.WARN)
        if not self.session.settings.configure_sensor and self.session.settings.transport != 'replay':
            status['rf_control'] = 'external: receiver cannot stop RF'
        diagnostic = DiagnosticStatus(
            level=level, name=self.get_fully_qualified_name(), hardware_id='TI AWR2944P',
            message=f"{status['state']}: {status['detail']}",
            values=[KeyValue(key=k, value=str(v)) for k, v in status.items()])
        message = DiagnosticArray(status=[diagnostic])
        message.header.stamp = stamp_from_ns(self.get_clock().now().nanoseconds)
        self.diagnostics_publisher.publish(message)

    def destroy_node(self):
        if not self.session.close():
            self.get_logger().error('Receiver did not stop in time; RF stop is not confirmed')
        return super().destroy_node()


def main(args=None):
    # ROS launch and the terminal can both deliver SIGINT. Keep the ROS context
    # alive until RF stop/serial cleanup completes, even on repeated signals.
    stopping = threading.Event()
    previous_handlers = {sig: signal.signal(sig, lambda *_: stopping.set())
                         for sig in (signal.SIGINT, signal.SIGTERM)}
    rclpy.init(args=args, signal_handler_options=SignalHandlerOptions.NO)
    node = None
    try:
        node = RadarNode(namespace='radar')
        while rclpy.ok() and not stopping.is_set():
            rclpy.spin_once(node, timeout_sec=0.1)
    except (KeyboardInterrupt, rclpy.executors.ExternalShutdownException):
        pass
    finally:
        if node:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)


if __name__ == '__main__':
    main()
