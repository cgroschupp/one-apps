from pathlib import Path

from one_vrouter.model import VyOSCommand
from one_vrouter.reconciler import poll_interval
from one_vrouter.vyos.state import calculate_delta, read_state, write_state


def test_state_roundtrip_and_unchanged_delta(tmp_path: Path):
    path = tmp_path / "state.json"
    commands = [VyOSCommand("set", ("system", "host-name", "router"))]
    write_state(commands, path)
    assert read_state(path) == commands
    assert calculate_delta(commands, commands) == []
    assert oct(path.stat().st_mode & 0o777) == "0o600"


def test_delta_removes_stale_leaf_before_new_value():
    old = [VyOSCommand("set", ("interfaces", "ethernet", "eth0", "mtu", "1500"))]
    new = [VyOSCommand("set", ("interfaces", "ethernet", "eth0", "mtu", "1400"))]
    assert calculate_delta(old, new) == [old[0].delete(), new[0]]


def test_poll_interval_default_override_and_minimum():
    assert poll_interval({}) == 30
    assert poll_interval({"ONEAPP_VNF_VYOS_REFRESH_RATE": "45"}) == 45
    assert poll_interval({}, 0) == 1
