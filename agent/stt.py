"""Local faster-whisper transcription boundaries.

Speech boundaries belong to the browser turn detector; the backend only
receives one validated utterance at a time, so no VAD or segmenter lives here.
"""

from __future__ import annotations

import math
import sys
import threading
from array import array
from collections.abc import Callable, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class Transcript:
    text: str
    confidence: float


class STTError(RuntimeError):
    """Raised when the speech model cannot load or transcribe audio."""


def decode_pcm16le(pcm: bytes) -> list[float]:
    """Convert signed little-endian PCM16 bytes to float samples in [-1.0, 1.0]."""
    if len(pcm) % 2:
        pcm = pcm[: len(pcm) - 1]
    samples = array("h")
    samples.frombytes(pcm)
    if sys.byteorder == "big":
        samples.byteswap()
    return [sample / 32768.0 for sample in samples]


class _FloatSamplesAdapter:
    """Adapt the pipeline's float list to faster-whisper's numpy input."""

    def __init__(self, model: object) -> None:
        self._model = model

    def transcribe(self, samples):
        import numpy

        return self._model.transcribe(
            numpy.asarray(samples, dtype=numpy.float32)
        )


class Transcriber:
    """Owns one speech model and serializes access to it.

    ``_get_model`` uses a double-checked lock so concurrent first turns load
    exactly one model. ``transcribe`` holds a per-transcriber lock for the whole
    call because faster-whisper's model is not documented as reentrant;
    serializing STT is acceptable for one demo session at a time.
    """

    def __init__(
        self,
        model_name: str = "small.en",
        *,
        model_factory: Callable[[], object] | None = None,
        device: str = "cpu",
        compute_type: str = "int8",
    ) -> None:
        self.model_name = model_name
        self.model_factory = model_factory
        # CPU int8 is the demo default: the CUDA run fails on this laptop
        # without cublas64_12.dll, and the GPU is reserved for VoxPocket.
        self.device = device
        self.compute_type = compute_type
        self._model = None
        self._model_lock = threading.Lock()
        self._transcribe_lock = threading.Lock()

    def _get_model(self):
        model = self._model
        if model is not None:
            return model
        with self._model_lock:
            if self._model is not None:
                return self._model
            try:
                if self.model_factory is not None:
                    self._model = self.model_factory()
                else:
                    from faster_whisper import WhisperModel

                    self._model = _FloatSamplesAdapter(
                        WhisperModel(
                            self.model_name,
                            device=self.device,
                            compute_type=self.compute_type,
                        )
                    )
            except STTError:
                raise
            except (ImportError, OSError, RuntimeError, ValueError) as error:
                raise STTError("Speech model is unavailable") from error
            return self._model

    def transcribe(self, samples: Sequence[float]) -> Transcript:
        with self._transcribe_lock:
            model = self._get_model()
            try:
                segments, _ = model.transcribe(samples)
                parts = list(segments)
                text = " ".join(segment.text.strip() for segment in parts).strip()
                confidence = _confidence(parts)
            except STTError:
                raise
            except (OSError, RuntimeError, ValueError, TypeError, AttributeError) as error:
                raise STTError("Transcription failed") from error
        return Transcript(text=text, confidence=confidence)


def _confidence(segments: Sequence[object]) -> float:
    """Turn faster-whisper average log-probability into a 0-1 probability."""
    if not segments:
        return 0.0
    logprobs = [float(getattr(segment, "avg_logprob", 0.0)) for segment in segments]
    mean = sum(logprobs) / len(logprobs)
    return min(1.0, max(0.0, math.exp(min(mean, 0.0))))
