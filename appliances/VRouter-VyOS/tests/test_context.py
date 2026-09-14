from pathlib import Path

from one_vrouter.context import build_model, load_context, merge_vrouter_context


def test_context_file_and_prefix_detection(tmp_path: Path):
    context = tmp_path / "one_env"
    context.write_text("export ETH0_IP='10.2.3.4'\nETH0_MASK=255.255.0.0\n", encoding="utf-8")
    env = load_context(context)
    model = build_model(env)
    assert model.interfaces[0].addresses == ("10.2.3.4/16",)


def test_onegate_template_overlays_stale_local_values():
    local = {"ONEGATE_ENDPOINT": "http://onegate", "ONEAPP_VNF_ROUTER4_ENABLED": "NO"}
    document = {
        "VROUTER": {
            "ID": "42",
            "TEMPLATE": {
                "ONEAPP_VNF_ROUTER4_ENABLED": "YES",
                "NIC": {"NIC_ID": "0", "IP": "192.0.2.10", "NETWORK_ID": "7"},
            },
        }
    }
    result = merge_vrouter_context(local, document)
    assert result["ONEGATE_ENDPOINT"] == "http://onegate"
    assert result["VROUTER_ID"] == "42"
    assert result["ONEAPP_VNF_ROUTER4_ENABLED"] == "YES"
    assert result["ETH0_IP"] == "192.0.2.10"


def test_interface_selection_supports_addresses_and_exclusions():
    model = build_model({"ETH0_IP": "192.0.2.10", "ETH1_IP": "10.0.0.1"})
    assert model.select_interfaces("192.0.2.10 !eth1", default_all=True) == ["eth0"]
