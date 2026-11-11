"""Configuration loading, validation and default generation.

Config lives at ``$XDG_CONFIG_HOME/memwatch/config.toml`` (usually
``~/.config/memwatch/config.toml``).  TOML is parsed with the stdlib
``tomllib``; a tiny serializer is used to write the default file.
"""

from __future__ import annotations

import copy
import os
import tomllib
from pathlib import Path
from typing import Any

APP_NAME = "memwatch"

MB = 1024 * 1024

#: Default protected process names (case-insensitive).  Auto-kill will never
#: target these, regardless of how much memory they use.
DEFAULT_PROTECTED = [
    "systemd",
    "systemd-journald",
    "systemd-logind",
    "systemd-oomd",
    "gnome-shell",
    "gnome-session-binary",
    "Xorg",
    "Xwayland",
    "pipewire",
    "pipewire-pulse",
    "wireplumber",
    "dbus-daemon",
    "dbus-broker",
    "sshd",
    "polkitd",
    "memwatch",
]

DEFAULTS: dict[str, dict[str, Any]] = {
    "general": {
        "poll_interval": 10,
        "elevated_poll_interval": 2,
        "cooldown": 300,
        "log_level": "info",
    },
    "thresholds": {
        "warn_percent": 80.0,
        "warn_available_mb": 2048,
        "critical_percent": 90.0,
        "critical_available_mb": 1024,
        "emergency_percent": 95.0,
        "emergency_available_mb": 512,
        "hysteresis_percent": 5.0,
        "swap_critical_percent": 80.0,
    },
    "notifications": {
        "desktop": True,
        "sound": False,
        "sound_file": "/usr/share/sounds/freedesktop/stereo/dialog-warning.oga",
        "sound_min_severity": "critical",
        "top_processes": 5,
        "startup_notify": False,
    },
    "psi": {
        "enabled": True,
        "warn_some_avg10": 10.0,
        "critical_some_avg10": 25.0,
    },
    "auto_kill": {
        "enabled": False,
        "min_severity": "emergency",
        "max_kills_per_event": 1,
        "kill_signal": "SIGTERM",
        "sigkill_timeout": 5,
        "grace_seconds": 10,
        "cooldown": 60,
        "allow_root": False,
        "protected": list(DEFAULT_PROTECTED),
    },
}


class ConfigError(Exception):
    """Raised when the configuration is invalid."""


def xdg_config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")


def xdg_state_home() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")


def config_path() -> Path:
    return xdg_config_home() / APP_NAME / "config.toml"


def state_dir() -> Path:
    return xdg_state_home() / APP_NAME


def log_path() -> Path:
    return state_dir() / "memwatch.log"


def _deep_merge(base: dict, override: dict) -> dict:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    raise TypeError(f"cannot serialize {type(value).__name__} to TOML")


def dumps(data: dict[str, dict[str, Any]]) -> str:
    lines = ["# memwatch configuration", "# Generated defaults - edit to taste.", ""]
    for section, values in data.items():
        lines.append(f"[{section}]")
        for key, value in values.items():
            lines.append(f"{key} = {_toml_value(value)}")
        lines.append("")
    return "\n".join(lines)


def write_default_config(path: Path | None = None) -> Path:
    target = path or config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_text(dumps(DEFAULTS), encoding="utf-8")
    return target


def load_config(path: Path | None = None) -> dict[str, dict[str, Any]]:
    """Load config, merging over defaults, and validate it."""
    target = path or config_path()
    user: dict[str, Any] = {}
    if target.exists():
        try:
            user = tomllib.loads(target.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise ConfigError(f"cannot read config {target}: {exc}") from exc
    cfg = _deep_merge(DEFAULTS, user)
    validate(cfg)
    return cfg


def validate(cfg: dict[str, dict[str, Any]]) -> None:
    thresholds = cfg["thresholds"]
    for key in (
        "warn_percent",
        "critical_percent",
        "emergency_percent",
        "hysteresis_percent",
        "swap_critical_percent",
    ):
        if not 0 <= float(thresholds[key]) <= 100:
            raise ConfigError(f"thresholds.{key} must be between 0 and 100")

    if not (
        thresholds["warn_percent"]
        <= thresholds["critical_percent"]
        <= thresholds["emergency_percent"]
    ):
        raise ConfigError(
            "thresholds must satisfy warn_percent <= critical_percent <= emergency_percent"
        )

    if int(cfg["general"]["poll_interval"]) < 1:
        raise ConfigError("general.poll_interval must be >= 1")

    valid_sev = {"normal", "warn", "critical", "emergency"}
    sound_sev = str(cfg["notifications"].get("sound_min_severity", "critical")).lower()
    if sound_sev not in valid_sev:
        raise ConfigError(
            "notifications.sound_min_severity must be one of "
            "normal, warn, critical, emergency"
        )

    ak = cfg["auto_kill"]
    if str(ak["min_severity"]).lower() not in valid_sev:
        raise ConfigError(
            "auto_kill.min_severity must be one of normal, warn, critical, emergency"
        )
    if ak["enabled"] and not ak["protected"]:
        raise ConfigError("auto_kill.protected must not be empty when auto_kill is enabled")
    if int(ak["max_kills_per_event"]) < 1:
        raise ConfigError("auto_kill.max_kills_per_event must be >= 1")
    sig = str(ak["kill_signal"]).upper()
    if not sig.startswith("SIG"):
        sig = "SIG" + sig
    if sig not in {"SIGTERM", "SIGKILL", "SIGINT"}:
        raise ConfigError("auto_kill.kill_signal must be SIGTERM, SIGKILL or SIGINT")
