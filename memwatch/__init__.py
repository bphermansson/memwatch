"""memwatch - a memory watchdog for Fedora Linux.

Warns (desktop notification + log) before the system runs out of memory,
naming the top memory-consuming processes. Optionally auto-kills the
largest offending process (opt-in, off by default).
"""

__version__ = "0.1.0"
__all__ = ["__version__"]
