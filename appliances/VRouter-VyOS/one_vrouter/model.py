"""Normalized controller model shared by all feature renderers."""

from __future__ import annotations

import ipaddress
import re
import shlex
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping


def truthy(value: str | None, default: bool = False) -> bool:
    if value is None or value.strip() == "":
        return default
    return value.strip().upper() in {"1", "TRUE", "YES", "ON", "Y"}


def split_values(value: str | None) -> list[str]:
    if value is None:
        return []
    return [item for item in re.split(r"[\s,;]+", value.strip()) if item]


def interface_sort_key(name: str) -> tuple[str, int | str]:
    match = re.fullmatch(r"([a-zA-Z_-]+)(\d+)", name)
    return (match.group(1), int(match.group(2))) if match else (name, name)


@dataclass(frozen=True)
class VyOSCommand:
    action: str
    path: tuple[str, ...]

    def render(self) -> str:
        return " ".join((self.action, *(shlex.quote(part) for part in self.path)))

    def as_dict(self) -> dict[str, object]:
        return {"action": self.action, "path": list(self.path)}

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "VyOSCommand":
        path = value.get("path")
        if not isinstance(path, list):
            raise ValueError("command path must be a list")
        return cls(str(value["action"]), tuple(str(item) for item in path))

    def delete(self) -> "VyOSCommand":
        return VyOSCommand("delete", self.path)


@dataclass
class DesiredConfig:
    commands: list[VyOSCommand] = field(default_factory=list)

    def add(self, action: str, *path: object) -> None:
        command = VyOSCommand(action, tuple(str(item) for item in path))
        if command not in self.commands:
            self.commands.append(command)

    def set(self, *path: object) -> None:
        self.add("set", *path)

    def delete(self, *path: object) -> None:
        self.add("delete", *path)

    def extend(self, commands: Iterable[VyOSCommand]) -> None:
        for command in commands:
            if command not in self.commands:
                self.commands.append(command)


@dataclass(frozen=True)
class Interface:
    index: int
    name: str
    addresses: tuple[str, ...]
    vips: tuple[str, ...]
    management: bool = False
    gateway: str | None = None
    mtu: str | None = None

    @property
    def endpoint_addresses(self) -> tuple[str, ...]:
        return self.addresses + self.vips

    @property
    def networks(self) -> tuple[str, ...]:
        result: list[str] = []
        for address in self.endpoint_addresses:
            network = str(ipaddress.ip_interface(address).network)
            if network not in result:
                result.append(network)
        return tuple(result)


@dataclass(frozen=True)
class VRouterModel:
    env: Mapping[str, str]
    interfaces: tuple[Interface, ...]
    onegate: Mapping[str, Any] = field(default_factory=dict)

    def value(self, name: str, default: str | None = None) -> str | None:
        value = self.env.get(name, default)
        return value if value is None or value != "" else default

    def enabled(self, name: str, default: bool = False) -> bool:
        return truthy(self.env.get(name), default)

    @property
    def interface_names(self) -> list[str]:
        return [interface.name for interface in self.interfaces]

    @property
    def management_names(self) -> set[str]:
        return {interface.name for interface in self.interfaces if interface.management}

    @property
    def address_index(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for interface in self.interfaces:
            for address in interface.endpoint_addresses:
                result[address.split("/", 1)[0].lower()] = interface.name
        return result

    @property
    def interpolation(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for interface in self.interfaces:
            for offset, address in enumerate(interface.addresses):
                plain = address.split("/", 1)[0]
                result[f"ETH{interface.index}_IP{offset}"] = plain
                result.setdefault(f"ETH{interface.index}_EP{offset}", plain)
            for offset, address in enumerate(interface.vips):
                plain = address.split("/", 1)[0]
                result[f"ETH{interface.index}_VIP{offset}"] = plain
                result[f"ETH{interface.index}_EP{offset}"] = plain
        return result

    def interpolate(self, value: str | None) -> str | None:
        if value is None:
            return None
        match = re.fullmatch(r"<([A-Za-z0-9_]+)>", value.strip())
        return self.interpolation.get(match.group(1), value) if match else value

    def select_interfaces(self, expression: str | None, default_all: bool = False) -> list[str]:
        if expression is None:
            return self.interface_names if default_all else []

        included: set[str] = set()
        excluded: set[str] = set()
        for raw in split_values(expression):
            is_excluded = raw.startswith("!")
            token = raw[1:] if is_excluded else raw
            token = token.split("@", 1)[0]
            token = token.split("/", 1)[0] if not re.fullmatch(r"eth\d+", token) else token
            name = token if re.fullmatch(r"eth\d+", token) else self.address_index.get(token.lower())
            if name:
                (excluded if is_excluded else included).add(name)

        if not included and (default_all or expression.strip() == ""):
            included.update(self.interface_names)
        return sorted(included - excluded, key=interface_sort_key)

    def interface(self, name: str) -> Interface | None:
        return next((item for item in self.interfaces if item.name == name), None)
