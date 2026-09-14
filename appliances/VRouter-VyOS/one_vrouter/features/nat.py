"""Static NAT4 and OneGate-driven symmetric dynamic NAT."""

from __future__ import annotations

import ipaddress
import re
from typing import Any, Iterable, Mapping

from ..model import DesiredConfig, VRouterModel, truthy


SOURCE_BASE = 9000
DESTINATION_BASE = 10000
SDNAT_SOURCE_BASE = 20000
SDNAT_DESTINATION_BASE = 30000


def _valid_port(value: str | None) -> bool:
    return bool(value and value.isdigit() and 0 < int(value) <= 65535)


def _valid_ipv4(value: str | None) -> bool:
    try:
        return value is not None and isinstance(ipaddress.ip_address(value), ipaddress.IPv4Address)
    except ValueError:
        return False


def _port_forwards(model: VRouterModel) -> dict[int, tuple[str | None, str, str, str | None, str]]:
    result: dict[int, tuple[str | None, str, str, str | None, str]] = {}
    for name, raw in model.env.items():
        match = re.fullmatch(r"ONEAPP_VNF_NAT4_PORT_FWD(\d+)", name)
        if not match or not raw.strip():
            continue
        parts = [item.strip() for item in raw.split(":")]
        if not 2 <= len(parts) <= 4:
            continue
        first = model.interpolate(parts[0]) or ""
        if _valid_ipv4(first):
            old_address, old_port = first, parts[1] if len(parts) > 1 else None
            new_address = model.interpolate(parts[2]) if len(parts) > 2 else None
            new_port = parts[3] if len(parts) > 3 else None
        else:
            old_address, old_port = None, first
            new_address = model.interpolate(parts[1]) if len(parts) > 1 else None
            new_port = parts[2] if len(parts) > 2 else None
        if not _valid_port(old_port) or not _valid_ipv4(new_address) or (new_port and not _valid_port(new_port)):
            continue
        protocol = model.value(f"ONEAPP_VNF_NAT4_PORT_FWD{match.group(1)}_PROTOCOL", "tcp_udp") or "tcp_udp"
        result[int(match.group(1))] = (old_address, old_port or "", new_address or "", new_port, protocol.lower())
    return result


def _vnet_body(document: Mapping[str, Any]) -> Mapping[str, Any]:
    value = document.get("VNET", document)
    return value if isinstance(value, dict) else {}


def _items(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _leases(vnets: Iterable[Mapping[str, Any]]) -> tuple[dict[tuple[str, str], Mapping[str, Any]], list[Mapping[str, Any]]]:
    by_vm_network: dict[tuple[str, str], Mapping[str, Any]] = {}
    external: list[Mapping[str, Any]] = []
    for document in vnets:
        vnet = _vnet_body(document)
        vnet_id = vnet.get("ID")
        ar_pool = vnet.get("AR_POOL", {})
        for ar in _items(ar_pool.get("AR") if isinstance(ar_pool, dict) else None):
            lease_pool = ar.get("LEASES", {}) if isinstance(ar, dict) else {}
            for lease in _items(lease_pool.get("LEASE") if isinstance(lease_pool, dict) else None):
                if not isinstance(lease, dict):
                    continue
                vm_id = lease.get("VM")
                if vm_id is not None and vnet_id is not None:
                    by_vm_network[(str(vm_id), str(vnet_id))] = lease
                if truthy(str(lease.get("EXTERNAL", "NO"))):
                    external.append(lease)
    return by_vm_network, external


def _sdnat_map(model: VRouterModel) -> dict[str, str]:
    vnets = model.onegate.get("vnets", [])
    if not isinstance(vnets, list):
        return {}
    selected = set(model.select_interfaces(model.env.get("ONEAPP_VNF_SDNAT4_INTERFACES"), default_all=False))
    selected -= model.management_names
    if not selected:
        return {}
    networks = [network for interface in model.interfaces if interface.name in selected for network in interface.networks]
    by_vm_network, external = _leases(vnets)
    result: dict[str, str] = {}
    for lease in external:
        vm_id, parent, external_ip = lease.get("VM"), lease.get("PARENT_NETWORK_ID"), lease.get("IP")
        if vm_id is None or parent is None or external_ip is None:
            continue
        internal = by_vm_network.get((str(vm_id), str(parent)), {}).get("IP")
        if internal is None:
            continue
        try:
            if networks and not any(ipaddress.ip_address(str(internal)) in ipaddress.ip_network(network) for network in networks):
                continue
        except ValueError:
            continue
        result[str(external_ip)] = str(internal)
    return result


def render(model: VRouterModel) -> DesiredConfig:
    config = DesiredConfig()
    if model.enabled("ONEAPP_VNF_NAT4_ENABLED"):
        outbound = model.select_interfaces(model.env.get("ONEAPP_VNF_NAT4_INTERFACES_OUT"), default_all=False)
        outbound = [name for name in outbound if name not in model.management_names]
        for offset, interface in enumerate(outbound):
            rule = SOURCE_BASE + offset
            config.set("nat", "source", "rule", rule, "outbound-interface", "name", interface)
            config.set("nat", "source", "rule", rule, "translation", "address", "masquerade")
        for index, (old_address, old_port, new_address, new_port, protocol) in _port_forwards(model).items():
            for offset, interface in enumerate(outbound):
                rule = DESTINATION_BASE + index * 10 + offset
                config.set("nat", "destination", "rule", rule, "inbound-interface", "name", interface)
                config.set("nat", "destination", "rule", rule, "protocol", protocol)
                config.set("nat", "destination", "rule", rule, "destination", "port", old_port)
                if old_address:
                    config.set("nat", "destination", "rule", rule, "destination", "address", old_address)
                config.set("nat", "destination", "rule", rule, "translation", "address", new_address)
                if new_port:
                    config.set("nat", "destination", "rule", rule, "translation", "port", new_port)

    if model.enabled("ONEAPP_VNF_SDNAT4_ENABLED"):
        for offset, (external, internal) in enumerate(sorted(_sdnat_map(model).items())):
            config.set("interfaces", "loopback", "lo", "address", f"{external}/32")
            config.set("nat", "source", "rule", SDNAT_SOURCE_BASE + offset, "source", "address", f"{internal}/32")
            config.set("nat", "source", "rule", SDNAT_SOURCE_BASE + offset, "translation", "address", external)
            config.set("nat", "destination", "rule", SDNAT_DESTINATION_BASE + offset, "destination", "address", f"{external}/32")
            config.set("nat", "destination", "rule", SDNAT_DESTINATION_BASE + offset, "translation", "address", internal)
    return config
