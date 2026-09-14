"""Small dependency-free client for the OpenNebula OneGate API."""

from __future__ import annotations

import json
import logging
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Mapping

from .model import truthy


LOG = logging.getLogger(__name__)


class OneGateError(RuntimeError):
    pass


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


@dataclass
class OneGateSnapshot:
    vrouter: dict[str, Any]
    vnets: list[dict[str, Any]] = field(default_factory=list)
    vms: list[dict[str, Any]] = field(default_factory=list)

    def as_mapping(self) -> dict[str, Any]:
        return {"vrouter": self.vrouter, "vnets": self.vnets, "vms": self.vms}


class OneGateClient:
    def __init__(self, env: Mapping[str, str], timeout: float = 15.0) -> None:
        self.env = dict(env)
        self.endpoint = env.get("ONEGATE_ENDPOINT", "").rstrip("/")
        self.vmid = env.get("VMID", "")
        self.token = env.get("TOKENTXT", "")
        self.timeout = timeout
        verify = truthy(env.get("ONEAPP_VNF_VYOS_ONEGATE_TLS_VERIFY"), default=False)
        self.ssl_context = ssl.create_default_context() if verify else ssl._create_unverified_context()

    @property
    def available(self) -> bool:
        return bool(self.endpoint and self.vmid and self.token)

    def request(
        self,
        method: str,
        path: str,
        query: Mapping[str, str] | None = None,
        form: Mapping[str, str] | None = None,
        expect_json: bool = True,
    ) -> Any:
        if not self.available:
            raise OneGateError("ONEGATE_ENDPOINT, VMID or TOKENTXT is missing")
        suffix = "?" + urllib.parse.urlencode(query) if query else ""
        body = urllib.parse.urlencode(form).encode("utf-8") if form else None
        request = urllib.request.Request(
            f"{self.endpoint}{path}{suffix}",
            data=body,
            method=method,
            headers={
                "X-ONEGATE-VMID": self.vmid,
                "X-ONEGATE-TOKEN": self.token,
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        try:
            with urllib.request.urlopen(request, context=self.ssl_context, timeout=self.timeout) as response:
                data = response.read().decode("utf-8")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise OneGateError(f"{method} {path} failed: {exc}") from exc
        if not expect_json:
            return data
        try:
            return json.loads(data)
        except ValueError as exc:
            raise OneGateError(f"{method} {path} returned invalid JSON") from exc

    def vrouter_show(self) -> dict[str, Any]:
        return self.request("GET", "/vrouter", {"extended": "true"})

    def vnet_show(self, network_id: str) -> dict[str, Any]:
        return self.request("GET", f"/vnet/{network_id}", {"extended": "true"})

    def vm_show(self, vm_id: str | None = None) -> dict[str, Any]:
        return self.request("GET", "/vm" if vm_id is None else f"/vms/{vm_id}")

    def service_show(self) -> dict[str, Any]:
        return self.request("GET", "/service")

    def vm_update(self, data: str, vm_id: str | None = None, erase: bool = False) -> str:
        path = "/vm" if vm_id is None else f"/vms/{vm_id}"
        return self.request(
            "PUT",
            path,
            form={"type": "2" if erase else "1", "data": data},
            expect_json=False,
        )

    def snapshot(self, include_dynamic: bool = True) -> OneGateSnapshot:
        vrouter = self.vrouter_show()
        if not include_dynamic:
            return OneGateSnapshot(vrouter)
        return OneGateSnapshot(
            vrouter=vrouter,
            vnets=self._vrouter_vnets(vrouter),
            vms=self._backend_vms(vrouter),
        )

    def _vrouter_vnets(self, document: Mapping[str, Any]) -> list[dict[str, Any]]:
        template = document.get("VROUTER", {}).get("TEMPLATE", {})
        nics = _as_list(template.get("NIC")) if isinstance(template, dict) else []
        pending = [str(nic["NETWORK_ID"]) for nic in nics if isinstance(nic, dict) and nic.get("NETWORK_ID") is not None]
        seen: set[str] = set()
        result: list[dict[str, Any]] = []
        while pending:
            network_id = pending.pop(0)
            if network_id in seen:
                continue
            seen.add(network_id)
            document = self.vnet_show(network_id)
            result.append(document)
            vnet = document.get("VNET", document)
            if not isinstance(vnet, dict):
                continue
            parent = vnet.get("PARENT_NETWORK_ID")
            if parent is not None:
                pending.append(str(parent))
            ar_pool = vnet.get("AR_POOL", {})
            for ar in _as_list(ar_pool.get("AR") if isinstance(ar_pool, dict) else None):
                leases = ar.get("LEASES", {}) if isinstance(ar, dict) else {}
                for lease in _as_list(leases.get("LEASE") if isinstance(leases, dict) else None):
                    if isinstance(lease, dict) and lease.get("VNET") is not None:
                        pending.append(str(lease["VNET"]))
        return result

    def _backend_vms(self, vrouter: Mapping[str, Any]) -> list[dict[str, Any]]:
        ids: list[str] = []
        if isinstance(vrouter.get("VROUTER"), dict):
            vm_pool = vrouter["VROUTER"].get("VMS", {})
            if isinstance(vm_pool, dict):
                ids.extend(str(value) for value in _as_list(vm_pool.get("ID")))
        service_id = self.env.get("SERVICE_ID")
        onegate_api = self.env.get("ONEAPP_VNF_LB_ONEGATE_API", "auto").lower()
        if service_id and onegate_api != "vrouter":
            service = self.service_show().get("SERVICE", {})
            for role in _as_list(service.get("roles") if isinstance(service, dict) else None):
                for node in _as_list(role.get("nodes") if isinstance(role, dict) else None):
                    vm = node.get("vm_info", {}).get("VM", {}) if isinstance(node, dict) else {}
                    if isinstance(vm, dict) and vm.get("ID") is not None:
                        ids.append(str(vm["ID"]))
        result: list[dict[str, Any]] = []
        for vm_id in dict.fromkeys(ids):
            result.append(self.vm_show(vm_id))
        return result
