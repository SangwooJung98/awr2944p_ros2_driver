"""Shared launch options with correctly typed ROS parameter substitutions."""
from pathlib import Path
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def description(transport):
    share = Path(get_package_share_directory('awr2944_driver'))
    args = {
        'config_file': (str(share / 'config' / ('ethernet_4_7_2.cfg' if transport == 'ethernet' else 'usb_4_6_2.cfg')), str),
        'cli_port': ('/dev/ttyACM0', str), 'data_port': ('/dev/ttyACM1', str),
        'data_baud': ('3125000', int), 'cli_baud': ('115200', int),
        'host_ip': ('192.168.1.10', str), 'radar_ip': ('192.168.1.200', str), 'tcp_port': ('7', int),
        'auto_start': ('true' if transport == 'replay' else 'false', bool),
        'configure_sensor': ('true', bool), 'resume_existing_config': ('false', bool),
        'max_run_seconds': ('60.0', float), 'max_temperature_c': ('0.0', float),
        'connect_timeout': ('15.0', float), 'data_timeout': ('3.0', float),
        'frame_id': ('radar_link', str), 'coordinates': ('ros', str),
        'replay_file': (str(share / 'data' / 'synthetic_uart.bin'), str),
        'replay_rate_hz': ('10.0', float), 'replay_loop': ('false', bool),
    }
    declarations = [DeclareLaunchArgument(name, default_value=value) for name, (value, _) in args.items()]
    declarations += [DeclareLaunchArgument('rviz', default_value='true'),
                     DeclareLaunchArgument('publish_tf', default_value='true',
                                           description='Publish identity radar_origin -> frame_id for standalone viewing'),
                     DeclareLaunchArgument('tf_parent', default_value='radar_origin')]
    params = {name: ParameterValue(LaunchConfiguration(name), value_type=kind)
              for name, (_, kind) in args.items()}
    params['transport'] = transport
    return LaunchDescription(declarations + [
        Node(package='awr2944_driver', executable='radar_node', name='awr2944',
             namespace='radar', output='screen', parameters=[params], sigterm_timeout='30'),
        Node(package='tf2_ros', executable='static_transform_publisher', name='radar_origin_tf',
             arguments=['--x', '0', '--y', '0', '--z', '0', '--roll', '0', '--pitch', '0', '--yaw', '0',
                        '--frame-id', LaunchConfiguration('tf_parent'),
                        '--child-frame-id', LaunchConfiguration('frame_id')],
             condition=IfCondition(LaunchConfiguration('publish_tf')), output='screen'),
        Node(package='rviz2', executable='rviz2', name='radar_rviz',
             arguments=['-d', str(share / 'rviz' / 'radar.rviz')],
             condition=IfCondition(LaunchConfiguration('rviz')), output='screen'),
    ])
