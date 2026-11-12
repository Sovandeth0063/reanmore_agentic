"""Check local provider configuration and reachability without exposing secrets."""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

# Allow `python scripts/check_providers.py` from the repository root.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.config import ConfigurationError, Settings  # noqa: E402


def _check_url(url: str) -> bool:
    try:
        with urlopen(url, timeout=3):
            return True
    except (OSError, URLError):
        return False


def _check_ollama(settings: Settings) -> bool:
    return _check_url(settings.ollama_base_url.rstrip("/") + "/api/tags")


def _check_import(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def _check_vision(settings: Settings) -> bool:
    if not settings.vision_model:
        return False
    if settings.vision_provider == "hosted":
        return bool(settings.vision_base_url)
    return True


def _vision_api_label(settings: Settings) -> str:
    """Name the configured vision API family; local vision has none."""
    if settings.vision_provider == "local":
        return "local (ollama)"
    return settings.vision_api


def _live_vision(settings: Settings) -> tuple[bool, str]:
    """Parse the demo worksheet once and report the count or a redacted error.

    Never prints the API key, the request URL, or a response body: only the
    exception type and the provider client's redacted message are reported.
    """
    image_path = ROOT / "docs" / "image.png"
    try:
        image_bytes = image_path.read_bytes()
    except OSError:
        return False, "cannot read docs/image.png"

    try:
        import httpx

        from agent.vision import VisionClient, VisionError
    except ImportError:
        return False, "vision client is not importable"

    http = httpx.Client(timeout=60.0)
    client = VisionClient(settings, http=http)
    try:
        parse = client.parse_worksheet(image_bytes)
    except VisionError as error:
        return False, f"{type(error).__name__}: {error}"
    except Exception as error:  # noqa: BLE001 - redact anything unexpected
        return False, f"unexpected {type(error).__name__}"
    finally:
        http.close()
    return True, f"{len(parse.items)} items parsed"


def main(*, live: bool = False) -> int:
    try:
        settings = Settings.from_environment()
    except ConfigurationError as error:
        print(f"Configuration: FAIL ({error})")
        return 1

    checks = [
        ("Ollama", _check_ollama(settings)),
        ("faster-whisper import", _check_import("faster_whisper")),
        ("Vision configuration", _check_vision(settings)),
    ]
    print(f"Vision API: {_vision_api_label(settings)}")
    for name, passed in checks:
        print(f"{name}: {'PASS' if passed else 'FAIL'}")

    checks_passed = all(passed for _, passed in checks)
    if not live:
        return 0 if checks_passed else 1

    live_passed, detail = _live_vision(settings)
    print(f"Vision live check: {'PASS' if live_passed else 'FAIL'} ({detail})")
    return 0 if checks_passed and live_passed else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--live",
        action="store_true",
        help="send docs/image.png to the configured vision provider",
    )
    args = parser.parse_args()
    sys.exit(main(live=args.live))
