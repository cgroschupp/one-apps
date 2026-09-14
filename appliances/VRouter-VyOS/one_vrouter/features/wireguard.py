"""WireGuard material lifecycle and native VyOS interface rendering."""

from __future__ import annotations

import base64
import ipaddress
import json
import logging
import subprocess
import time
from pathlib import Path
from typing import Any, Mapping

from ..model import DesiredConfig, VRouterModel


LOG = logging.getLogger(__name__)
DEFAULT_MATERIAL_FILE = Path("/config/one-vyos-vrouter/wireguard.json")


def _generate(command: list[str], input_text: str | None = None) -> str:
    result = subprocess.run(command, input=input_text, text=True, capture_output=True, check=True)
    return result.stdout.strip()


def _vm_ids(snapshot: Mapping[str, Any], fallback: str | None) -> list[str]:
    vrouter = snapshot.get("vrouter", {}).get("VROUTER", {})
    ids = vrouter.get("VMS", {}).get("ID", []) if isinstance(vrouter, dict) else []
    if not isinstance(ids, list):
        ids = [ids]
    result = [str(value) for value in ids if value not in (None, "")]
    return result or ([fallback] if fallback else [])


def _remote_material(snapshot: Mapping[str, Any]) -> dict[str, Any] | None:
    selected: tuple[int, str] | None = None
    for document in snapshot.get("vms", []):
        template = document.get("VM", {}).get("USER_TEMPLATE", {}) if isinstance(document, dict) else {}
        encoded = template.get("ONEGATE_VNF_WG_SERVER") if isinstance(template, dict) else None
        if not encoded:
            continue
        try:
            timestamp = int(template.get("ONEGATE_VNF_WG_SERVER_TIMESTAMP", 0))
            server = base64.b64decode(str(encoded), validate=True).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            continue
        if selected is None or timestamp > selected[0]:
            selected = (timestamp, server)
    return {"server": selected[1], "clients": []} if selected else None


def _make_material(model: VRouterModel) -> dict[str, Any]:
    subnet = ipaddress.ip_network(model.value("ONEAPP_VNF_WG_SUBNET", "169.254.33.0/24") or "169.254.33.0/24")
    if not isinstance(subnet, ipaddress.IPv4Network) or subnet.num_addresses < 4:
        raise ValueError("ONEAPP_VNF_WG_SUBNET must be an IPv4 subnet with usable addresses")
    count = int(model.value("ONEAPP_VNF_WG_PEERS", "5") or "5")
    listen_port = model.value("ONEAPP_VNF_WG_LISTEN_PORT", "51820") or "51820"
    outside = model.interface(model.value("ONEAPP_VNF_WG_INTERFACE_OUT", "") or "")
    inside = model.interface(model.value("ONEAPP_VNF_WG_INTERFACE_IN", "") or "")
    if outside is None or not outside.addresses or outside.management:
        raise ValueError("ONEAPP_VNF_WG_INTERFACE_OUT must select a non-management interface with an address")
    if inside is None:
        raise ValueError("ONEAPP_VNF_WG_INTERFACE_IN must select an interface")
    endpoint = outside.addresses[0].split("/", 1)[0]
    allowed = ",".join(inside.networks)
    server_private = _generate(["wg", "genkey"])
    server_public = _generate(["wg", "pubkey"], server_private + "\n")
    server_lines = [
        "[Interface]",
        f"Address = {subnet.network_address + 1}/{subnet.prefixlen}",
        f"ListenPort = {listen_port}",
        f"PrivateKey = {server_private}",
    ]
    clients: list[str] = []
    for index in range(count):
        address = subnet.network_address + index + 2
        if address >= subnet.broadcast_address:
            break
        private = _generate(["wg", "genkey"])
        public = _generate(["wg", "pubkey"], private + "\n")
        shared = _generate(["wg", "genpsk"])
        server_lines.extend(
            [
                "",
                "[Peer]",
                f"PublicKey = {public}",
                f"PresharedKey = {shared}",
                f"AllowedIPs = {address}/32",
            ]
        )
        clients.append(
            "\n".join(
                [
                    "[Interface]",
                    f"Address = {address}/{subnet.prefixlen}",
                    f"PrivateKey = {private}",
                    "",
                    "[Peer]",
                    f"Endpoint = {endpoint}:{listen_port}",
                    f"PublicKey = {server_public}",
                    f"PresharedKey = {shared}",
                    f"AllowedIPs = {allowed}",
                    "",
                ]
            )
        )
    return {"server": "\n".join(server_lines) + "\n", "clients": clients}


def _load_material(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value.get("server"), str) else None
    except (OSError, ValueError, AttributeError):
        return None


def _save_material(path: Path, material: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(material, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)


def prepare(
    env: Mapping[str, str],
    snapshot: Mapping[str, Any],
    client: Any | None,
    material_file: Path = DEFAULT_MATERIAL_FILE,
    generate: bool = True,
) -> dict[str, str]:
    result = dict(env)
    probe = VRouterModel(result, tuple(), snapshot)
    if not probe.enabled("ONEAPP_VNF_WG_ENABLED"):
        return result
    material = _remote_material(snapshot) or _load_material(material_file)
    members = _vm_ids(snapshot, result.get("VMID"))
    current_vm = result.get("VMID")
    leader = min(members, key=lambda value: int(value) if value.isdigit() else 2**63) if members else current_vm
    may_generate = not members or current_vm is None or current_vm == leader
    if material is None and generate and may_generate:
        # Build the complete model here because endpoint and subnet discovery need NICs.
        from ..context import build_model

        material = _make_material(build_model(result, snapshot))
        _save_material(material_file, material)
    if material is None:
        return result
    result["ONEGATE_VNF_WG_SERVER"] = base64.b64encode(material["server"].encode("utf-8")).decode("ascii")

    remote_exists = _remote_material(snapshot) is not None
    if client is not None and not remote_exists:
        timestamp = str(int(time.time()))
        values = [
            *(f"ONEGATE_VNF_WG_PEER{index}={base64.b64encode(value.encode()).decode('ascii')}" for index, value in enumerate(material.get("clients", []))),
            f"ONEGATE_VNF_WG_SERVER={result['ONEGATE_VNF_WG_SERVER']}",
            f"ONEGATE_VNF_WG_SERVER_TIMESTAMP={timestamp}",
        ]
        for vm_id in members:
            try:
                client.vm_update("\n".join(values), vm_id)
            except Exception as exc:  # retry publication on the next poll
                LOG.warning("cannot publish WireGuard material to VM %s: %s", vm_id, exc)
    return result


def _parse_server(value: str) -> tuple[dict[str, str], list[dict[str, str]]]:
    interface: dict[str, str] = {}
    peers: list[dict[str, str]] = []
    current = interface
    for raw_line in value.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower() == "[interface]":
            current = interface
            continue
        if line.lower() == "[peer]":
            current = {}
            peers.append(current)
            continue
        if "=" in line:
            key, content = [item.strip() for item in line.split("=", 1)]
            current[key.lower()] = content
    return interface, peers


def render(model: VRouterModel) -> DesiredConfig:
    config = DesiredConfig()
    if not model.enabled("ONEAPP_VNF_WG_ENABLED"):
        return config
    encoded = model.value("ONEGATE_VNF_WG_SERVER")
    if not encoded:
        return config
    try:
        server = base64.b64decode(encoded, validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        LOG.warning("ignoring invalid ONEGATE_VNF_WG_SERVER")
        return config
    interface, peers = _parse_server(server)
    device = model.value("ONEAPP_VNF_WG_DEVICE", "wg0") or "wg0"
    root = ("interfaces", "wireguard", device)
    for address in [item.strip() for item in interface.get("address", "").split(",") if item.strip()]:
        config.set(*root, "address", address)
    if interface.get("listenport"):
        config.set(*root, "port", interface["listenport"])
    if interface.get("privatekey"):
        config.set(*root, "private-key", interface["privatekey"])
    config.delete(*root, "ip", "disable-forwarding")
    for index, peer in enumerate(peers):
        peer_root = (*root, "peer", f"peer-{index}")
        if peer.get("publickey"):
            config.set(*peer_root, "public-key", peer["publickey"])
        if peer.get("presharedkey"):
            config.set(*peer_root, "preshared-key", peer["presharedkey"])
        for allowed in [item.strip() for item in peer.get("allowedips", "").split(",") if item.strip()]:
            config.set(*peer_root, "allowed-ips", allowed)
    return config
