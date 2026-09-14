"""Static and OneGate-discovered IPVS and HAProxy backends."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from ..model import DesiredConfig, VRouterModel, truthy


@dataclass
class Backend:
    host: str
    port: str | None = None
    weight: str | None = None


@dataclass
class LoadBalancer:
    index: int
    ip: str
    port: str | None
    protocol: str = "tcp"
    method: str = "nat"
    scheduler: str = "round-robin"
    timeout: str | None = None
    backends: list[Backend] = field(default_factory=list)


SCHEDULERS = {
    "rr": "round-robin",
    "wrr": "weighted-round-robin",
    "lc": "least-connection",
    "wlc": "weighted-least-connection",
    "sh": "source-hashing",
    "dh": "destination-hashing",
    "lblc": "locality-based-least-connection",
}
METHODS = {"nat": "nat", "dr": "direct", "tun": "tunnel", "tunnel": "tunnel", "direct": "direct"}


def _static(model: VRouterModel, prefix: str, allow_portless: bool) -> dict[int, LoadBalancer]:
    options: dict[int, dict[str, str]] = {}
    servers: dict[int, dict[int, dict[str, str]]] = {}
    for name, value in model.env.items():
        option = re.fullmatch(rf"{prefix}(\d+)_(IP|PORT|PROTOCOL|METHOD|SCHEDULER|TIMEOUT)", name)
        server = re.fullmatch(rf"{prefix}(\d+)_SERVER(\d+)_(HOST|PORT|WEIGHT)", name)
        if option:
            options.setdefault(int(option.group(1)), {})[option.group(2).lower()] = value
        elif server:
            servers.setdefault(int(server.group(1)), {}).setdefault(int(server.group(2)), {})[server.group(3).lower()] = value
    result: dict[int, LoadBalancer] = {}
    for index, values in options.items():
        ip = model.interpolate(values.get("ip"))
        port = values.get("port") or None
        if not ip or (not port and not allow_portless):
            continue
        scheduler = SCHEDULERS.get(values.get("scheduler", "rr").lower(), values.get("scheduler", "round-robin").lower())
        lb = LoadBalancer(
            index=index,
            ip=ip,
            port=port,
            protocol=values.get("protocol", "tcp").lower(),
            method=METHODS.get(values.get("method", "nat").lower(), "nat"),
            scheduler=scheduler,
            timeout=values.get("timeout") or None,
        )
        for _, backend in sorted(servers.get(index, {}).items()):
            host = model.interpolate(backend.get("host"))
            backend_port = backend.get("port") or port
            if host and (backend_port or allow_portless):
                lb.backends.append(Backend(host, backend_port, backend.get("weight") or None))
        result[index] = lb
    return result


def _dynamic_objects(model: VRouterModel) -> Iterable[Mapping[str, Any]]:
    for document in model.onegate.get("vms", []):
        if isinstance(document, dict):
            template = document.get("VM", {}).get("USER_TEMPLATE", {})
            if isinstance(template, dict):
                yield template
    for document in model.onegate.get("vnets", []):
        if not isinstance(document, dict):
            continue
        vnet = document.get("VNET", document)
        ar_pool = vnet.get("AR_POOL", {}) if isinstance(vnet, dict) else {}
        ars = ar_pool.get("AR", []) if isinstance(ar_pool, dict) else []
        for ar in ars if isinstance(ars, list) else [ars]:
            leases = ar.get("LEASES", {}).get("LEASE", []) if isinstance(ar, dict) else []
            for lease in leases if isinstance(leases, list) else [leases]:
                if isinstance(lease, dict) and truthy(str(lease.get("BACKEND", "NO"))):
                    yield lease


def _add_dynamic(model: VRouterModel, lbs: dict[int, LoadBalancer], prefix: str) -> None:
    target_id = model.value("SERVICE_ID") if (model.value("SERVICE_ID") and (model.value("ONEAPP_VNF_LB_ONEGATE_API", "auto") or "auto").lower() != "vrouter") else model.value("VROUTER_ID")
    for source in _dynamic_objects(model):
        for name, value in source.items():
            match = re.fullmatch(rf"{prefix}(\d+)_SERVER_(HOST|PORT|WEIGHT)", str(name))
            if not match:
                continue
            index = int(match.group(1))
            lb = lbs.get(index)
            if not lb:
                continue
            advertised_id = source.get(f"{prefix}{index}_ID")
            if advertised_id not in (None, "") and str(advertised_id) != str(target_id):
                continue
            host = model.interpolate(str(source.get(f"{prefix}{index}_SERVER_HOST", "")))
            port = str(source.get(f"{prefix}{index}_SERVER_PORT", "")) or lb.port
            weight = str(source.get(f"{prefix}{index}_SERVER_WEIGHT", "")) or None
            if host and not any(item.host == host and item.port == port for item in lb.backends):
                lb.backends.append(Backend(host, port, weight))
            break


def _render_ipvs(model: VRouterModel, config: DesiredConfig) -> None:
    if not model.enabled("ONEAPP_VNF_LB_ENABLED"):
        return
    lbs = _static(model, "ONEAPP_VNF_LB", allow_portless=True)
    if model.enabled("ONEAPP_VNF_LB_ONEGATE_ENABLED"):
        _add_dynamic(model, lbs, "ONEGATE_LB")
    selected = set(model.select_interfaces(model.env.get("ONEAPP_VNF_LB_INTERFACES", ""), default_all=True)) - model.management_names
    allowed = {address.split("/", 1)[0] for item in model.interfaces if item.name in selected for address in item.endpoint_addresses}
    for lb in lbs.values():
        if lb.ip not in allowed:
            continue
        root = ("high-availability", "virtual-server", lb.ip)
        config.set(*root, "algorithm", lb.scheduler)
        config.set(*root, "forward-method", lb.method)
        config.set(*root, "protocol", lb.protocol)
        if lb.port:
            config.set(*root, "port", lb.port)
        if lb.timeout:
            config.set(*root, "persistence-timeout", lb.timeout)
        for backend in lb.backends:
            config.set(*root, "real-server", backend.host, "port", backend.port or "0")
            if backend.weight:
                config.set(*root, "real-server", backend.host, "weight", backend.weight)


def _render_haproxy(model: VRouterModel, config: DesiredConfig) -> None:
    if not model.enabled("ONEAPP_VNF_HAPROXY_ENABLED"):
        return
    lbs = _static(model, "ONEAPP_VNF_HAPROXY_LB", allow_portless=False)
    if model.enabled("ONEAPP_VNF_HAPROXY_ONEGATE_ENABLED"):
        _add_dynamic(model, lbs, "ONEGATE_HAPROXY_LB")
    prefix = ("load-balancing", "haproxy")
    selected = set(model.select_interfaces(model.env.get("ONEAPP_VNF_HAPROXY_INTERFACES", ""), default_all=True)) - model.management_names
    allowed = {address.split("/", 1)[0] for item in model.interfaces if item.name in selected for address in item.endpoint_addresses}
    for lb in lbs.values():
        if lb.ip not in allowed:
            continue
        service, backend_name = f"one-lb-{lb.index}", f"one-backend-{lb.index}"
        config.set(*prefix, "service", service, "listen-address", lb.ip)
        config.set(*prefix, "service", service, "port", lb.port or "")
        config.set(*prefix, "service", service, "mode", "tcp")
        config.set(*prefix, "service", service, "backend", backend_name)
        config.set(*prefix, "backend", backend_name, "mode", "tcp")
        balance = lb.scheduler if lb.scheduler in {"round-robin", "least-connection", "source-address"} else "round-robin"
        config.set(*prefix, "backend", backend_name, "balance", balance)
        for offset, server in enumerate(lb.backends):
            name = f"server-{offset}"
            config.set(*prefix, "backend", backend_name, "server", name, "address", server.host)
            config.set(*prefix, "backend", backend_name, "server", name, "port", server.port or lb.port or "")
            config.set(*prefix, "backend", backend_name, "server", name, "check")


def render(model: VRouterModel) -> DesiredConfig:
    config = DesiredConfig()
    _render_ipvs(model, config)
    _render_haproxy(model, config)
    return config
