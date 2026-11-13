"""Local VoxPocket text-to-speech service for the tutor dashboard.

The service is deliberately separate from the main backend environment: the
VoxCPM/torch CUDA stack lives in ``C:\\Users\\ASUS\\voxcpm-tts`` and is never a
dependency of ``requirements.txt``. ``voxcpm`` is imported only inside the lazy
engine factory, so the repository's Python 3.10 environment can import this
module and run the fake-engine tests without the model stack.

Run it with the isolated interpreter from the repository root:

    C:\\Users\\ASUS\\voxcpm-tts\\Scripts\\python.exe scripts\\voxpocket_tts_server.py \\
        --host 127.0.0.1 --port 8001

The browser calls ``POST /tts`` through the Vite proxy. Text, prompts, and keys
are never logged; only the model id, device, and sample rate are reported.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import logging
import os
import re
import threading
import wave
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol

from fastapi import FastAPI
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

logger = logging.getLogger(__name__)

MODEL_ID = "muyleanging/VoxPocket-TTS-Khmer"
DEVICE = "cuda"
DEFAULT_SAMPLE_RATE = 44100
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8001
MAX_TEXT_CHARACTERS = 400
# Spoken style guidance for the designed tutor voice. It is prepended to every
# sentence chunk so the delivery stays consistent across concatenated audio.
VOICE_PROMPT = (
    "(A warm, patient Grade 3 math tutor voice, clear and friendly)"
)

_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+")


class SpeechEngine(Protocol):
    """The small surface this service needs from a VoxCPM pipeline."""

    sample_rate: int

    def generate(self, text: str) -> Sequence[float]:
        """Return mono float samples in [-1.0, 1.0]."""


class TtsRequest(BaseModel):
    text: str


class SpeechService:
    """Owns the lazily loaded engine and serializes generation.

    Loading and generation have separate locks: one request may wait for the
    model to load, but a health check never loads it and never blocks on a
    synthesis call. ``synthesize`` is synchronous and is called in a worker
    thread so the event loop stays responsive during GPU work.
    """

    def __init__(
        self, engine_factory: Callable[[], SpeechEngine] | None = None
    ) -> None:
        self._factory = engine_factory or _default_engine_factory
        self._engine: SpeechEngine | None = None
        self._load_lock = threading.Lock()
        self._generate_lock = threading.Lock()

    @property
    def loaded(self) -> bool:
        return self._engine is not None

    @property
    def sample_rate(self) -> int:
        engine = self._engine
        if engine is None:
            return DEFAULT_SAMPLE_RATE
        rate = getattr(engine, "sample_rate", DEFAULT_SAMPLE_RATE)
        return rate if isinstance(rate, int) and rate > 0 else DEFAULT_SAMPLE_RATE

    def engine(self) -> SpeechEngine:
        engine = self._engine
        if engine is not None:
            return engine
        with self._load_lock:
            if self._engine is None:
                self._engine = self._factory()
            return self._engine

    def synthesize(self, text: str) -> bytes:
        """Generate one tutor line as a PCM16 WAV at the engine's rate."""
        chunks = [f"{VOICE_PROMPT} {sentence}" for sentence in split_sentences(text)]
        with self._generate_lock:
            engine = self.engine()
            sample_rate = self.sample_rate
            samples: list[float] = []
            for chunk in chunks:
                samples.extend(float(value) for value in engine.generate(text=chunk))
        return encode_wav(samples, sample_rate)


def split_sentences(text: str) -> list[str]:
    """Split a bounded tutor line into non-empty sentences."""
    normalized = " ".join(text.split())
    sentences = [
        part.strip() for part in _SENTENCE_BREAK.split(normalized) if part.strip()
    ]
    return sentences or [normalized]


def encode_wav(samples: Sequence[float], sample_rate: int) -> bytes:
    """Encode float samples as mono PCM16 WAV bytes."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(_pcm16(samples))
    return buffer.getvalue()


def _pcm16(samples: Sequence[float]) -> bytes:
    frame = bytearray()
    for value in samples:
        clamped = max(-1.0, min(1.0, float(value)))
        frame.extend(int(round(clamped * 32767.0)).to_bytes(2, "little", signed=True))
    return bytes(frame)


def _default_engine_factory() -> SpeechEngine:
    """Import VoxCPM and load the cache without touching the network.

    The demo cache is ``%USERPROFILE%\\voxcpm-hf``. Set ``VOXPOCKET_CACHE_DIR``
    to move it, or ``VOXPOCKET_ALLOW_DOWNLOAD=1`` to permit a hub download.
    """
    from voxcpm import VoxCPM

    cache_dir = os.getenv("VOXPOCKET_CACHE_DIR") or str(
        Path.home() / "voxcpm-hf"
    )
    local_files_only = os.getenv("VOXPOCKET_ALLOW_DOWNLOAD") != "1"
    return VoxCPM.from_pretrained(
        MODEL_ID,
        load_denoiser=False,
        optimize=False,
        device=DEVICE,
        cache_dir=cache_dir,
        local_files_only=local_files_only,
    )


def create_app(engine_factory: Callable[[], SpeechEngine] | None = None) -> FastAPI:
    """Build the TTS app; the engine is not loaded until the first request."""
    service = SpeechService(engine_factory)
    app = FastAPI(title="VoxPocket tutor speech")

    @app.get("/health")
    async def health() -> dict[str, object]:
        # Never calls SpeechService.engine(): a health check must not load the
        # model, and an unloaded service still reports its planned rate.
        return {
            "status": "ok",
            "model": MODEL_ID,
            "device": DEVICE,
            "loaded": service.loaded,
            "sample_rate": service.sample_rate,
        }

    @app.post("/tts")
    async def synthesize(request: TtsRequest) -> Response:
        text = request.text.strip()
        if not text:
            return _error(400, "empty_text", "text must not be empty")
        if len(text) > MAX_TEXT_CHARACTERS:
            return _error(
                400,
                "text_too_long",
                f"text must be at most {MAX_TEXT_CHARACTERS} characters",
            )
        try:
            audio = await asyncio.to_thread(service.synthesize, text)
        except Exception as error:  # noqa: BLE001 - one redacted failure path
            # The line, prompt, and key never reach the log; only the type.
            logger.warning(
                "Speech synthesis failed (%s)", type(error).__name__
            )
            return _error(
                503,
                "tts_unavailable",
                "The speech service could not generate audio",
            )
        return Response(
            content=audio,
            media_type="audio/wav",
            headers={"Content-Disposition": 'inline; filename="speech.wav"'},
        )

    return app


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code, content={"error": {"code": code, "message": message}}
    )


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Serve the local VoxPocket tutor voice over HTTP."
    )
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args(argv)

    import uvicorn

    uvicorn.run(create_app(), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
