from pathlib import Path

from one_vrouter.reconciler import Reconciler, save_snapshot


def test_no_onegate_ignores_persisted_snapshot(tmp_path: Path, capsys):
    context = tmp_path / "one_env"
    context.write_text("ETH0_IP=10.0.0.1/24\nONEAPP_VNF_SDNAT4_ENABLED=YES\nONEAPP_VNF_SDNAT4_INTERFACES=eth0\n")
    snapshot = {
        "vrouter": {"VROUTER": {"ID": "42", "TEMPLATE": {}}},
        "vnets": [
            {"VNET": {"ID": "10", "AR_POOL": {"AR": {"LEASES": {"LEASE": {"VM": "9", "IP": "10.0.0.9"}}}}}},
            {"VNET": {"ID": "20", "AR_POOL": {"AR": {"LEASES": {"LEASE": {"VM": "9", "IP": "198.51.100.9", "EXTERNAL": "YES", "PARENT_NETWORK_ID": "10"}}}}}},
        ],
        "vms": [],
    }
    snapshot_file = tmp_path / "onegate.json"
    save_snapshot(snapshot_file, snapshot)
    controller = Reconciler(
        context_file=context,
        state_file=tmp_path / "state.json",
        snapshot_file=snapshot_file,
        dry_run=True,
        use_onegate=False,
    )
    assert controller.reconcile_once()
    assert "198.51.100.9" not in capsys.readouterr().out
