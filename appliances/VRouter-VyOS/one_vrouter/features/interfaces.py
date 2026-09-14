"""Physical interface addresses and default routes."""

from ..model import DesiredConfig, VRouterModel


def render(model: VRouterModel) -> DesiredConfig:
    config = DesiredConfig()
    vrrp_enabled = model.enabled("ONEAPP_VNF_VYOS_VRRP_ENABLED", default=any(item.vips for item in model.interfaces))
    for interface in model.interfaces:
        for address in interface.addresses:
            config.set("interfaces", "ethernet", interface.name, "address", address)
        if not vrrp_enabled:
            for address in interface.vips:
                config.set("interfaces", "ethernet", interface.name, "address", address)
        if interface.mtu:
            config.set("interfaces", "ethernet", interface.name, "mtu", interface.mtu)
        if interface.gateway:
            config.set("protocols", "static", "route", "0.0.0.0/0", "next-hop", interface.gateway, "distance", interface.index + 1)
    return config
