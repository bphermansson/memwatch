import tempfile
import unittest
from pathlib import Path

from memwatch import config


class ConfigTests(unittest.TestCase):
    def test_defaults_when_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = config.load_config(Path(tmp) / "nope.toml")
        self.assertFalse(cfg["auto_kill"]["enabled"])
        self.assertEqual(cfg["thresholds"]["warn_percent"], 80.0)

    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            config.write_default_config(path)
            cfg = config.load_config(path)
        self.assertEqual(cfg["auto_kill"]["protected"], config.DEFAULT_PROTECTED)
        self.assertEqual(cfg["general"]["poll_interval"], 10)

    def test_partial_override_merges(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text("[general]\npoll_interval = 3\n", encoding="utf-8")
            cfg = config.load_config(path)
        self.assertEqual(cfg["general"]["poll_interval"], 3)
        # untouched default survives the merge
        self.assertEqual(cfg["general"]["cooldown"], 300)

    def test_invalid_threshold_order(self):
        cfg = config.load_config(Path("/nonexistent"))
        cfg["thresholds"]["warn_percent"] = 99.0
        cfg["thresholds"]["critical_percent"] = 50.0
        with self.assertRaises(config.ConfigError):
            config.validate(cfg)

    def test_autokill_requires_protected(self):
        cfg = config.load_config(Path("/nonexistent"))
        cfg["auto_kill"]["enabled"] = True
        cfg["auto_kill"]["protected"] = []
        with self.assertRaises(config.ConfigError):
            config.validate(cfg)

    def test_dumps_serializes_types(self):
        text = config.dumps({
            "s": {"b": True, "i": 3, "f": 1.5, "t": "x", "l": ["a", "b"]}
        })
        self.assertIn("b = true", text)
        self.assertIn("i = 3", text)
        self.assertIn('t = "x"', text)
        self.assertIn('l = ["a", "b"]', text)


if __name__ == "__main__":
    unittest.main()
