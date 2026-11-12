"""Tests for secret-safe provider configuration validation."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.config import ConfigurationError, Settings


SNAPSHOT_ENV = {
    "OLLAMA_MODEL": "model",
    "VISION_MODEL": "vision",
    "VISION_BASE_URL": "https://opencode.ai/inference/openai/v1",
    "VISION_API_KEY": "vision-key",
}


class SettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        # Hermetic tests: never read the developer's working-directory `.env`.
        dotenv = patch("agent.config._load_dotenv")
        dotenv.start()
        self.addCleanup(dotenv.stop)

    def test_defaults_can_be_loaded_without_secrets(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings.from_environment(require_secrets=False)

        self.assertEqual(settings.ollama_base_url, "http://localhost:11434")
        self.assertEqual(settings.vision_provider, "hosted")
        self.assertEqual(settings.db_url, "sqlite:///./data/tutor.db")

    def test_dotenv_disabled_ignores_cwd_file(self) -> None:
        # A bogus provider in `.env` would fail validation if the loader ran;
        # use a temp cwd so the repository's own `.env` is never touched.
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                Path(".env").write_text(
                    "VISION_PROVIDER=bogus\n", encoding="utf-8"
                )
                with patch.dict(os.environ, {}, clear=True):
                    settings = Settings.from_environment(require_secrets=False)
            finally:
                os.chdir(original)

        self.assertEqual(settings.vision_provider, "hosted")

    def test_missing_secrets_are_reported_without_values(self) -> None:
        fake_secret = "do-not-print-this-value"
        with patch.dict(os.environ, {"VISION_API_KEY": fake_secret}, clear=True):
            with self.assertRaises(ConfigurationError) as error:
                Settings.from_environment()

        message = str(error.exception)
        for name in ("OLLAMA_MODEL", "VISION_MODEL", "VISION_BASE_URL"):
            self.assertIn(name, message)
        self.assertNotIn(fake_secret, message)

    def test_hosted_vision_requires_model_and_key(self) -> None:
        values = {
            "OLLAMA_MODEL": "model",
        }
        with patch.dict(os.environ, values, clear=True):
            with self.assertRaises(ConfigurationError) as error:
                Settings.from_environment()

        self.assertIn("VISION_MODEL", str(error.exception))
        self.assertIn("VISION_API_KEY", str(error.exception))

    def test_hosted_vision_requires_base_url(self) -> None:
        values = {
            "OLLAMA_MODEL": "model",
            "VISION_MODEL": "vision",
            "VISION_API_KEY": "vision-key",
        }
        with patch.dict(os.environ, values, clear=True):
            with self.assertRaises(ConfigurationError) as error:
                Settings.from_environment()

        self.assertIn("VISION_BASE_URL", str(error.exception))

    def test_hosted_vision_accepts_opencode_base_url(self) -> None:
        with patch.dict(os.environ, SNAPSHOT_ENV, clear=True):
            settings = Settings.from_environment()

        self.assertEqual(
            settings.vision_base_url, "https://opencode.ai/inference/openai/v1"
        )

    def test_invalid_vision_base_url_names_variable_not_value(self) -> None:
        bad_value = "not-a-url"
        values = {
            **SNAPSHOT_ENV,
            "VISION_BASE_URL": bad_value,
        }
        with patch.dict(os.environ, values, clear=True):
            with self.assertRaises(ConfigurationError) as error:
                Settings.from_environment()

        self.assertIn("VISION_BASE_URL", str(error.exception))
        self.assertNotIn(bad_value, str(error.exception))

    def test_local_vision_does_not_require_api_key(self) -> None:
        values = {
            "OLLAMA_MODEL": "model",
            "VISION_PROVIDER": "local",
            "VISION_MODEL": "local-model",
        }
        with patch.dict(os.environ, values, clear=True):
            settings = Settings.from_environment()

        self.assertEqual(settings.vision_provider, "local")
        self.assertEqual(settings.vision_api_key, "")

    def test_snapshot_config_validates_with_provider_values(self) -> None:
        with patch.dict(os.environ, SNAPSHOT_ENV, clear=True):
            settings = Settings.from_environment()

        self.assertEqual(settings.ollama_model, "model")
        self.assertEqual(settings.vision_model, "vision")
        self.assertEqual(settings.vision_api_key, "vision-key")

    def test_vision_api_defaults_to_openai(self) -> None:
        with patch.dict(os.environ, SNAPSHOT_ENV, clear=True):
            settings = Settings.from_environment()

        self.assertEqual(settings.vision_api, "openai")

    def test_gemini_vision_api_is_accepted(self) -> None:
        values = {
            **SNAPSHOT_ENV,
            "VISION_BASE_URL": "https://opencode.ai/inference/go/google/v1beta",
            "VISION_MODEL": "gemini-4-argon",
            "VISION_API": "gemini",
        }
        with patch.dict(os.environ, values, clear=True):
            settings = Settings.from_environment()

        self.assertEqual(settings.vision_api, "gemini")
        self.assertEqual(settings.vision_model, "gemini-4-argon")

    def test_invalid_vision_api_names_variable_not_value(self) -> None:
        bad_value = "mistral"
        with patch.dict(
            os.environ, {**SNAPSHOT_ENV, "VISION_API": bad_value}, clear=True
        ):
            with self.assertRaises(ConfigurationError) as error:
                Settings.from_environment()

        self.assertIn("VISION_API", str(error.exception))
        self.assertNotIn(bad_value, str(error.exception))

    def test_local_vision_ignores_vision_api(self) -> None:
        values = {
            "OLLAMA_MODEL": "model",
            "VISION_PROVIDER": "local",
            "VISION_MODEL": "local-model",
            "VISION_API": "not-a-family",
        }
        with patch.dict(os.environ, values, clear=True):
            settings = Settings.from_environment()

        self.assertEqual(settings.vision_provider, "local")
        self.assertEqual(settings.vision_api, "not-a-family")

    def test_public_dict_includes_vision_api_but_not_the_key(self) -> None:
        settings = Settings(
            ollama_model="model",
            vision_api="gemini",
            vision_api_key="vision-key-value",
        )
        public = settings.public_dict()

        self.assertEqual(public["vision_api"], "gemini")
        self.assertNotIn("vision_api_key", public)
        self.assertNotIn("vision-key-value", repr(public))

    def test_settings_fixture_needs_no_provider_values(self) -> None:
        settings = Settings(ollama_model="model")

        self.assertEqual(settings.ollama_model, "model")
        self.assertEqual(settings.vision_api_key, "")

    def test_db_url_comes_from_the_environment(self) -> None:
        values = {**SNAPSHOT_ENV, "DB_URL": "sqlite:///:memory:"}
        with patch.dict(os.environ, values, clear=True):
            settings = Settings.from_environment()

        self.assertEqual(settings.db_url, "sqlite:///:memory:")

    def test_missing_vision_names_only_the_required_variables(self) -> None:
        with patch.dict(os.environ, {"OLLAMA_MODEL": "model"}, clear=True):
            with self.assertRaises(ConfigurationError) as error:
                Settings.from_environment()

        message = str(error.exception)
        self.assertIn("VISION_MODEL", message)
        self.assertIn("VISION_BASE_URL", message)
        self.assertIn("VISION_API_KEY", message)
        self.assertNotIn("OLLAMA_MODEL", message)

    def test_livekit_environment_variables_are_ignored(self) -> None:
        # The snapshot API has no runtime mode and no room transport, so the
        # old variables must not select a mode, raise, or reach public output.
        values = {
            **SNAPSHOT_ENV,
            "TUTOR_RUNTIME": "livekit",
            "LIVEKIT_URL": "http://localhost:7880",
            "LIVEKIT_API_KEY": "livekit-key-value",
            "LIVEKIT_API_SECRET": "livekit-secret-value",
        }
        with patch.dict(os.environ, values, clear=True):
            settings = Settings.from_environment()

        self.assertFalse(hasattr(settings, "livekit_url"))
        self.assertEqual(settings.ollama_model, "model")
        public = settings.public_dict()
        self.assertFalse([name for name in public if "livekit" in name])
        self.assertNotIn("tutor_runtime", public)
        rendered = repr(public) + repr(settings)
        self.assertNotIn("livekit-key-value", rendered)
        self.assertNotIn("livekit-secret-value", rendered)

    def test_public_dict_omits_the_vision_key(self) -> None:
        settings = Settings(
            ollama_model="model",
            vision_api_key="vision-key-value",
        )
        public = settings.public_dict()

        self.assertNotIn("vision_api_key", public)
        self.assertEqual(public["ollama_model"], "model")
        self.assertNotIn("vision-key-value", repr(public))

    def test_repr_redacts_the_vision_key(self) -> None:
        settings = Settings(vision_api_key="vision-key-value")

        self.assertNotIn("vision-key-value", repr(settings))


INTENT_ENV = {
    "INTENT_PROVIDER": "opencode",
    "INTENT_MODEL": "claude-haiku-5-5",
    "INTENT_BASE_URL": "https://opencode.ai/inference/go/openai/v1",
}


class IntentSettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        dotenv = patch("agent.config._load_dotenv")
        dotenv.start()
        self.addCleanup(dotenv.stop)

    def test_intent_defaults_to_local_ollama(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings.from_environment(require_secrets=False)

        self.assertEqual(settings.intent_provider, "ollama")
        self.assertEqual(settings.intent_model, "")
        self.assertEqual(settings.intent_base_url, "")
        self.assertEqual(settings.intent_api_key, "")

    def test_opencode_intent_reuses_the_vision_key(self) -> None:
        with patch.dict(
            os.environ, {**SNAPSHOT_ENV, **INTENT_ENV}, clear=True
        ):
            settings = Settings.from_environment()

        self.assertEqual(settings.intent_provider, "opencode")
        self.assertEqual(settings.intent_model, "claude-haiku-5-5")
        self.assertEqual(
            settings.intent_base_url,
            "https://opencode.ai/inference/go/openai/v1",
        )
        self.assertEqual(settings.intent_api_key, "vision-key")

    def test_intent_key_overrides_the_vision_key(self) -> None:
        with patch.dict(
            os.environ,
            {**SNAPSHOT_ENV, **INTENT_ENV, "INTENT_API_KEY": "intent-key"},
            clear=True,
        ):
            settings = Settings.from_environment()

        self.assertEqual(settings.intent_api_key, "intent-key")

    def test_invalid_intent_provider_names_variable_not_value(self) -> None:
        bad_value = "bogus-provider"
        with patch.dict(
            os.environ,
            {**SNAPSHOT_ENV, "INTENT_PROVIDER": bad_value},
            clear=True,
        ):
            with self.assertRaises(ConfigurationError) as error:
                Settings.from_environment()

        self.assertIn("INTENT_PROVIDER", str(error.exception))
        self.assertNotIn(bad_value, str(error.exception))

    def test_opencode_intent_requires_model_and_base_url(self) -> None:
        with patch.dict(
            os.environ,
            {
                **SNAPSHOT_ENV,
                "INTENT_PROVIDER": "opencode",
            },
            clear=True,
        ):
            with self.assertRaises(ConfigurationError) as error:
                Settings.from_environment()

        message = str(error.exception)
        self.assertIn("INTENT_MODEL", message)
        self.assertIn("INTENT_BASE_URL", message)

    def test_invalid_intent_base_url_names_variable_not_value(self) -> None:
        bad_value = "not-a-url"
        with patch.dict(
            os.environ,
            {**SNAPSHOT_ENV, **INTENT_ENV, "INTENT_BASE_URL": bad_value},
            clear=True,
        ):
            with self.assertRaises(ConfigurationError) as error:
                Settings.from_environment()

        self.assertIn("INTENT_BASE_URL", str(error.exception))
        self.assertNotIn(bad_value, str(error.exception))

    def test_opencode_intent_without_any_key_names_intent_variable(self) -> None:
        values = {
            "OLLAMA_MODEL": "model",
            "VISION_PROVIDER": "local",
            "VISION_MODEL": "local-model",
            **INTENT_ENV,
        }
        with patch.dict(os.environ, values, clear=True):
            with self.assertRaises(ConfigurationError) as error:
                Settings.from_environment()

        self.assertIn("INTENT_API_KEY", str(error.exception))

    def test_local_intent_ignores_hosted_intent_values(self) -> None:
        values = {
            **SNAPSHOT_ENV,
            "INTENT_PROVIDER": "ollama",
            "INTENT_BASE_URL": "not-a-url",
            "INTENT_MODEL": "",
        }
        with patch.dict(os.environ, values, clear=True):
            settings = Settings.from_environment()

        self.assertEqual(settings.intent_provider, "ollama")
        self.assertEqual(settings.intent_base_url, "not-a-url")

    def test_public_dict_and_repr_omit_the_intent_key(self) -> None:
        settings = Settings(
            ollama_model="model",
            intent_provider="opencode",
            intent_model="claude-haiku-5-5",
            intent_base_url="https://opencode.ai/inference/go/openai/v1",
            intent_api_key="intent-key-value",
        )

        public = settings.public_dict()
        self.assertEqual(public["intent_provider"], "opencode")
        self.assertEqual(public["intent_model"], "claude-haiku-5-5")
        self.assertNotIn("intent_api_key", public)
        rendered = repr(public) + repr(settings)
        self.assertNotIn("intent-key-value", rendered)


if __name__ == "__main__":
    unittest.main()
