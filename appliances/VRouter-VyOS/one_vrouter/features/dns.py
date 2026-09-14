"""DNS recursion, forwarding ACLs, and OpenNebula endpoint records."""

from __future__ import annotations

from ..model import DesiredConfig, VRouterModel, split_values


def render(model: VRouterModel) -> DesiredConfig:
    config = DesiredConfig()
    if not model.enabled("ONEAPP_VNF_DNS_ENABLED"):
        return config
    selected = set(model.select_interfaces(model.env.get("ONEAPP_VNF_DNS_INTERFACES", ""), default_all=True))
    selected -= model.management_names
    allowed = split_values(model.value("ONEAPP_VNF_DNS_ALLOWED_NETWORKS"))
    if not allowed:
        allowed = sorted({network for interface in model.interfaces if interface.name in selected for network in interface.networks})
    for network in allowed:
        config.set("service", "dns", "forwarding", "allow-from", network)
    for interface in model.interfaces:
        if interface.name not in selected:
            continue
        for address in interface.endpoint_addresses:
            config.set("service", "dns", "forwarding", "listen-address", address.split("/", 1)[0])
    nameservers = split_values(model.value("ONEAPP_VNF_DNS_NAMESERVERS"))
    if nameservers:
        for nameserver in nameservers:
            config.set("service", "dns", "forwarding", "name-server", nameserver)
    elif not model.enabled("ONEAPP_VNF_DNS_USE_ROOTSERVERS", default=True):
        config.set("service", "dns", "forwarding", "system")
    timeout = model.value("ONEAPP_VNF_DNS_UPSTREAM_TIMEOUT")
    if timeout and timeout.isdigit():
        config.set("service", "dns", "forwarding", "timeout", timeout)

    domain = (model.value("ONEAPP_VNF_DNS_CLUSTER_DOMAIN", "vr") or "").strip(".")
    if domain:
        for interface in model.interfaces:
            for offset, address in enumerate(interface.addresses):
                config.set("service", "dns", "forwarding", "authoritative-domain", domain, "records", "a", f"ip{offset}.{interface.name}", "address", address.split("/", 1)[0])
            for offset, address in enumerate(interface.vips):
                config.set("service", "dns", "forwarding", "authoritative-domain", domain, "records", "a", f"vip{offset}.{interface.name}", "address", address.split("/", 1)[0])
    return config
