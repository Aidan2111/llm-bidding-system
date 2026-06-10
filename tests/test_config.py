import json
import tempfile
import unittest
from pathlib import Path

from llm_bidding.config import ConfigError, load_config


class ConfigTests(unittest.TestCase):
    def test_defaults_load_without_file(self):
        config = load_config()
        self.assertEqual(len(config.agents), 3)
        self.assertAlmostEqual(
            config.weights.quality + config.weights.price + config.weights.risk_fit, 1.0
        )
        self.assertEqual(config.calibration.neutral_prior, 0.5)
        self.assertEqual(config.history_db, "~/.llm-bidding/history.db")

    def test_repo_default_config_file_is_valid(self):
        path = Path(__file__).resolve().parent.parent / "llm-bidding.config.json"
        config = load_config(path)
        self.assertEqual({p.provider for p in config.agents}, {"anthropic", "openai"})

    def _write_config(self, data: dict) -> str:
        handle = tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8"
        )
        json.dump(data, handle)
        handle.close()
        self.addCleanup(Path(handle.name).unlink)
        return handle.name

    def test_rejects_weights_not_summing_to_one(self):
        path = self._write_config(
            {"utility": {"weights": {"quality": 0.9, "price": 0.9, "risk_fit": 0.9}}}
        )
        with self.assertRaises(ConfigError):
            load_config(path)

    def test_rejects_duplicate_agent_names(self):
        agent = {
            "name": "dup",
            "provider": "mock",
            "model_id": "m",
            "input_cost_per_mtok": 1,
            "output_cost_per_mtok": 1,
        }
        path = self._write_config({"agents": [agent, dict(agent)]})
        with self.assertRaises(ConfigError):
            load_config(path)

    def test_rejects_invalid_quality_mix(self):
        path = self._write_config(
            {"utility": {"quality_mix": {"confidence": 0.9, "history": 0.9}}}
        )
        with self.assertRaises(ConfigError):
            load_config(path)

    def test_agent_lookup(self):
        config = load_config()
        self.assertEqual(config.agent("claude-opus").model_id, "claude-opus-4-8")
        with self.assertRaises(ConfigError):
            config.agent("nope")


if __name__ == "__main__":
    unittest.main()
