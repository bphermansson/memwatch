"""Reader for Linux Pressure Stall Information (PSI).

``/proc/pressure/memory`` reports how much time tasks were stalled waiting on
memory.  The ``some avg10`` value is a great early-warning signal: it rises
before the system actually runs out of memory.
"""

from __future__ import annotations

PSI_MEMORY = "/proc/pressure/memory"


def read_some_avg10(path: str = PSI_MEMORY) -> float | None:
    """Return the ``some avg10`` memory pressure value, or ``None`` if unavailable."""
    try:
        with open(path, encoding="ascii") as handle:
            for line in handle:
                if line.startswith("some"):
                    fields = dict(
                        part.split("=", 1) for part in line.split()[1:] if "=" in part
                    )
                    return float(fields["avg10"])
    except (OSError, ValueError, KeyError):
        return None
    return None
