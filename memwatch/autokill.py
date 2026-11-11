"""Opt-in auto-kill of the largest memory consumer.

Disabled by default.  Even when enabled it only acts at ``min_severity`` or
above, refuses to touch protected/system processes, requires at least two safe
candidates, and waits out a grace window during which memory may recover.
"""

from __future__ import annotations

import logging
import signal
import time

import psutil

from .monitor import SEVERITY_BY_NAME, Severity
from .processes import ProcessInfo, ancestors, top_processes

log = logging.getLogger("memwatch.autokill")


class AutoKiller:
    def __init__(
        self,
        config: dict,
        notifier,
        self_pids: set[int] | None = None,
        force_enabled: bool = False,
        dry_run: bool = False,
    ):
        self.cfg = config["auto_kill"]
        self.notifier = notifier
        self.self_pids = set(self_pids) if self_pids is not None else ancestors()
        self.protected = {str(name).lower() for name in self.cfg.get("protected", [])}
        self.min_severity = SEVERITY_BY_NAME[str(self.cfg["min_severity"]).lower()]
        self.cfg_enabled = bool(self.cfg.get("enabled")) or force_enabled
        self.dry_run = dry_run
        self.last_kill = 0.0

    @property
    def enabled(self) -> bool:
        return self.cfg_enabled and not self.dry_run

    def _is_protected(self, proc: ProcessInfo) -> bool:
        name = proc.name.lower()
        if name in self.protected:
            return True
        first = proc.cmdline.split(" ", 1)[0].rsplit("/", 1)[-1].lower() if proc.cmdline else ""
        return first in self.protected

    def select_candidates(self, count: int | None = None) -> list[ProcessInfo]:
        """Return safe kill candidates, largest first."""
        count = count or max(1, int(self.cfg.get("max_kills_per_event", 1)))
        min_uid = None if self.cfg.get("allow_root") else 1000
        pool = top_processes(count=count * 5, exclude_pids=self.self_pids, min_uid=min_uid)
        safe: list[ProcessInfo] = []
        for proc in pool:
            if proc.pid == 1:
                continue
            if self._is_protected(proc):
                continue
            safe.append(proc)
            if len(safe) >= count:
                break
        return safe

    def maybe_kill(self, sample, severity: Severity, resample_severity) -> bool:
        """Consider killing a process.  Returns True if a process was signalled."""
        if not self.cfg_enabled:
            return False
        if severity < self.min_severity:
            return False

        now = time.time()
        if now - self.last_kill < float(self.cfg.get("cooldown", 0)):
            log.info("auto-kill suppressed by cooldown (%.0fs remaining)",
                     float(self.cfg.get("cooldown", 0)) - (now - self.last_kill))
            return False

        # Look at more candidates than we intend to kill so the "at least two
        # safe candidates" safety check reflects the real pool.
        candidates = self.select_candidates(
            count=max(2, int(self.cfg.get("max_kills_per_event", 1)))
        )
        if len(candidates) < 2:
            log.warning(
                "auto-kill: only %d safe candidate(s) found; refusing to act",
                len(candidates),
            )
            return False

        target = candidates[0]
        grace = int(self.cfg.get("grace_seconds", 10))
        self.notifier.notify(
            "memwatch: auto-kill armed",
            f"Memory {severity.label}. Will terminate {target.name} "
            f"(pid {target.pid}, {target.human_rss}) in {grace}s "
            f"unless memory recovers.",
            Severity.CRITICAL,
        )

        if self.dry_run:
            log.warning(
                "[dry-run] would terminate %s (pid %s, %s)",
                target.name, target.pid, target.human_rss,
            )
            return False

        if grace > 0:
            deadline = time.time() + grace
            while time.time() < deadline:
                time.sleep(min(1.0, max(0.0, deadline - time.time())))
                if resample_severity() < self.min_severity:
                    log.info("auto-kill aborted: memory recovered during grace window")
                    self.notifier.notify(
                        "memwatch: auto-kill cancelled",
                        f"{target.name} left running; memory recovered.",
                        Severity.WARN,
                    )
                    return False

        return self._terminate(target)

    def _terminate(self, target: ProcessInfo) -> bool:
        try:
            proc = psutil.Process(target.pid)
        except psutil.NoSuchProcess:
            log.info("auto-kill: pid %s already exited", target.pid)
            return False

        sig_name = str(self.cfg.get("kill_signal", "SIGTERM")).upper()
        if not sig_name.startswith("SIG"):
            sig_name = "SIG" + sig_name
        sig = getattr(signal, sig_name)

        try:
            proc.send_signal(sig)
            log.warning(
                "auto-kill: sent %s to %s (pid %s, %s)",
                sig_name, target.name, target.pid, target.human_rss,
            )
        except psutil.Error as exc:
            log.error("auto-kill: failed to signal pid %s: %s", target.pid, exc)
            return False

        if sig_name != "SIGKILL":
            timeout = float(self.cfg.get("sigkill_timeout", 5))
            try:
                proc.wait(timeout=timeout)
            except psutil.TimeoutExpired:
                log.warning(
                    "auto-kill: pid %s survived %s; escalating to SIGKILL",
                    target.pid, sig_name,
                )
                try:
                    proc.kill()
                except psutil.Error as exc:
                    log.error("auto-kill: SIGKILL failed for pid %s: %s", target.pid, exc)
                    return False
            except psutil.Error:
                pass

        self.last_kill = time.time()
        self.notifier.notify(
            "memwatch: process terminated",
            f"Terminated {target.name} (pid {target.pid}, {target.human_rss}).",
            Severity.WARN,
        )
        return True
