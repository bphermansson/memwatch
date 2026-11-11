"""Command line interface for memwatch."""

from __future__ import annotations

import argparse
import json
import logging
import logging.handlers
import sys
import time
from pathlib import Path

from . import __version__, config as config_mod, service
from .autokill import AutoKiller
from .monitor import (
    SEVERITY_BY_NAME,
    Severity,
    classify,
    format_sample,
    simulated_sample,
    take_sample,
)
from .notifier import Notifier, build_body
from .processes import top_processes

log = logging.getLogger("memwatch")


def setup_logging(level: str, logfile: Path | None = None) -> None:
    root = logging.getLogger("memwatch")
    root.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    root.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    stream = logging.StreamHandler(sys.stderr)
    stream.setFormatter(fmt)
    root.addHandler(stream)

    if logfile is not None:
        try:
            logfile.parent.mkdir(parents=True, exist_ok=True)
            handler = logging.handlers.RotatingFileHandler(
                logfile, maxBytes=1_000_000, backupCount=3
            )
            handler.setFormatter(fmt)
            root.addHandler(handler)
        except OSError as exc:
            root.warning("cannot open log file %s: %s", logfile, exc)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="memwatch",
        description="Warn before Fedora runs out of memory.",
    )
    parser.add_argument("--config", type=Path, default=None, help="config file path")
    parser.add_argument("--version", action="version", version=f"memwatch {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run the monitoring loop")
    run.add_argument("--interval", type=float, default=None, help="seconds between polls")
    run.add_argument("--once", action="store_true", help="sample once and exit")
    run.add_argument(
        "--auto-kill", action="store_true", help="force-enable auto-kill for this run"
    )
    run.add_argument("--no-desktop", action="store_true", help="disable desktop popups")

    check = sub.add_parser("check", help="one-shot memory check (exit code = severity)")
    check.add_argument(
        "--simulate", choices=["normal", "warn", "critical", "emergency"],
        help="use fake memory stats at the given level",
    )
    check.add_argument(
        "--auto-kill-dry-run", action="store_true",
        help="show which process auto-kill would target",
    )
    check.add_argument("--json", action="store_true", help="print JSON")

    install = sub.add_parser("install", help="install the systemd user service")
    install.add_argument("--force", action="store_true", help="overwrite existing unit")
    install.add_argument("--no-start", action="store_true", help="do not start it now")

    sub.add_parser("uninstall", help="remove the systemd user service")
    sub.add_parser("status", help="show the service status")
    config = sub.add_parser("config", help="print config location and values")
    config.add_argument("--init", action="store_true", help="write the default config file")

    return parser


def cmd_run(args, cfg) -> int:
    general = cfg["general"]
    thresholds = cfg["thresholds"]
    psi_cfg = cfg["psi"]
    notifier = Notifier(cfg, desktop=not args.no_desktop)
    killer = AutoKiller(cfg, notifier, force_enabled=args.auto_kill)

    interval = args.interval or float(general["poll_interval"])
    elevated = float(general.get("elevated_poll_interval", interval))
    cooldown = float(general["cooldown"])
    psi_enabled = bool(psi_cfg.get("enabled", True))

    current = Severity.NORMAL
    last_notify = {sev: 0.0 for sev in Severity}

    if general.get("startup_notify"):
        notifier.notify(
            "memwatch started", "Memory watchdog is running.", Severity.NORMAL
        )
    log.info(
        "memwatch started (interval=%ss, auto_kill=%s)", interval, killer.cfg_enabled
    )

    try:
        while True:
            sample = take_sample(psi_enabled)
            severity = classify(sample, thresholds, psi_cfg, current)
            if severity != current:
                log.info("severity %s -> %s", current.label, severity.label)

            if severity >= Severity.WARN:
                now = time.time()
                if severity > current or now - last_notify[severity] >= cooldown:
                    procs = top_processes(
                        notifier.top_processes, exclude_pids=killer.self_pids
                    )
                    notifier.notify(
                        f"Memory {severity.label}",
                        build_body(sample, severity, procs),
                        severity,
                    )
                    last_notify[severity] = now

                killer.maybe_kill(
                    sample,
                    severity,
                    resample_severity=lambda: classify(
                        take_sample(psi_enabled), thresholds, psi_cfg, current
                    ),
                )

            current = severity
            if args.once:
                break
            time.sleep(elevated if severity >= Severity.WARN else interval)
    except KeyboardInterrupt:
        log.info("memwatch stopped")
    return 0


def cmd_check(args, cfg) -> int:
    if args.simulate:
        sample = simulated_sample(SEVERITY_BY_NAME[args.simulate])
    else:
        sample = take_sample(bool(cfg["psi"].get("enabled", True)))

    severity = classify(sample, cfg["thresholds"], cfg["psi"])
    procs = top_processes(int(cfg["notifications"]["top_processes"]))

    if args.json:
        print(json.dumps({
            "severity": severity.label,
            "percent": round(sample.percent, 1),
            "available_bytes": sample.available,
            "total_bytes": sample.total,
            "swap_percent": round(sample.swap_percent, 1),
            "psi_some_avg10": sample.psi_some_avg10,
            "top_processes": [
                {"pid": p.pid, "name": p.name, "rss": p.rss} for p in procs
            ],
        }, indent=2))
    else:
        print(format_sample(sample))
        if procs:
            print("\nTop processes by memory:")
            for proc in procs:
                print(f"  {proc.human_rss:>9}  {proc.name} (pid {proc.pid})")
        print(f"\nSeverity: {severity.label.upper()}")

    notifier = Notifier(cfg)
    if severity >= Severity.WARN:
        notifier.notify(
            f"Memory {severity.label}", build_body(sample, severity, procs), severity
        )

    if args.auto_kill_dry_run:
        killer = AutoKiller(cfg, notifier, dry_run=True)
        candidates = killer.select_candidates(
            count=max(3, int(cfg["auto_kill"].get("max_kills_per_event", 1)))
        )
        print("\nAuto-kill dry run:")
        if candidates:
            for proc in candidates:
                print(f"  would target {proc.human_rss:>9}  {proc.name} (pid {proc.pid})")
        else:
            print("  no safe candidates found")

    return int(severity)


def cmd_config(args, cfg) -> int:
    path = args.config or config_mod.config_path()
    if args.init:
        written = config_mod.write_default_config(path)
        print(f"wrote {written}")
    print(f"config file: {path}")
    print(f"exists:      {path.exists()}")
    print()
    print(config_mod.dumps(cfg))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command in ("install", "uninstall", "status"):
        if args.command == "install":
            setup_logging("info")
            return service.install(force=args.force, start=not args.no_start)
        if args.command == "uninstall":
            setup_logging("info")
            return service.uninstall()
        return service.status()

    try:
        cfg = config_mod.load_config(args.config)
    except config_mod.ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2

    setup_logging(cfg["general"]["log_level"], config_mod.log_path())

    if args.command == "run":
        return cmd_run(args, cfg)
    if args.command == "check":
        return cmd_check(args, cfg)
    if args.command == "config":
        return cmd_config(args, cfg)

    parser.error(f"unknown command {args.command!r}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
