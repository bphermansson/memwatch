import copy
import unittest
from unittest import mock

from memwatch.config import DEFAULTS
from memwatch.monitor import Severity
from memwatch.notifier import Notifier


def cfg(sound=True, sound_min_severity="critical"):
    c = copy.deepcopy(DEFAULTS)
    c["notifications"]["sound"] = sound
    c["notifications"]["sound_min_severity"] = sound_min_severity
    return c


class SoundSeverityTests(unittest.TestCase):
    def test_no_sound_below_threshold(self):
        notifier = Notifier(cfg(sound_min_severity="critical"), desktop=False)
        with mock.patch.object(notifier, "_play_sound") as play:
            notifier.notify("t", "b", Severity.WARN)
        play.assert_not_called()

    def test_sound_at_threshold(self):
        notifier = Notifier(cfg(sound_min_severity="critical"), desktop=False)
        with mock.patch.object(notifier, "_play_sound") as play:
            notifier.notify("t", "b", Severity.CRITICAL)
        play.assert_called_once()

    def test_sound_disabled_never_plays(self):
        notifier = Notifier(cfg(sound=False), desktop=False)
        with mock.patch.object(notifier, "_play_sound") as play:
            notifier.notify("t", "b", Severity.EMERGENCY)
        play.assert_not_called()


if __name__ == "__main__":
    unittest.main()
