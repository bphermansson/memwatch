"""Memory sampling and severity classification."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

import psutil

from . import psi as psi_mod

MB = 1024 * 1024


class Severity(IntEnum):
    NORMAL = 0
    WARN = 1
    CRITICAL = 2
    EMERGENCY = 3

    @property
    def label(self) -> str:
        return self.name.lower()


SEVERITY_BY_NAME = {s.name.lower(): s for s in Severity}


@dataclass
class MemorySample:
    total: int
    available: int
    used: int
    percent: float
    swap_total: int
    swap_used: int
    swap_percent: float
    psi_some_avg10: float | None = None

    @property
    def used_percent(self) -> float:
        return self.percent

    @property
    def available_percent(self) -> float:
        if self.total <= 0:
            return 100.0
        return 100.0 * self.available / self.total


def take_sample(psi_enabled: bool = True) -> MemorySample:
    vm = psutil.virtual_memory()
    sw = psutil.swap_memory()
    psi = psi_mod.read_some_avg10() if psi_enabled else None
    return MemorySample(
        total=int(vm.total),
        available=int(vm.available),
        used=int(vm.used),
        percent=float(vm.percent),
        swap_total=int(sw.total),
        swap_used=int(sw.used),
        swap_percent=float(sw.percent),
        psi_some_avg10=psi,
    )


def _lower_thresholds(thresholds: dict) -> dict:
    """Return thresholds adjusted by the hysteresis band (harder to stay warned)."""
    hyst = float(thresholds.get("hysteresis_percent", 0.0))
    lowered = dict(thresholds)
    for key in ("warn_percent", "critical_percent", "emergency_percent"):
        lowered[key] = float(thresholds[key]) - hyst
    return lowered


def _raw_severity(
    sample: MemorySample, thresholds: dict, psi_cfg: dict
) -> Severity:
    sev = Severity.NORMAL

    emergency_mb = float(thresholds["emergency_available_mb"]) * MB
    critical_mb = float(thresholds["critical_available_mb"]) * MB
    warn_mb = float(thresholds["warn_available_mb"]) * MB

    if sample.percent >= thresholds["emergency_percent"] or sample.available < emergency_mb:
        sev = Severity.EMERGENCY
    elif sample.percent >= thresholds["critical_percent"] or sample.available < critical_mb:
        sev = Severity.CRITICAL
    elif sample.percent >= thresholds["warn_percent"] or sample.available < warn_mb:
        sev = Severity.WARN

    if sample.swap_total > 0 and sample.swap_percent >= thresholds.get(
        "swap_critical_percent", 100.0
    ):
        sev = max(sev, Severity.CRITICAL)

    if psi_cfg.get("enabled") and sample.psi_some_avg10 is not None:
        if sample.psi_some_avg10 >= float(psi_cfg["critical_some_avg10"]):
            sev = max(sev, Severity.CRITICAL)
        elif sample.psi_some_avg10 >= float(psi_cfg["warn_some_avg10"]):
            sev = max(sev, Severity.WARN)

    return sev


def classify(
    sample: MemorySample,
    thresholds: dict,
    psi_cfg: dict,
    current: Severity = Severity.NORMAL,
) -> Severity:
    """Classify a sample, applying hysteresis relative to ``current``.

    Escalation is immediate; downgrading only happens once usage has fallen
    clearly below the threshold band, which prevents notification flapping.
    """
    raw = _raw_severity(sample, thresholds, psi_cfg)
    if raw >= current:
        return raw
    sticky = _raw_severity(sample, _lower_thresholds(thresholds), psi_cfg)
    return max(raw, min(sticky, current))


def format_sample(sample: MemorySample) -> str:
    lines = [
        f"RAM: {sample.percent:.0f}% used  "
        f"({_fmt(sample.used)} / {_fmt(sample.total)}), "
        f"{_fmt(sample.available)} available",
    ]
    if sample.swap_total > 0:
        lines.append(
            f"Swap: {sample.swap_percent:.0f}% used "
            f"({_fmt(sample.swap_used)} / {_fmt(sample.swap_total)})"
        )
    if sample.psi_some_avg10 is not None:
        lines.append(f"Memory pressure (some avg10): {sample.psi_some_avg10:.1f}")
    return "\n".join(lines)


def _fmt(value: float) -> str:
    from .processes import human_bytes

    return human_bytes(value)


def simulated_sample(severity: Severity, total: int | None = None) -> MemorySample:
    """Build a fake sample at roughly the given severity, for testing alerts."""
    total = total or int(psutil.virtual_memory().total)
    fraction = {
        Severity.NORMAL: 0.30,
        Severity.WARN: 0.82,
        Severity.CRITICAL: 0.92,
        Severity.EMERGENCY: 0.97,
    }[severity]
    used = int(total * fraction)
    return MemorySample(
        total=total,
        available=total - used,
        used=used,
        percent=fraction * 100,
        swap_total=8 * 1024 * MB,
        swap_used=int(8 * 1024 * MB * fraction),
        swap_percent=fraction * 100,
        psi_some_avg10={Severity.NORMAL: 0.0, Severity.WARN: 12.0,
                        Severity.CRITICAL: 30.0, Severity.EMERGENCY: 45.0}[severity],
    )
