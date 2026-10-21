import struct

from awr2944_driver.messages import FIELDS, make_cloud
from awr2944_driver.protocol import Frame, Point


def test_ros_axes_fields_and_stamp():
    frame = Frame(0x04060201, 0x2944, 1, 0, 0,
                  (Point(2., 3., 4., -.5, 18., 12.),), 0, {}, {})
    cloud = make_cloud(frame, 'radar_link', 12_345_678_901)
    assert [field.name for field in cloud.fields] == list(FIELDS)
    assert cloud.point_step == cloud.row_step == 32
    assert cloud.width == cloud.height == 1
    assert not cloud.is_bigendian
    assert cloud.is_dense
    x, y, z, velocity, snr, noise, intensity, distance = struct.unpack('<8f', bytes(cloud.data))
    assert (x, y, z) == (3., -2., 4.)
    assert (velocity, snr, noise, intensity) == (-.5, 18., 12., 18.)
    assert abs(distance - 29**.5) < 1e-6
    assert cloud.header.frame_id == 'radar_link'
    assert cloud.header.stamp.sec == 12
    assert cloud.header.stamp.nanosec == 345678901
    raw = make_cloud(frame, 'radar_ti', 0, 'ti')
    assert struct.unpack_from('<3f', bytes(raw.data)) == (2., 3., 4.)


def test_empty_cloud_and_missing_side_info():
    frame = Frame(0, 0, 0, 0, 0, (), 40, {}, {})
    cloud = make_cloud(frame, 'radar_link', 0)
    assert cloud.width == cloud.row_step == len(cloud.data) == 0
    frame = Frame(0, 0, 0, 0, 0, (Point(1., 2., 3., 0.),), 0, {}, {})
    assert not make_cloud(frame, 'radar_link', 0).is_dense
