"""Long-running OpenNebula-to-VyOS reconciliation loop."""

from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import threading
from pathlib import Path
from typing import Any, Mapping

from .context import DEFAULT_CONTEXT_FILE, build_model, load_context, merge_vrouter_context
from .features import interfaces, wireguard
from .onegate import OneGateClient, OneGateError
from .vyos.renderer import render
from .vyos.state import DEFAULT_STATE_FILE, apply_desired


LOG = logging.getLogger("one-vyos-vrouter")
DEFAULT_SNAPSHOT_FILE = Path("/config/one-vyos-vrouter/onegate.json")
DEFAULT_POLL_INTERVAL = 30


def load_snapshot(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) and isinstance(value.get("vrouter"), dict) else None
    except (OSError, ValueError):
        return None


def save_snapshot(path: Path, snapshot: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)


def poll_interval(env: Mapping[str, str], override: float | None = None) -> float:
    if override is not None:
        return max(1.0, override)
    raw = env.get("ONEAPP_VNF_VYOS_REFRESH_RATE", str(DEFAULT_POLL_INTERVAL))
    try:
        return max(1.0, float(raw or DEFAULT_POLL_INTERVAL))
    except ValueError:
        LOG.warning("invalid ONEAPP_VNF_VYOS_REFRESH_RATE=%r; using %ss", raw, DEFAULT_POLL_INTERVAL)
        return float(DEFAULT_POLL_INTERVAL)


class Reconciler:
    def __init__(
        self,
        context_file: Path = DEFAULT_CONTEXT_FILE,
        state_file: Path = DEFAULT_STATE_FILE,
        snapshot_file: Path = DEFAULT_SNAPSHOT_FILE,
        interval: float | None = None,
        save: bool = False,
        dry_run: bool = False,
        use_onegate: bool = True,
    ) -> None:
        self.context_file = context_file
        self.state_file = state_file
        self.snapshot_file = snapshot_file
        self.interval = interval
        self.save = save
        self.dry_run = dry_run
        self.use_onegate = use_onegate
        self.stop_event = threading.Event()
        self.last_snapshot = load_snapshot(snapshot_file)
        self._bootstrapped = False

    def stop(self, *_: object) -> None:
        self.stop_event.set()

    def _bootstrap_network(self, env: Mapping[str, str]) -> None:
        if self._bootstrapped or self.dry_run:
            return
        model = build_model(env)
        bootstrap_state = self.state_file.with_name("bootstrap-state.json")
        apply_desired(interfaces.render(model), bootstrap_state, save=False)
        self._bootstrapped = True

    def reconcile_once(self) -> bool:
        local = load_context(self.context_file)
        client: OneGateClient | None = None
        snapshot = self.last_snapshot if self.use_onegate else None
        onegate_required = False
        poll_succeeded = True
        if self.use_onegate:
            client = OneGateClient(local)
            onegate_required = client.available
            if client.available:
                self._bootstrap_network(local)
                try:
                    LOG.info("polling OneGate %s/vrouter", client.endpoint)
                    snapshot = client.snapshot(include_dynamic=True).as_mapping()
                    self.last_snapshot = snapshot
                    if not self.dry_run:
                        save_snapshot(self.snapshot_file, snapshot)
                except OneGateError as exc:
                    poll_succeeded = False
                    LOG.warning("OneGate poll failed: %s", exc)

        if onegate_required and snapshot is None:
            LOG.warning("no successful OneGate snapshot yet; keeping bootstrap network configuration")
            return False
        snapshot = snapshot or {}
        vrouter_document = snapshot.get("vrouter") if isinstance(snapshot, dict) else None
        effective = merge_vrouter_context(local, vrouter_document if isinstance(vrouter_document, dict) else None)
        effective = wireguard.prepare(
            effective,
            snapshot,
            client,
            material_file=wireguard.DEFAULT_MATERIAL_FILE,
            generate=not self.dry_run,
        )
        model = build_model(effective, snapshot)
        delta = apply_desired(render(model), self.state_file, save=self.save, dry_run=self.dry_run)
        if delta:
            LOG.info("reconciled %d VyOS commands", len(delta))
        return poll_succeeded

    def run(self, once: bool = False) -> int:
        failures = 0
        while not self.stop_event.is_set():
            try:
                success = self.reconcile_once()
                failures = 0 if success else failures + 1
            except Exception:
                failures += 1
                LOG.exception("reconcile failed")
                if once:
                    return 1
            if once or self.dry_run:
                break
            env = load_context(self.context_file)
            base = poll_interval(env, self.interval)
            delay = min(base * (2 ** min(failures, 4)), 300.0)
            self.stop_event.wait(delay)
        return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Reconcile OpenNebula VRouter settings into VyOS")
    parser.add_argument("--context-file", type=Path, default=DEFAULT_CONTEXT_FILE)
    parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE_FILE)
    parser.add_argument("--snapshot-file", type=Path, default=DEFAULT_SNAPSHOT_FILE)
    parser.add_argument("--poll-interval", type=float, help="OneGate polling interval in seconds")
    parser.add_argument("--once", action="store_true", help="perform one reconciliation and exit")
    parser.add_argument("--no-onegate", action="store_true", help="use only the local context")
    parser.add_argument("--save", action="store_true", help="save commits to config.boot")
    parser.add_argument("--dry-run", action="store_true", help="print commands without applying them")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    reconciler = Reconciler(
        context_file=args.context_file,
        state_file=args.state_file,
        snapshot_file=args.snapshot_file,
        interval=args.poll_interval,
        save=args.save,
        dry_run=args.dry_run,
        use_onegate=not args.no_onegate,
    )
    signal.signal(signal.SIGTERM, reconciler.stop)
    signal.signal(signal.SIGINT, reconciler.stop)
    return reconciler.run(once=args.once)


if __name__ == "__main__":
    raise SystemExit(main())
