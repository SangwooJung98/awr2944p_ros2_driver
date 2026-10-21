"""Prevent shipping another board's antenna layout as an AWR2944P default."""
from pathlib import Path

import pytest

from awr2944_driver.cli import profile_commands


@pytest.mark.parametrize('name', ['ethernet_4_7_2.cfg', 'usb_4_6_2.cfg'])
def test_profiles_match_awr2944p_antenna_layout(name):
    commands = profile_commands(Path(__file__).resolve().parents[1] / 'config' / name)
    by_name = {line.split()[0]: line for line in commands}
    assert by_name['ddmPhaseShiftAntOrder'] == 'ddmPhaseShiftAntOrder 0 2 3 1'
    assert by_name['antGeometryCfg'] == (
        'antGeometryCfg 1 0 1 1 1 2 1 3 0 2 0 3 0 4 0 5 '
        '1 4 1 5 1 6 1 7 1 8 1 9 1 10 1 11 0.5 0.8')
    assert by_name['antennaCalibParams'].split()[1:] == ['0', '1'] * 16
