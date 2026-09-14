"""IPv4 forwarding using native VyOS configuration nodes."""

from ..model import DesiredConfig, VRouterModel


def render(model: VRouterModel) -> DesiredConfig:
    config = DesiredConfig()
    enabled = model.enabled("ONEAPP_VNF_ROUTER4_ENABLED", default=bool(model.value("VROUTER_ID")))
    selected = model.select_interfaces(model.env.get("ONEAPP_VNF_ROUTER4_INTERFACES", ""), default_all=True)
    forwarded = set(selected) - model.management_names if enabled else set()
    if forwarded:
        config.delete("system", "ip", "disable-forwarding")
    else:
        config.set("system", "ip", "disable-forwarding")
    for interface in model.interfaces:
        if interface.name in forwarded:
            config.delete("interfaces", "ethernet", interface.name, "ip", "disable-forwarding")
        else:
            config.set("interfaces", "ethernet", interface.name, "ip", "disable-forwarding")
    return config
