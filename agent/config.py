"""Load and validate backend provider configuration without exposing secrets."""

from dataclasses import dataclass, field
import os


DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"


class ConfigurationError(ValueError):
    """Raised when required provider configuration is missing."""


@dataclass(frozen=True)
class Settings:
    livekit_url: str
    livekit_api_key: str = field(repr=False)
    livekit_api_secret: str = field(repr=False)
    ollama_base_url: str = DEFAULT_OLLAMA_BASE_URL
    ollama_model: str = ""
    whisper_model: str = "small.en"
    log_level: str = "INFO"
    db_url: str = "sqlite:///./data/tutor.db"

    @classmethod
    def from_environment(cls, *, require_secrets: bool = True) -> "Settings":
        values = {
            "livekit_url": os.getenv("LIVEKIT_URL", ""),
            "livekit_api_key": os.getenv("LIVEKIT_API_KEY", ""),
            "livekit_api_secret": os.getenv("LIVEKIT_API_SECRET", ""),
            "ollama_base_url": os.getenv("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL),
            "ollama_model": os.getenv("OLLAMA_MODEL", ""),
            "whisper_model": os.getenv("WHISPER_MODEL", "small.en"),
            "log_level": os.getenv("LOG_LEVEL", "INFO"),
            "db_url": os.getenv("DB_URL", "sqlite:///./data/tutor.db"),
        }

        if require_secrets:
            missing = [
                name
                for name in (
                    "LIVEKIT_URL",
                    "LIVEKIT_API_KEY",
                    "LIVEKIT_API_SECRET",
                    "OLLAMA_MODEL",
                )
                if not os.getenv(name)
            ]
            if missing:
                raise ConfigurationError(
                    "Missing required provider configuration: " + ", ".join(missing)
                )

        return cls(**values)