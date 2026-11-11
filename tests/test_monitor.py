import unittest

from memwatch.config import DEFAULTS, dumps
from memwatch.monitor import MemorySample, Severity, classify

MB = 1024 * 1024
TH = DEFAULTS["thresholds"]
PSI_OFF = {"enabled": False, "warn_some_avg10": 10.0, "critical_some_avg10": 25.0}
PSI_ON = {"enabled": True, "warn_some_avg10": 10.0, "critical_some_avg10": 25.0}


def make_sample(percent, available_mb, swap_percent=0.0, psi=None, total_mb=32000):
    total = total_mb * MB
    return MemorySample(
        total=total,
        available=int(available_mb * MB),
        used=total - int(available_mb * MB),
        percent=percent,
        swap_total=8000 * MB,
        swap_used=int(8000 * MB * swap_percent / 100),
        swap_percent=swap_percent,
        psi_some_avg10=psi,
    )


class ClassifyTests(unittest.TestCase):
    def test_normal(self):
        self.assertEqual(classify(make_sample(30, 20000), TH, PSI_OFF), Severity.NORMAL)

    def test_warn_by_percent(self):
        self.assertEqual(classify(make_sample(85, 4000), TH, PSI_OFF), Severity.WARN)

    def test_critical_by_percent(self):
        self.assertEqual(classify(make_sample(92, 2500), TH, PSI_OFF), Severity.CRITICAL)

    def test_emergency_by_percent(self):
        self.assertEqual(classify(make_sample(96, 1200), TH, PSI_OFF), Severity.EMERGENCY)

    def test_warn_by_available(self):
        self.assertEqual(classify(make_sample(30, 1500), TH, PSI_OFF), Severity.WARN)

    def test_emergency_by_available(self):
        self.assertEqual(classify(make_sample(30, 400), TH, PSI_OFF), Severity.EMERGENCY)

    def test_critical_by_swap(self):
        self.assertEqual(
            classify(make_sample(30, 20000, swap_percent=90), TH, PSI_OFF),
            Severity.CRITICAL,
        )

    def test_psi_ignored_when_disabled(self):
        self.assertEqual(classify(make_sample(30, 20000, psi=40), TH, PSI_OFF), Severity.NORMAL)

    def test_psi_warn_when_enabled(self):
        self.assertEqual(classify(make_sample(30, 20000, psi=12), TH, PSI_ON), Severity.WARN)

    def test_psi_critical_when_enabled(self):
        self.assertEqual(classify(make_sample(30, 20000, psi=30), TH, PSI_ON), Severity.CRITICAL)


class HysteresisTests(unittest.TestCase):
    def test_stays_warn_within_band(self):
        # 78% is below the 80% warn threshold but above 80-5=75, so stay WARN.
        sev = classify(make_sample(78, 4000), TH, PSI_OFF, current=Severity.WARN)
        self.assertEqual(sev, Severity.WARN)

    def test_downgrades_below_band(self):
        sev = classify(make_sample(70, 8000), TH, PSI_OFF, current=Severity.WARN)
        self.assertEqual(sev, Severity.NORMAL)

    def test_escalates_immediately(self):
        sev = classify(make_sample(96, 1200), TH, PSI_OFF, current=Severity.WARN)
        self.assertEqual(sev, Severity.EMERGENCY)


if __name__ == "__main__":
    unittest.main()
