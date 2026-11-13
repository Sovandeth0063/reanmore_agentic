"""Load and validate backend provider configuration without exposing secrets."""

from dataclasses import asdict, dataclass, field
import os
from pathlib import Path
from urllib.parse import urlparse


DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_INTENT_PROVIDER = "ollama"
INTENT_PROVIDERS = {"ollama", "opencode"}
# Safe defaults keep the deterministic choice flow and offline wording; the
# demo `.env` opts into guided flow and hosted rendering explicitly.
DEFAULT_TUTOR_FLOW = "choice"
DEFAULT_TUTOR_RENDERER = "template"
TUTOR_FLOWS = {"choice", "guided"}
TUTOR_RENDERERS = {"template", "llm"}
# The demo keeps speech-to-text on the CPU: faster-whisper's CUDA build fails
# on this laptop without cublas64_12.dll, and the GPU is reserved for VoxPocket.
DEFAULT_WHISPER_DEVICE = "cpu"
DEFAULT_WHISPER_COMPUTE_TYPE = "int8"
WHISPER_DEVICES = {"cpu", "cuda"}
WHISPER_COMPUTE_TYPES = {
    "auto",
    "default",
    "int8",
    "int8_float16",
    "int8_float32",
    "float16",
    "float32",
    "bfloat16",
}
# Never expose these through repr() or public_dict(); they are credentials.
PRIVATE_SETTING_FIELDS = ("vision_api_key", "intent_api_key")


class ConfigurationError(ValueError):
    """Raised when required provider configuration is missing."""


@dataclass(frozen=True)
class Settings:
    ollama_base_url: str = DEFAULT_OLLAMA_BASE_URL
    ollama_model: str = ""
    whisper_model: str = "small.en"
    whisper_device: str = DEFAULT_WHISPER_DEVICE
    whisper_compute_type: str = DEFAULT_WHISPER_COMPUTE_TYPE
    vision_provider: str = "hosted"
    vision_api: str = "openai"
    vision_base_url: str = ""
    vision_model: str = ""
    vision_api_key: str = field(default="", repr=False)
    # Intent classification: local Ollama by default for compatibility; the
    # hosted OpenAI-compatible route is selected explicitly in `.env`.
    intent_provider: str = DEFAULT_INTENT_PROVIDER
    intent_model: str = ""
    intent_base_url: str = ""
    intent_api_key: str = field(default="", repr=False)
    log_level: str = "INFO"
    db_url: str = "sqlite:///./data/tutor.db"
    tutor_flow: str = DEFAULT_TUTOR_FLOW
    tutor_renderer: str = DEFAULT_TUTOR_RENDERER

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
            "whisper_device": os.getenv(
                "WHISPER_DEVICE", DEFAULT_WHISPER_DEVICE
            ).lower(),
            "whisper_compute_type": os.getenv(
                "WHISPER_COMPUTE_TYPE", DEFAULT_WHISPER_COMPUTE_TYPE
            ).lower(),
            "vision_provider": os.getenv("VISION_PROVIDER", "hosted").lower(),
            "vision_api": os.getenv("VISION_API", "openai").lower(),
            "vision_base_url": os.getenv("VISION_BASE_URL", ""),
            "vision_model": os.getenv("VISION_MODEL", ""),
            "vision_api_key": os.getenv("VISION_API_KEY", ""),
            "intent_provider": os.getenv(
                "INTENT_PROVIDER", DEFAULT_INTENT_PROVIDER
            ).lower(),
            "intent_model": os.getenv("INTENT_MODEL", ""),
            "intent_base_url": os.getenv("INTENT_BASE_URL", ""),
            "intent_api_key": os.getenv("INTENT_API_KEY", ""),
            "log_level": os.getenv("LOG_LEVEL", "INFO"),
            "db_url": os.getenv("DB_URL", "sqlite:///./data/tutor.db"),
            "tutor_flow": os.getenv("TUTOR_FLOW", DEFAULT_TUTOR_FLOW).lower(),
            "tutor_renderer": os.getenv(
                "TUTOR_RENDERER", DEFAULT_TUTOR_RENDERER
            ).lower(),
        }

        # One Go key is enough: an empty INTENT_API_KEY reuses VISION_API_KEY.
        values["intent_api_key"] = (
            values["intent_api_key"] or values["vision_api_key"]
        )
        intent_provider = values["intent_provider"]
        if intent_provider not in INTENT_PROVIDERS:
            raise ConfigurationError(
                "INTENT_PROVIDER must be either ollama or opencode"
            )

        # A typo must fail at startup, not in the middle of a speech turn.
        if values["whisper_device"] not in WHISPER_DEVICES:
            raise ConfigurationError(
                "WHISPER_DEVICE must be either cpu or cuda"
            )
        if values["whisper_compute_type"] not in WHISPER_COMPUTE_TYPES:
            raise ConfigurationError(
                "WHISPER_COMPUTE_TYPE must be one of "
                + ", ".join(sorted(WHISPER_COMPUTE_TYPES))
            )

        # A typo in either tutor switch must fail at startup, never mid-turn.
        if values["tutor_flow"] not in TUTOR_FLOWS:
            raise ConfigurationError(
                "TUTOR_FLOW must be either choice or guided"
            )
        if values["tutor_renderer"] not in TUTOR_RENDERERS:
            raise ConfigurationError(
                "TUTOR_RENDERER must be either template or llm"
            )

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

        # The hosted intent route is validated only when it is selected; the
        # local default must keep working without any intent variables.
        if intent_provider == "opencode" and values["intent_base_url"] and (
            urlparse(values["intent_base_url"]).scheme not in {"http", "https"}
        ):
            raise ConfigurationError(
                "INTENT_BASE_URL must be an absolute http or https URL"
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
            if intent_provider == "opencode":
                if not values["intent_model"]:
                    required.append("INTENT_MODEL")
                if not values["intent_base_url"]:
                    required.append("INTENT_BASE_URL")
                if not values["intent_api_key"]:
                    required.append("INTENT_API_KEY")
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