# memwatch

A memory watchdog for Fedora (and other Linux desktops). It watches RAM, swap
and kernel memory-pressure (PSI), and sends a **desktop notification before the
system runs out of memory**, naming the top memory-consuming processes so you
know what to close.

It can also **optionally auto-kill** the largest offending process. This is
**off by default** and heavily guarded.

## Features

- Desktop popups via `notify-send` with urgency levels (warn / critical / emergency).
- Linux PSI (`/proc/pressure/memory`) early warning — rises *before* OOM.
- Swap-pressure detection.
- Top-N processes by RSS included in each alert.
- Hysteresis + cooldown so it does not spam you.
- Adaptive polling: fast while memory is tight, slow when idle.
- Rotating log at `~/.local/state/memwatch/memwatch.log`.
- Runs as a **systemd user service** (no root).
- Opt-in auto-kill with a grace window, protected-process list and dry-run.

## Requirements

- Python >= 3.11 (3.14 on this machine)
- `psutil` (already installed)
- `notify-send` (from `libnotify`) for popups

## Quick start

```sh
cd "/home/patrik/Dokument/Default Project"

# one-shot check (exit code 0=normal 1=warn 2=critical 3=emergency)
python3 -m memwatch check

# fire a test popup
python3 -m memwatch check --simulate critical

# install + start the background service
python3 -m memwatch install

# check on it / stop it
python3 -m memwatch status
python3 -m memwatch uninstall
```

`install` writes a launcher to `~/.local/bin/memwatch`, a unit to
`~/.config/systemd/user/memwatch.service`, then runs
`systemctl --user enable --now memwatch.service`.

## Configuration

Created on first run at `~/.config/memwatch/config.toml`:

```toml
[general]
poll_interval = 10            # seconds between samples when idle
elevated_poll_interval = 2    # seconds while memory is tight
cooldown = 300                # seconds before repeating an alert
log_level = "info"

[thresholds]
warn_percent = 80.0
warn_available_mb = 2048
critical_percent = 90.0
critical_available_mb = 1024
emergency_percent = 95.0
emergency_available_mb = 512
hysteresis_percent = 5.0
swap_critical_percent = 80.0

[notifications]
desktop = true
sound = false
sound_file = "/usr/share/sounds/freedesktop/stereo/dialog-warning.oga"
sound_min_severity = "critical"   # only play sound at this level or above
top_processes = 5
startup_notify = false

[psi]
enabled = true
warn_some_avg10 = 10.0
critical_some_avg10 = 25.0

[auto_kill]
enabled = false               # master switch
min_severity = "emergency"    # only act at this level or above
max_kills_per_event = 1
kill_signal = "SIGTERM"       # SIGTERM then SIGKILL after sigkill_timeout
sigkill_timeout = 5
grace_seconds = 10            # cancel window; aborts if memory recovers
cooldown = 60
allow_root = false            # never kill system/root processes
protected = ["systemd", "gnome-shell", "Xorg", "Xwayland", "pipewire", "sshd", "memwatch"]
```

Severity is the highest of the percent / available / swap / PSI conditions.
Escalation is immediate; a level only clears once usage drops below
`threshold - hysteresis_percent` (prevents flapping).

## Auto-kill (opt-in)

Disabled unless `auto_kill.enabled = true`. When enabled it will only act:

1. at `min_severity` or above,
2. after a cooldown since the last kill,
3. if at least **two** safe candidates exist (so it never kills the only
   remaining process),
4. after a `grace_seconds` countdown during which memory may recover
   (the kill is cancelled if it does).

Safe candidates exclude the memwatch process and its ancestors, anything in
`protected`, PID 1, and — unless `allow_root = true` — any process owned by a
system user (uid < 1000).

Preview what it would do, without killing anything:

```sh
python3 -m memwatch check --simulate emergency --auto-kill-dry-run
```

Force auto-kill for a single foreground run regardless of config:

```sh
python3 -m memwatch run --auto-kill
```

## Troubleshooting

**No desktop popups when running as a service.** The systemd user manager needs
your session's display variables. Most Fedora/GNOME setups import them
automatically; if not, run:

```sh
systemctl --user import-environment DISPLAY WAYLAND_DISPLAY XDG_CURRENT_DESKTOP
```

**View logs.**

```sh
journalctl --user -u memwatch -f
tail -f ~/.local/state/memwatch/memwatch.log
```

## Development

```sh
python3 -m unittest discover -s tests -v
```

## CLI reference

| Command | Purpose |
| --- | --- |
| `memwatch run` | run the monitoring loop (`--once`, `--interval`, `--auto-kill`, `--no-desktop`) |
| `memwatch check` | one-shot check; exit code = severity (`--simulate`, `--json`, `--auto-kill-dry-run`) |
| `memwatch install` | install + enable the systemd user service (`--force`, `--no-start`) |
| `memwatch uninstall` | stop and remove the service |
| `memwatch status` | show service status |
| `memwatch config` | print config path/values (`--init` to write defaults) |

## Not included (yet)

- Per-process memory-growth / leak detection
- cgroup memory-limit awareness
- Email / webhook alerts
