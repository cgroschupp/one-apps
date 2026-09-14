"""Translate OpenNebula Keepalived settings to native VyOS VRRP."""

from __future__ import annotations

from ..model import DesiredConfig, VRouterModel, truthy


def _number(value: str | None, fallback: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value or "")
        return parsed if minimum <= parsed <= maximum else fallback
    except ValueError:
        return fallback


def render(model: VRouterModel) -> DesiredConfig:
    config = DesiredConfig()
    if not model.enabled("ONEAPP_VNF_VYOS_VRRP_ENABLED", default=any(item.vips for item in model.interfaces)):
        return config
    selected = set(model.select_interfaces(model.env.get("ONEAPP_VNF_KEEPALIVED_INTERFACES", ""), default_all=True))
    selected -= model.management_names
    identity = model.value("ONEAPP_VNF_KEEPALIVED_VRID") or model.value("VROUTER_KEEPALIVED_ID")
    vm_id = _number(model.value("VMID"), 0, 0, 2**31 - 1)
    default_vrid = _number(identity, vm_id % 255 + 1, 1, 255)
    default_priority = _number(model.value("ONEAPP_VNF_KEEPALIVED_PRIORITY"), 100, 1, 255)
    groups: list[str] = []
    for interface in model.interfaces:
        if interface.name not in selected or not interface.vips:
            continue
        upper = interface.name.upper()
        if truthy(model.value(f"ONEAPP_VNF_KEEPALIVED_{upper}_SKIP")):
            continue
        group = f"ONE-{upper}"
        groups.append(group)
        vrid = _number(model.value(f"ONEAPP_VNF_KEEPALIVED_{upper}_VRID"), default_vrid, 1, 255)
        priority = _number(model.value(f"ONEAPP_VNF_KEEPALIVED_{upper}_PRIORITY"), default_priority, 1, 255)
        config.set("high-availability", "vrrp", "group", group, "interface", interface.name)
        config.set("high-availability", "vrrp", "group", group, "vrid", vrid)
        config.set("high-availability", "vrrp", "group", group, "priority", priority)
        for address in interface.vips:
            config.set("high-availability", "vrrp", "group", group, "address", address)
    if len(groups) > 1:
        for group in groups:
            config.set("high-availability", "vrrp", "sync-group", "ONE-VROUTER", "member", group)
    return config
