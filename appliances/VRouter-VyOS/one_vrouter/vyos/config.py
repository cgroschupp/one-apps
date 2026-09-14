"""Execute a complete VyOS configuration transaction."""

from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Sequence

from ..model import VyOSCommand


LOG = logging.getLogger(__name__)


def run_config_session(commands: Sequence[VyOSCommand], save: bool = False) -> None:
    if not commands:
        return
    script = [
        "#!/bin/vbash",
        "source /opt/vyatta/etc/functions/script-template",
        "configure",
        *(command.render() for command in commands),
        "commit comment 'OpenNebula VRouter reconcile' || exit 1",
    ]
    if save:
        script.append("save || exit 1")
    script.append("exit")

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
        handle.write("\n".join(script) + "\n")
        path = Path(handle.name)
    try:
        path.chmod(0o700)
        LOG.info("applying %d VyOS configuration commands", len(commands))
        subprocess.run(["sg", "vyattacfg", "-c", str(path)], check=True)
    finally:
        path.unlink(missing_ok=True)
