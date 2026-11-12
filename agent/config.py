"""Load and validate backend provider configuration without exposing secrets."""

from dataclasses import asdict, dataclass, field
import os
from pathlib import Path
from urllib.parse import urlparse


DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
# Never expose these through repr() or public_dict(); they are credentials.
PRIVATE_SETTING_FIELDS = ("vision_api_key",)


class ConfigurationError(ValueError):
    """Raised when required provider configuration is missing."""


@dataclass(frozen=True)
class Settings:
    ollama_base_url: str = DEFAULT_OLLAMA_BASE_URL
    ollama_model: str = ""
    whisper_model: str = "small.en"
    vision_provider: str = "hosted"
    vision_api: str = "openai"
    vision_base_url: str = ""
    vision_model: str = ""
    vision_api_key: str = field(default="", repr=False)
    log_level: str = "INFO"
    db_url: str = "sqlite:///./data/tutor.db"

    def public_dict(self) -> dict[str, str]:
        """Return loggable settings without credentials."""
        values = asdict(self)
        for name in PRIVATE_SETTING_FIELDS:
            values.pop(name, None)
        return values

    @classmethod
    def from_environment(cls, *, require_secrets: bool = True) -> "Settings":
        _load_dotenv()
        values = {
            "ollama_base_url": os.getenv("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL),
            "ollama_model": os.getenv("OLLAMA_MODEL", ""),
            "whisper_model": os.getenv("WHISPER_MODEL", "small.en"),
            "vision_provider": os.getenv("VISION_PROVIDER", "hosted").lower(),
            "vision_api": os.getenv("VISION_API", "openai").lower(),
            "vision_base_url": os.getenv("VISION_BASE_URL", ""),
            "vision_model": os.getenv("VISION_MODEL", ""),
            "vision_api_key": os.getenv("VISION_API_KEY", ""),
            "log_level": os.getenv("LOG_LEVEL", "INFO"),
            "db_url": os.getenv("DB_URL", "sqlite:///./data/tutor.db"),
        }

        provider = values["vision_provider"]
        if provider not in {"hosted", "local"}:
            raise ConfigurationError(
                "VISION_PROVIDER must be either hosted or local"
            )

        # Local vision ignores VISION_API; only the hosted path selects a family.
        allowed_apis = {"openai", "gemini"}
        if provider == "hosted" and values["vision_api"] not in allowed_apis:
            raise ConfigurationError(
                "VISION_API must be either openai or gemini"
            )

        if values["vision_base_url"] and urlparse(
            values["vision_base_url"]
        ).scheme not in {"http", "https"}:
            raise ConfigurationError(
                "VISION_BASE_URL must be an absolute http or https URL"
            )

        if require_secrets:
            required = [
                name
                for name in ("OLLAMA_MODEL", "VISION_MODEL")
                if not os.getenv(name)
            ]
            if provider == "hosted" and not values["vision_base_url"]:
                required.append("VISION_BASE_URL")
            if provider == "hosted" and not values["vision_api_key"]:
                required.append("VISION_API_KEY")
            if required:
                raise ConfigurationError(
                    "Missing required provider configuration: "
                    + ", ".join(required)
                )

        return cls(**values)


def _load_dotenv() -> None:
    """Load simple KEY=VALUE pairs without overwriting process environment."""
    path = Path(".env")
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))