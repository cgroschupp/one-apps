"""Track the exact VyOS leaves owned by the controller."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Sequence

from ..model import DesiredConfig, VyOSCommand
from .config import run_config_session


LOG = logging.getLogger(__name__)
DEFAULT_STATE_FILE = Path("/run/one-vyos-vrouter/state.json")


def read_state(path: Path = DEFAULT_STATE_FILE) -> list[VyOSCommand]:
    if not path.exists():
        return []
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return [VyOSCommand.from_dict(item) for item in value.get("commands", [])]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        LOG.warning("ignoring invalid state file %s: %s", path, exc)
        return []


def write_state(commands: Sequence[VyOSCommand], path: Path = DEFAULT_STATE_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps({"commands": [item.as_dict() for item in commands]}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.chmod(0o600)
    temporary.replace(path)


def calculate_delta(previous: Sequence[VyOSCommand], desired: Sequence[VyOSCommand]) -> list[VyOSCommand]:
    if list(previous) == list(desired):
        return []
    desired_paths = {command.path for command in desired}
    cleanup = [command.delete() for command in reversed(previous) if command.action == "set" and command.path not in desired_paths]
    result: list[VyOSCommand] = []
    for command in [*cleanup, *desired]:
        if command not in result:
            result.append(command)
    return result


def apply_desired(
    desired: DesiredConfig,
    state_file: Path = DEFAULT_STATE_FILE,
    save: bool = False,
    dry_run: bool = False,
) -> list[VyOSCommand]:
    previous = read_state(state_file)
    delta = calculate_delta(previous, desired.commands)
    if dry_run:
        for command in delta:
            print(command.render())
        return delta
    if not delta:
        LOG.debug("desired VyOS configuration is unchanged")
        return []
    run_config_session(delta, save=save)
    write_state(desired.commands, state_file)
    return delta
