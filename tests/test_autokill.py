import unittest
from unittest import mock

from memwatch.autokill import AutoKiller
from memwatch.config import DEFAULTS
from memwatch.monitor import Severity, simulated_sample
from memwatch.processes import ProcessInfo


class FakeNotifier:
    def __init__(self):
        self.calls = []

    def notify(self, title, body, severity=Severity.WARN, urgency=None):
        self.calls.append((title, severity))
        return True


def cfg(**overrides):
    import copy

    c = copy.deepcopy(DEFAULTS)
    c["auto_kill"].update(overrides)
    return c


PROCS = [
    ProcessInfo(pid=101, name="firefox", rss=4 * 1024**3),
    ProcessInfo(pid=102, name="chrome", rss=3 * 1024**3),
    ProcessInfo(pid=103, name="gnome-shell", rss=2 * 1024**3),  # protected
    ProcessInfo(pid=104, name="slack", rss=1 * 1024**3),
]


class AutoKillTests(unittest.TestCase):
    def setUp(self):
        self.notifier = FakeNotifier()
        self.patcher = mock.patch(
            "memwatch.autokill.top_processes", return_value=list(PROCS)
        )
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_disabled_by_default(self):
        killer = AutoKiller(cfg(), self.notifier, self_pids={999})
        self.assertFalse(killer.cfg_enabled)
        self.assertFalse(
            killer.maybe_kill(simulated_sample(Severity.EMERGENCY), Severity.EMERGENCY,
                              resample_severity=lambda: Severity.EMERGENCY)
        )

    def test_protected_filtered_out(self):
        killer = AutoKiller(cfg(enabled=True), self.notifier, self_pids={999})
        names = [p.name for p in killer.select_candidates(count=5)]
        self.assertNotIn("gnome-shell", names)
        self.assertEqual(names[0], "firefox")

    def test_below_min_severity_does_nothing(self):
        killer = AutoKiller(cfg(enabled=True, min_severity="emergency"),
                            self.notifier, self_pids={999})
        acted = killer.maybe_kill(
            simulated_sample(Severity.CRITICAL), Severity.CRITICAL,
            resample_severity=lambda: Severity.CRITICAL,
        )
        self.assertFalse(acted)

    def test_requires_two_candidates(self):
        with mock.patch(
            "memwatch.autokill.top_processes",
            return_value=[ProcessInfo(pid=101, name="firefox", rss=10**9)],
        ):
            killer = AutoKiller(cfg(enabled=True, grace_seconds=0),
                                self.notifier, self_pids={999})
            acted = killer.maybe_kill(
                simulated_sample(Severity.EMERGENCY), Severity.EMERGENCY,
                resample_severity=lambda: Severity.EMERGENCY,
            )
        self.assertFalse(acted)

    def test_dry_run_does_not_signal(self):
        killer = AutoKiller(cfg(enabled=True, grace_seconds=0), self.notifier,
                            self_pids={999}, dry_run=True)
        with mock.patch("memwatch.autokill.psutil.Process") as proc:
            acted = killer.maybe_kill(
                simulated_sample(Severity.EMERGENCY), Severity.EMERGENCY,
                resample_severity=lambda: Severity.EMERGENCY,
            )
        self.assertFalse(acted)
        proc.assert_not_called()

    def test_kills_target_when_armed(self):
        killer = AutoKiller(cfg(enabled=True, grace_seconds=0), self.notifier,
                            self_pids={999})
        fake_proc = mock.Mock()
        with mock.patch("memwatch.autokill.psutil.Process", return_value=fake_proc):
            acted = killer.maybe_kill(
                simulated_sample(Severity.EMERGENCY), Severity.EMERGENCY,
                resample_severity=lambda: Severity.EMERGENCY,
            )
        self.assertTrue(acted)
        fake_proc.send_signal.assert_called_once()
        fake_proc.wait.assert_called_once()

    def test_aborts_if_memory_recovers_during_grace(self):
        killer = AutoKiller(cfg(enabled=True, grace_seconds=2), self.notifier,
                            self_pids={999})
        with mock.patch("memwatch.autokill.psutil.Process") as proc:
            acted = killer.maybe_kill(
                simulated_sample(Severity.EMERGENCY), Severity.EMERGENCY,
                resample_severity=lambda: Severity.NORMAL,
            )
        self.assertFalse(acted)
        proc.assert_not_called()


if __name__ == "__main__":
    unittest.main()
