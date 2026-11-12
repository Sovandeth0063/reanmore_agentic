"""Tests for PCM decoding, transcription, and confidence."""

import math
import threading
import time
import unittest

from agent.stt import (
    STTError,
    Transcriber,
    decode_pcm16le,
)


class PcmDecodeTests(unittest.TestCase):
    def test_decode_pcm16le(self) -> None:
        samples = decode_pcm16le(b"\x00\x00\xff\x7f")
        self.assertEqual(len(samples), 2)
        self.assertAlmostEqual(samples[0], 0.0, places=4)
        self.assertAlmostEqual(samples[1], 1.0, places=4)

    def test_decode_pcm16le_handles_negative_values(self) -> None:
        self.assertAlmostEqual(decode_pcm16le(b"\x00\x80")[0], -1.0, places=4)

    def test_decode_pcm16le_ignores_a_trailing_odd_byte(self) -> None:
        self.assertEqual(decode_pcm16le(b"\x00\x00\x01"), [0.0])


class FakeSegment:
    def __init__(self, text: str, avg_logprob: float) -> None:
        self.text = text
        self.avg_logprob = avg_logprob


class FakeWhisperModel:
    def __init__(self, segments: list[FakeSegment]) -> None:
        self.segments = segments
        self.inputs: list[list[float]] = []

    def transcribe(self, samples):
        self.inputs.append(samples)
        return iter(self.segments), None


class TranscriberTests(unittest.TestCase):
    def test_transcriber_confidence_is_probability(self) -> None:
        model = FakeWhisperModel([FakeSegment(" fifteen ", -0.1)])
        transcriber = Transcriber(model_factory=lambda: model)

        transcript = transcriber.transcribe([0.0, 0.5])

        self.assertEqual(transcript.text, "fifteen")
        self.assertAlmostEqual(transcript.confidence, math.exp(-0.1), places=6)
        self.assertEqual(model.inputs, [[0.0, 0.5]])

    def test_transcriber_averages_segment_log_probabilities(self) -> None:
        model = FakeWhisperModel(
            [FakeSegment("six", -0.2), FakeSegment("teen", -0.4)]
        )
        transcript = Transcriber(model_factory=lambda: model).transcribe([0.0])
        self.assertAlmostEqual(transcript.confidence, math.exp(-0.3), places=6)
        self.assertEqual(transcript.text, "six teen")

    def test_transcriber_confidence_is_clamped(self) -> None:
        loud = FakeWhisperModel([FakeSegment("hi", 1.0)])
        transcript = Transcriber(model_factory=lambda: loud).transcribe([0.0])
        self.assertEqual(transcript.confidence, 1.0)

    def test_empty_transcription_has_zero_confidence(self) -> None:
        model = FakeWhisperModel([])
        transcript = Transcriber(model_factory=lambda: model).transcribe([0.0])
        self.assertEqual(transcript.text, "")
        self.assertEqual(transcript.confidence, 0.0)

    def test_model_factory_is_used_once(self) -> None:
        calls: list[int] = []

        def factory():
            calls.append(1)
            return FakeWhisperModel([FakeSegment("hi", -0.2)])

        transcriber = Transcriber(model_factory=factory)
        transcriber.transcribe([0.0])
        transcriber.transcribe([0.0])

        self.assertEqual(len(calls), 1)

    def test_model_failure_becomes_an_stt_error(self) -> None:
        def factory():
            raise RuntimeError("model unavailable")

        with self.assertRaises(STTError):
            Transcriber(model_factory=factory).transcribe([0.0])

    def test_transcription_failure_becomes_an_stt_error(self) -> None:
        class ExplodingModel:
            def transcribe(self, samples):
                raise RuntimeError("transcription failed")

        with self.assertRaises(STTError):
            Transcriber(model_factory=lambda: ExplodingModel()).transcribe([0.0])


class TranscriberConcurrencyTests(unittest.TestCase):
    def test_concurrent_first_turns_load_one_model(self) -> None:
        loads: list[str] = []
        transcripts: list[object] = []

        def factory():
            loads.append(threading.current_thread().name)
            time.sleep(0.01)
            return FakeWhisperModel([FakeSegment("hi", -0.2)])

        transcriber = Transcriber(model_factory=factory)

        def run() -> None:
            transcripts.append(transcriber.transcribe([0.0]))

        threads = [threading.Thread(target=run) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(5)

        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(len(loads), 1)
        self.assertEqual(len(transcripts), 4)

    def test_concurrent_transcriptions_do_not_overlap(self) -> None:
        class SlowModel:
            def __init__(self) -> None:
                self.active = 0
                self.max_active = 0
                self._lock = threading.Lock()

            def transcribe(self, samples):
                with self._lock:
                    self.active += 1
                    self.max_active = max(self.max_active, self.active)
                time.sleep(0.05)
                with self._lock:
                    self.active -= 1
                return iter([FakeSegment("hi", -0.2)]), None

        model = SlowModel()
        transcriber = Transcriber(model_factory=lambda: model)
        transcripts: list[object] = []
        start = threading.Barrier(3)

        def run() -> None:
            start.wait()
            transcripts.append(transcriber.transcribe([0.0]))

        threads = [threading.Thread(target=run) for _ in range(3)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(5)

        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(len(transcripts), 3)
        self.assertEqual(model.max_active, 1)


if __name__ == "__main__":
    unittest.main()
