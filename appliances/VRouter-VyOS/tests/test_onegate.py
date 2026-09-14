import json
from pathlib import Path

from one_vrouter import reconciler as reconciler_module
from one_vrouter.onegate import OneGateClient, OneGateSnapshot
from one_vrouter.reconciler import Reconciler


def test_vrouter_request_contains_query_and_auth_headers(monkeypatch):
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self):
            return json.dumps({"VROUTER": {"ID": "42"}}).encode()

    def urlopen(request, **kwargs):
        captured["request"] = request
        captured["kwargs"] = kwargs
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    client = OneGateClient({"ONEGATE_ENDPOINT": "https://onegate:5030", "VMID": "7", "TOKENTXT": "token"})
    assert client.vrouter_show()["VROUTER"]["ID"] == "42"
    request = captured["request"]
    assert request.full_url == "https://onegate:5030/vrouter?extended=true"
    assert request.get_header("X-onegate-vmid") == "7"
    assert request.get_header("X-onegate-token") == "token"


def test_reconciler_polls_onegate_on_every_iteration(tmp_path: Path, monkeypatch):
    context = tmp_path / "one_env"
    context.write_text("ONEGATE_ENDPOINT=http://onegate\nVMID=7\nTOKENTXT=token\nETH0_IP=10.0.0.1/24\n")
    calls = []

    class Client:
        def __init__(self, env):
            self.endpoint = env["ONEGATE_ENDPOINT"]
            self.available = True

        def snapshot(self, include_dynamic=True):
            calls.append(include_dynamic)
            return OneGateSnapshot({"VROUTER": {"ID": "42", "TEMPLATE": {}}})

    monkeypatch.setattr(reconciler_module, "OneGateClient", Client)
    controller = Reconciler(
        context_file=context,
        state_file=tmp_path / "state.json",
        snapshot_file=tmp_path / "onegate.json",
        dry_run=True,
    )
    assert controller.reconcile_once()
    assert controller.reconcile_once()
    assert calls == [True, True]
