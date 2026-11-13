"""Tests for the separate VoxPocket TTS service (fake engine, main env)."""

import asyncio
import importlib.util
import io
import os
import sys
import threading
import time
import types
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "voxpocket_tts_server.py"
SPEC = importlib.util.spec_from_file_location(
    "voxpocket_tts_server", SCRIPT_PATH
)
assert SPEC is not None and SPEC.loader is not None
tts = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = tts
SPEC.loader.exec_module(tts)


def read_wav(data: bytes) -> tuple[int, int, int, int]:
    with wave.open(io.BytesIO(data), "rb") as wav:
        return (
            wav.getnchannels(),
            wav.getsampwidth(),
            wav.getframerate(),
            wav.getnframes(),
        )


class FakeEngine:
    sample_rate = 44100

    def __init__(self, samples: list[float] | None = None) -> None:
        self.samples = samples if samples is not None else [0.0, 0.5, -0.5]
        self.texts: list[str] = []

    def generate(self, text: str) -> list[float]:
        self.texts.append(text)
        return self.samples


class FailingEngine:
    sample_rate = 44100

    def generate(self, text: str) -> list[float]:
        # Echo the received line so the redaction test proves the route never
        # copies it into a response or a log record.
        raise RuntimeError(f"engine exploded while reading: {text}")


class DefaultEngineFactoryTests(unittest.TestCase):
    """The lazy factory loads the exact cached VoxPocket model contract."""

    def _load(
        self, environment: dict[str, str] | None = None
    ) -> tuple[
        tts.VoxCPMEngine,
        list[tuple[tuple[object, ...], dict[str, object]]],
    ]:
        calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

        class FakeVoxCPM:
            @classmethod
            def from_pretrained(cls, *args, **kwargs):
                calls.append((args, kwargs))
                return FakeEngine()

        module = types.ModuleType("voxcpm")
        module.VoxCPM = FakeVoxCPM
        env = dict(environment or {})
        with patch.dict(sys.modules, {"voxcpm": module}), patch.dict(
            os.environ, env, clear=False
        ):
            # Ambient overrides must not leak into the default assertions.
            for name in ("VOXPOCKET_CACHE_DIR", "VOXPOCKET_ALLOW_DOWNLOAD"):
                if name not in env:
                    os.environ.pop(name, None)
            engine = tts._default_engine_factory()
        return engine, calls

    def test_default_factory_loads_the_cached_model_on_cuda(self) -> None:
        engine, calls = self._load()

        self.assertIsInstance(engine, tts.VoxCPMEngine)
        self.assertIsInstance(engine.model, FakeEngine)
        self.assertEqual(engine.sample_rate, 44100)
        self.assertEqual(len(calls), 1)
        args, kwargs = calls[0]
        self.assertEqual(args, (tts.MODEL_ID,))
        self.assertEqual(
            kwargs,
            {
                "load_denoiser": False,
                "optimize": False,
                "device": "cuda",
                "cache_dir": str(Path.home() / "voxcpm-hf"),
                "local_files_only": True,
            },
        )

    def test_real_adapter_disables_badcase_retries(self) -> None:
        class RetryingModel:
            sample_rate = 44100

            def __init__(self) -> None:
                self.calls: list[tuple[str, bool]] = []

            def generate(self, text: str, retry_badcase: bool = True):
                self.calls.append((text, retry_badcase))
                return [0.25]

        model = RetryingModel()
        engine = tts.VoxCPMEngine(model)

        samples = engine.generate("Hello.")

        self.assertEqual(samples, [0.25])
        self.assertEqual(model.calls, [("Hello.", False)])

    def test_download_flag_allows_the_hub(self) -> None:
        _, calls = self._load({"VOXPOCKET_ALLOW_DOWNLOAD": "1"})

        self.assertFalse(calls[0][1]["local_files_only"])

    def test_cache_override_is_passed_through(self) -> None:
        _, calls = self._load({"VOXPOCKET_CACHE_DIR": "D:/tts-cache"})

        self.assertEqual(calls[0][1]["cache_dir"], "D:/tts-cache")


class TtsServerTests(unittest.TestCase):
    def test_module_import_does_not_import_voxcpm(self) -> None:
        # The repository environment must keep its light dependency set; the
        # model stack is imported only inside the lazy default factory.
        self.assertTrue(hasattr(tts, "VoxCPMEngine"))
        self.assertNotIn("voxcpm", sys.modules)

    def test_health_reports_readiness_without_loading_the_model(self) -> None:
        calls: list[object] = []

        def factory():
            calls.append(object())
            return FakeEngine()

        with TestClient(tts.create_app(factory)) as client:
            response = client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(calls, [])
        self.assertEqual(
            response.json(),
            {
                "status": "ok",
                "model": tts.MODEL_ID,
                "device": "cuda",
                "loaded": False,
                "sample_rate": 44100,
            },
        )

    def test_tts_returns_a_44k_pcm16_wav_and_loads_once(self) -> None:
        engine = FakeEngine([0.0, 0.5, -0.5])
        calls: list[object] = []

        def factory():
            calls.append(object())
            return engine

        with TestClient(tts.create_app(factory)) as client:
            first = client.post("/tts", json={"text": "Say hello."})
            second = client.post("/tts", json={"text": "Say hello again."})
            health = client.get("/health")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.headers["content-type"], "audio/wav")
        channels, width, rate, frames = read_wav(first.content)
        self.assertEqual((channels, width, rate), (1, 2, 44100))
        self.assertEqual(frames, 3)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(len(calls), 1)
        self.assertTrue(health.json()["loaded"])

    def test_voice_prompt_and_sentence_split_reach_the_engine(self) -> None:
        engine = FakeEngine([0.1])
        with TestClient(tts.create_app(lambda: engine)) as client:
            response = client.post(
                "/tts",
                json={"text": "  Ask a question.  Then wait for me!  "},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            engine.texts,
            [
                f"{tts.VOICE_PROMPT} Ask a question.",
                f"{tts.VOICE_PROMPT} Then wait for me!",
            ],
        )
        # Two chunks, one sample each, concatenated in sentence order.
        self.assertEqual(read_wav(response.content)[3], 2)

    def test_tutor_request_keeps_the_voice_prompt(self) -> None:
        engine = FakeEngine([0.1])
        with TestClient(tts.create_app(lambda: engine)) as client:
            response = client.post(
                "/tts",
                json={"text": "Count to ten.", "voice_prompt": True},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            engine.texts, [f"{tts.VOICE_PROMPT} Count to ten."]
        )

    def test_student_request_omits_the_voice_prompt(self) -> None:
        engine = FakeEngine([0.1])
        with TestClient(tts.create_app(lambda: engine)) as client:
            response = client.post(
                "/tts", json={"text": "nine", "voice_prompt": False}
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(engine.texts, ["nine"])

    def test_one_long_sentence_is_not_dropped(self) -> None:
        engine = FakeEngine([0.0])
        with TestClient(tts.create_app(lambda: engine)) as client:
            response = client.post(
                "/tts", json={"text": "x" * tts.MAX_TEXT_CHARACTERS}
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(engine.texts), 1)

    def test_empty_or_whitespace_text_is_rejected(self) -> None:
        calls: list[object] = []

        def factory():
            calls.append(object())
            return FakeEngine()

        with TestClient(tts.create_app(factory)) as client:
            for body in ({"text": ""}, {"text": "   \n\t "}):
                response = client.post("/tts", json=body)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["error"]["code"], "empty_text")

        self.assertEqual(calls, [])

    def test_text_over_400_characters_is_rejected(self) -> None:
        calls: list[object] = []

        def factory():
            calls.append(object())
            return FakeEngine()

        with TestClient(tts.create_app(factory)) as client:
            response = client.post(
                "/tts", json={"text": "a" * (tts.MAX_TEXT_CHARACTERS + 1)}
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "text_too_long")
        self.assertEqual(calls, [])

    def test_engine_failure_is_redacted_and_retryable(self) -> None:
        text = "Count to ten."
        with TestClient(tts.create_app(lambda: FailingEngine())) as client:
            with self.assertLogs(tts.logger, level="WARNING") as captured:
                response = client.post("/tts", json={"text": text})

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json()["error"]["code"], "tts_unavailable"
        )
        self.assertNotIn("engine exploded", response.text)
        self.assertNotIn(text, response.text)
        self.assertNotIn(tts.VOICE_PROMPT, response.text)

        logged = "\n".join(record.getMessage() for record in captured.records)
        self.assertNotIn("engine exploded", logged)
        self.assertNotIn(text, logged)
        self.assertNotIn(tts.VOICE_PROMPT, logged)

    def test_health_stays_responsive_while_generation_blocks(self) -> None:
        started = threading.Event()
        release = threading.Event()

        class BlockingEngine:
            sample_rate = 44100

            def generate(self, text: str) -> list[float]:
                started.set()
                release.wait(2)
                return [0.0]

        app = tts.create_app(BlockingEngine)

        async def scenario():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                turn = asyncio.create_task(
                    client.post("/tts", json={"text": "Hello."})
                )
                # The engine runs in a worker thread, so the loop can answer a
                # health check while the model is busy.
                await asyncio.to_thread(started.wait, 2)
                health = await asyncio.wait_for(client.get("/health"), 1)
                release.set()
                result = await turn
            return health, result

        health, result = asyncio.run(scenario())

        self.assertEqual(health.status_code, 200)
        self.assertTrue(health.json()["loaded"])
        self.assertEqual(result.status_code, 200)

    def test_generation_is_serialized(self) -> None:
        class CountingEngine:
            sample_rate = 44100

            def __init__(self) -> None:
                self.active = 0
                self.max_active = 0
                self._lock = threading.Lock()

            def generate(self, text: str) -> list[float]:
                with self._lock:
                    self.active += 1
                    self.max_active = max(self.max_active, self.active)
                time.sleep(0.03)
                with self._lock:
                    self.active -= 1
                return [0.0]

        engine = CountingEngine()
        app = tts.create_app(lambda: engine)

        async def scenario():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                return await asyncio.gather(
                    client.post("/tts", json={"text": "First line."}),
                    client.post("/tts", json={"text": "Second line."}),
                )

        results = asyncio.run(scenario())

        self.assertEqual([response.status_code for response in results], [200, 200])
        self.assertEqual(engine.max_active, 1)


if __name__ == "__main__":
    unittest.main()
