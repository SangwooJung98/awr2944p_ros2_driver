"""ROS messages and the explicit TI-to-REP-103 coordinate conversion."""
from array import array
import math
import struct

from builtin_interfaces.msg import Time
from sensor_msgs.msg import PointCloud2, PointField
from std_msgs.msg import Header

FIELDS = ('x', 'y', 'z', 'velocity', 'snr', 'noise', 'intensity', 'range')


def stamp_from_ns(stamp_ns):
    sec, nanosec = divmod(int(stamp_ns), 1_000_000_000)
    return Time(sec=sec, nanosec=nanosec)


def make_cloud(frame, frame_id, stamp_ns, coordinates='ros'):
    if coordinates not in ('ros', 'ti'):
        raise ValueError('coordinates must be ros or ti')
    data = bytearray(len(frame.points) * 32)
    dense = True
    for index, point in enumerate(frame.points):
        # TI: x right, y forward, z up. ROS: x forward, y left, z up.
        x, y, z = (point.y, -point.x, point.z) if coordinates == 'ros' else (point.x, point.y, point.z)
        distance = math.sqrt(x*x + y*y + z*z)
        values = (x, y, z, point.velocity, point.snr, point.noise, point.snr, distance)
        dense = dense and all(math.isfinite(value) for value in values)
        struct.pack_into('<8f', data, index * 32, *values)
    return PointCloud2(
        header=Header(stamp=stamp_from_ns(stamp_ns), frame_id=frame_id),
        height=1, width=len(frame.points),
        fields=[PointField(name=name, offset=i*4, datatype=PointField.FLOAT32, count=1)
                for i, name in enumerate(FIELDS)],
        is_bigendian=False, point_step=32, row_step=len(data),
        data=array('B', data), is_dense=dense)
