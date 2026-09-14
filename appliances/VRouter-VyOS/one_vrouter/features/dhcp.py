"""OpenNebula DHCP4 settings rendered as a native VyOS Kea service."""

from __future__ import annotations

import ipaddress

from ..model import DesiredConfig, VRouterModel


def _range(network: ipaddress.IPv4Network) -> tuple[str, str] | None:
    if network.num_addresses <= 4:
        return None
    return str(network.network_address + 2), str(network.broadcast_address - 1)


def render(model: VRouterModel) -> DesiredConfig:
    config = DesiredConfig()
    if not model.enabled("ONEAPP_VNF_DHCP4_ENABLED"):
        return config
    selected = set(model.select_interfaces(model.env.get("ONEAPP_VNF_DHCP4_INTERFACES", ""), default_all=True))
    selected -= model.management_names
    lease_time = model.value("ONEAPP_VNF_DHCP4_LEASE_TIME", "3600") or "3600"
    vyos_15 = not (model.value("ONEAPP_VNF_VYOS_VERSION", "1.5") or "1.5").startswith("1.4")
    subnet_id = 1
    for interface in model.interfaces:
        if interface.name not in selected:
            continue
        explicit = model.value(f"ONEAPP_VNF_DHCP4_{interface.name.upper()}")
        for address in interface.addresses[:1]:
            network = ipaddress.ip_interface(address).network
            if not isinstance(network, ipaddress.IPv4Network):
                continue
            pool = _range(network)
            subnet = str(network)
            if explicit:
                parts = [item.strip() for item in explicit.split(":", 1)]
                subnet = parts[0] or subnet
                if len(parts) == 2 and "-" in parts[1]:
                    start, stop = [item.strip() for item in parts[1].split("-", 1)]
                    pool = (start, stop)
            if not pool:
                continue
            root = ("service", "dhcp-server", "shared-network-name", interface.name.upper(), "subnet", subnet)
            config.set(*root, "subnet-id", subnet_id)
            config.set(*root, "lease", lease_time)
            config.set(*root, "range", "0", "start", pool[0])
            config.set(*root, "range", "0", "stop", pool[1])
            gateway = model.interpolate(model.value(f"ONEAPP_VNF_DHCP4_{interface.name.upper()}_GATEWAY"))
            gateway = gateway or model.interpolate(model.value("ONEAPP_VNF_DHCP4_GATEWAY"))
            dns = model.interpolate(model.value(f"ONEAPP_VNF_DHCP4_{interface.name.upper()}_DNS"))
            dns = dns or model.interpolate(model.value("ONEAPP_VNF_DHCP4_DNS"))
            if gateway:
                config.set(*root, *("option", "default-router") if vyos_15 else ("default-router",), gateway)
            if dns:
                for server in dns.replace(",", " ").split():
                    config.set(*root, *("option", "name-server") if vyos_15 else ("name-server",), server)
            if model.enabled("ONEAPP_VNF_DHCP4_AUTHORITATIVE", default=True):
                config.set("service", "dhcp-server", "shared-network-name", interface.name.upper(), "authoritative")
            router_ip = address.split("/", 1)[0]
            config.set(*root, "exclude", router_ip)
            for vip in interface.vips:
                if ipaddress.ip_address(vip.split("/", 1)[0]) in network:
                    config.set(*root, "exclude", vip.split("/", 1)[0])
            subnet_id += 1
    return config
