"""Desktop notifications (notify-send) plus optional sound."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess

from .monitor import SEVERITY_BY_NAME, Severity

log = logging.getLogger("memwatch.notifier")

_URGENCY = {
    Severity.NORMAL: "low",
    Severity.WARN: "normal",
    Severity.CRITICAL: "critical",
    Severity.EMERGENCY: "critical",
}

_ICON = {
    Severity.NORMAL: "dialog-information",
    Severity.WARN: "dialog-warning",
    Severity.CRITICAL: "dialog-error",
    Severity.EMERGENCY: "dialog-error",
}


def desktop_available() -> bool:
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


class Notifier:
    def __init__(self, config: dict, desktop: bool | None = None):
        notes = config["notifications"]
        self.desktop = notes.get("desktop", True) if desktop is None else desktop
        self.sound = bool(notes.get("sound", False))
        self.sound_file = notes.get("sound_file")
        self.sound_min_severity = SEVERITY_BY_NAME.get(
            str(notes.get("sound_min_severity", "critical")).lower(), Severity.CRITICAL
        )
        self.top_processes = int(notes.get("top_processes", 5))

    def notify(
        self,
        title: str,
        body: str,
        severity: Severity = Severity.WARN,
        urgency: str | None = None,
    ) -> bool:
        log.warning("%s: %s", title, body.replace("\n", " | "))

        delivered = False
        if self.sound and severity >= self.sound_min_severity:
            self._play_sound()
            delivered = True

        if not (self.desktop and desktop_available()):
            if self.desktop:
                log.debug("no DISPLAY/WAYLAND_DISPLAY; skipping desktop notification")
            return delivered
        if not shutil.which("notify-send"):
            log.debug("notify-send not found; skipping desktop notification")
            return delivered

        cmd = [
            "notify-send",
            "--app-name=memwatch",
            f"--urgency={urgency or _URGENCY.get(severity, 'normal')}",
            f"--icon={_ICON.get(severity, 'dialog-warning')}",
            "--category=system",
            title,
            body,
        ]
        try:
            subprocess.run(cmd, check=False, timeout=10)
            delivered = True
        except (OSError, subprocess.SubprocessError) as exc:
            log.debug("notify-send failed: %s", exc)

        return delivered

    def _play_sound(self) -> None:
        if not self.sound_file:
            return
        for player in ("paplay", "pw-play", "aplay"):
            if shutil.which(player):
                try:
                    subprocess.run(
                        [player, self.sound_file], check=False, timeout=10
                    )
                except (OSError, subprocess.SubprocessError):
                    pass
                return


def build_body(sample, severity: Severity, processes) -> str:
    from .monitor import format_sample

    parts = [format_sample(sample)]
    if processes:
        parts.append("")
        parts.append("Top processes by memory:")
        for proc in processes:
            parts.append(f"  {proc.human_rss:>9}  {proc.name} (pid {proc.pid})")
    return "\n".join(parts)
