"""Combine independent feature renderers into one desired configuration."""

from __future__ import annotations

from ..features import dhcp, dns, interfaces, loadbalancer, nat, router, vrrp, wireguard
from ..model import DesiredConfig, VRouterModel


FEATURES = (interfaces, vrrp, router, nat, dhcp, dns, loadbalancer, wireguard)


def render(model: VRouterModel) -> DesiredConfig:
    desired = DesiredConfig()
    for feature in FEATURES:
        desired.extend(feature.render(model).commands)
    return desired
