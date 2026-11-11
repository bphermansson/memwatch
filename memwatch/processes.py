"""Process inspection helpers (top consumers by resident memory)."""

from __future__ import annotations

import os
from dataclasses import dataclass

import psutil


@dataclass
class ProcessInfo:
    pid: int
    name: str
    rss: int
    username: str | None = None
    cmdline: str = ""

    @property
    def human_rss(self) -> str:
        return human_bytes(self.rss)


def human_bytes(value: float) -> str:
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(value) < 1024.0:
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{value:.1f} PiB"


def _uid_of(proc: psutil.Process) -> int | None:
    try:
        return proc.uids().real
    except (psutil.Error, AttributeError, OSError):
        return None


def top_processes(
    count: int = 5,
    exclude_pids: set[int] | None = None,
    min_uid: int | None = None,
) -> list[ProcessInfo]:
    """Return the ``count`` processes using the most RSS.

    ``exclude_pids`` are skipped, and when ``min_uid`` is set, processes owned
    by a lower uid are skipped (e.g. root/system processes).
    """
    exclude_pids = exclude_pids or set()
    result: list[ProcessInfo] = []
    for proc in psutil.process_iter(["pid", "name", "username", "cmdline"]):
        try:
            info = proc.info
            pid = info["pid"]
            if pid in exclude_pids:
                continue
            if min_uid is not None:
                uid = _uid_of(proc)
                if uid is not None and uid < min_uid:
                    continue
            mem = proc.memory_info()
            rss = int(mem.rss)
            if rss <= 0:
                continue
            cmdline = info.get("cmdline") or []
            result.append(
                ProcessInfo(
                    pid=pid,
                    name=info.get("name") or "?",
                    rss=rss,
                    username=info.get("username"),
                    cmdline=" ".join(cmdline)[:200],
                )
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, OSError):
            continue
    result.sort(key=lambda p: p.rss, reverse=True)
    return result[:count]


def ancestors(pid: int | None = None) -> set[int]:
    """Return ``pid`` plus all of its ancestors (walking up the process tree)."""
    pids: set[int] = set()
    try:
        proc = psutil.Process(pid or os.getpid())
    except psutil.Error:
        return pids
    while proc is not None:
        pids.add(proc.pid)
        try:
            proc = proc.parent()
        except psutil.Error:
            break
    return pids
