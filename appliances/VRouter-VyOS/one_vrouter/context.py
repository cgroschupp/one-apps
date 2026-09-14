"""Read OpenNebula context files and normalize network interfaces."""

from __future__ import annotations

import ipaddress
import logging
import os
import re
import shlex
from pathlib import Path
from typing import Any, Mapping

from .model import Interface, VRouterModel, truthy


LOG = logging.getLogger(__name__)
DEFAULT_CONTEXT_FILE = Path("/run/one-context/one_env")


def load_context(path: Path = DEFAULT_CONTEXT_FILE) -> dict[str, str]:
    env = dict(os.environ)
    if not path.exists():
        LOG.warning("context file %s does not exist; using process environment", path)
        return env

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            fields = shlex.split(line, comments=True, posix=True)
        except ValueError as exc:
            LOG.warning("ignoring invalid context line %r: %s", raw_line, exc)
            continue
        if fields and fields[0] == "export":
            fields = fields[1:]
        for field in fields:
            if "=" not in field:
                continue
            name, value = field.split("=", 1)
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                env[name] = value
    return env


def scalar(value: object) -> str | None:
    return str(value) if isinstance(value, (str, int, float)) else None


def merge_vrouter_context(local: Mapping[str, str], document: Mapping[str, Any] | None) -> dict[str, str]:
    """Overlay current VRouter template values from OneGate on local credentials."""
    result = dict(local)
    if not document:
        return result
    vrouter = document.get("VROUTER")
    if not isinstance(vrouter, dict):
        return result

    vrouter_id = scalar(vrouter.get("ID"))
    if vrouter_id:
        result["VROUTER_ID"] = vrouter_id
    template = vrouter.get("TEMPLATE")
    if not isinstance(template, dict):
        return result

    for name, value in template.items():
        if name == "NIC":
            continue
        parsed = scalar(value)
        if parsed is not None:
            result[name] = parsed

    nics = template.get("NIC", [])
    if isinstance(nics, dict):
        nics = [nics]
    if not isinstance(nics, list):
        return result
    for fallback_index, nic in enumerate(nics):
        if not isinstance(nic, dict):
            continue
        index = scalar(nic.get("NIC_ID")) or scalar(nic.get("ID")) or str(fallback_index)
        if not index.isdigit():
            continue
        for name, value in nic.items():
            parsed = scalar(value)
            if parsed is not None:
                result[f"ETH{index}_{name}"] = parsed
    return result


def infer_prefix(env: Mapping[str, str], index: int, address: str) -> int:
    if "/" in address:
        return int(address.rsplit("/", 1)[1])
    mask = env.get(f"ETH{index}_MASK")
    if mask:
        return ipaddress.ip_network(f"0.0.0.0/{mask}").prefixlen
    network = env.get(f"ETH{index}_NETWORK")
    if network:
        try:
            return ipaddress.ip_network(network, strict=False).prefixlen if "/" in network else _classful_network_prefix(network)
        except ValueError:
            pass
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv4Address):
        if ip in ipaddress.ip_network("10.0.0.0/8"):
            return 8
        if ip in ipaddress.ip_network("172.16.0.0/12"):
            return 16
        if ip in ipaddress.ip_network("192.168.0.0/16"):
            return 24
        return 24
    return 64


def _classful_network_prefix(network: str) -> int:
    octets = [int(value) for value in network.split(".")]
    if len(octets) != 4:
        raise ValueError(network)
    trailing = 0
    for octet in reversed(octets):
        if octet:
            break
        trailing += 1
    return 32 - trailing * 8 or 32


def with_prefix(env: Mapping[str, str], index: int, address: str) -> str:
    plain = address.strip().split("/", 1)[0]
    return f"{plain}/{infer_prefix(env, index, address.strip())}"


def build_model(env: Mapping[str, str], onegate: Mapping[str, Any] | None = None) -> VRouterModel:
    indexes: set[int] = set()
    for name, value in env.items():
        match = re.match(r"^ETH(\d+)_(?:IP|VROUTER_IP|VROUTER_MANAGEMENT|GATEWAY|MTU)$", name)
        if match and value != "":
            indexes.add(int(match.group(1)))
        match = re.match(r"^ONEAPP_VROUTER_ETH(\d+)_VIP\d+$", name)
        if match and value != "":
            indexes.add(int(match.group(1)))

    interfaces: list[Interface] = []
    for index in sorted(indexes):
        addresses: list[str] = []
        primary = env.get(f"ETH{index}_IP", "").strip()
        if primary:
            addresses.append(with_prefix(env, index, primary))

        vips: list[str] = []
        direct_vip = env.get(f"ETH{index}_VROUTER_IP", "").strip()
        if direct_vip:
            vips.append(with_prefix(env, index, direct_vip))
        for name, value in env.items():
            if re.fullmatch(rf"ONEAPP_VROUTER_ETH{index}_VIP\d+", name) and value.strip():
                vip = with_prefix(env, index, value)
                if vip not in vips:
                    vips.append(vip)

        interfaces.append(
            Interface(
                index=index,
                name=f"eth{index}",
                addresses=tuple(addresses),
                vips=tuple(vips),
                management=truthy(env.get(f"ETH{index}_VROUTER_MANAGEMENT")),
                gateway=env.get(f"ETH{index}_GATEWAY") or None,
                mtu=env.get(f"ETH{index}_MTU") or None,
            )
        )
    return VRouterModel(dict(env), tuple(interfaces), onegate or {})
