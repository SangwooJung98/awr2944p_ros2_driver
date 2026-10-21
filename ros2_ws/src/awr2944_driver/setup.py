from glob import glob
from setuptools import find_packages, setup

name = 'awr2944_driver'
setup(
    name=name, version='0.1.0', packages=find_packages(exclude=['tests']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + name]),
        ('share/' + name, ['package.xml', 'README.md', 'LICENSE']),
        ('share/' + name + '/launch', glob('launch/*.launch.py')),
        ('share/' + name + '/config', glob('config/*')),
        ('share/' + name + '/rviz', glob('rviz/*')),
        ('share/' + name + '/data', glob('data/*')),
    ],
    install_requires=['setuptools', 'pyserial'], zip_safe=True,
    tests_require=['pytest'],
    maintainer='SangwooJung98', maintainer_email='SangwooJung98@users.noreply.github.com',
    description='USB UART, Ethernet TCP, and recorded-data AWR2944P ROS2 driver',
    license='Apache-2.0',
    entry_points={'console_scripts': ['radar_node = awr2944_driver.node:main']},
)
