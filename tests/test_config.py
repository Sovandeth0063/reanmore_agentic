"""Tests for secret-safe provider configuration validation."""

import os
import unittest
from unittest.mock import patch

from agent.config import ConfigurationError, Settings


class SettingsTests(unittest.TestCase):
    def test_defaults_can_be_loaded_without_secrets(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings.from_environment(require_secrets=False)

        self.assertEqual(settings.ollama_base_url, "http://localhost:11434")
        self.assertEqual(settings.db_url, "sqlite:///./data/tutor.db")

    def test_missing_secrets_are_reported_without_values(self) -> None:
        fake_secret = "do-not-print-this-value"
        with patch.dict(os.environ, {"LIVEKIT_API_SECRET": fake_secret}, clear=True):
            with self.assertRaises(ConfigurationError) as error:
                Settings.from_environment()

        self.assertIn("LIVEKIT_URL", str(error.exception))
        self.assertNotIn(fake_secret, str(error.exception))


if __name__ == "__main__":
    unittest.main()