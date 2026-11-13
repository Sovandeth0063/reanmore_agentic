"""Tests for the IP3 scenario runner, its fixture, and its JSON reports."""

import importlib.util
import io
import json
import sys
import tempfile
import unittest
import wave
from pathlib import Path

import httpx

from agent.config import Settings
from agent.controller import TutorController
from agent.lesson import load_lesson
from agent.llm import TutorIntent
from agent.memory import SessionStore
from agent.render import TemplateRenderer
from agent.stt import Transcript
from agent.vision import WorksheetParse
from server.contract import ContractError, MAX_AUDIO_SECONDS

ROOT = Path(__file__).parents[1]
SCRIPT_PATH = ROOT / "scripts" / "run_scenario.py"
SPEC = importlib.util.spec_from_file_location("run_scenario", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
run_scenario = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = run_scenario
SPEC.loader.exec_module(run_scenario)

LESSON_PATH = ROOT / "agent" / "lessons" / "grade3_demo.yaml"
SCENARIO_PATH = ROOT / "scripts" / "scenarios" / "ip3_homework2.yaml"
FIXTURE_PATH = ROOT / "scripts" / "scenarios" / "ip3_worksheet.json"


class FakeIntent:
    """Classifier stand-in: review the sheet first, then spoken answers."""

    provider = "fake"

    def __init__(self) -> None:
        self.calls = []

    def interpret(self, transcript, state, exercise):
        self.calls.append(transcript)
        if "review" in transcript.lower():
            return TutorIntent("REVIEW", None, None, None)
        return TutorIntent("CHECK_SPOKEN_ANSWER", None, transcript, None)


class ScenarioFileTests(unittest.TestCase):
    def test_scenario_file_lists_sixteen_student_turns(self) -> None:
        scenario = run_scenario.load_scenario(SCENARIO_PATH)

        self.assertEqual(scenario.name, "ip3_homework2")
        self.assertEqual(scenario.worksheet, "docs/image.png")
        self.assertEqual(len(scenario.turns), 16)

    def test_missing_scenario_key_raises_a_clear_error(self) -> None:
        cases = {
            "worksheet": "name: broken\nturns:\n  - student: \"nine\"\n",
            "turns": "name: broken\nworksheet: docs/image.png\n",
            "name": "worksheet: docs/image.png\nturns:\n  - student: \"nine\"\n",
        }
        for missing, body in cases.items():
            with self.subTest(missing=missing):
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "broken.yaml"
                    path.write_text(body, encoding="utf-8")
                    with self.assertRaises(run_scenario.ScenarioError) as raised:
                        run_scenario.load_scenario(path)
                self.assertIn(missing, str(raised.exception))

    def test_checked_in_fixture_parses_into_a_worksheet_parse(self) -> None:
        worksheet = run_scenario.load_worksheet_fixture(FIXTURE_PATH)
        lesson = load_lesson(LESSON_PATH)

        self.assertIsInstance(worksheet, WorksheetParse)
        self.assertEqual(len(worksheet.items), 12)
        self.assertEqual(worksheet.placement, "ready")
        self.assertGreaterEqual(worksheet.confidence, 0.75)
        self.assertEqual(
            [item.item for item in worksheet.items],
            [exercise.id for exercise in lesson.exercises],
        )
        for parsed, exercise in zip(worksheet.items, lesson.exercises):
            self.assertEqual(parsed.section, exercise.section)
            self.assertEqual(parsed.problem, exercise.problem)
            self.assertEqual(parsed.expression, exercise.verification_expression)

    def test_fixture_vision_serves_the_fixture_without_an_image(self) -> None:
        vision = run_scenario.FixtureVision()

        parsed = vision.parse_worksheet(b"not-a-real-image")

        self.assertIsInstance(parsed, WorksheetParse)
        self.assertEqual(len(parsed.items), 12)
        self.assertEqual(vision.parse_calls, 1)


class ReportWriterTests(unittest.TestCase):
    def test_write_report_creates_the_parent_directory(self) -> None:
        report = {"scenario": "unit-test", "mode": "text"}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "results" / "report.json"

            run_scenario.write_report(report, path)

            self.assertTrue(path.is_file())
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8")), report
            )


class LeakScanTests(unittest.TestCase):
    """The milestone scan must catch real answers, not authored operands."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.lesson = load_lesson(LESSON_PATH)

    def test_b6_printed_answer_is_still_a_leak(self) -> None:
        # B6's problem prints its own answer; the step prompt is stripped, but
        # the remaining "5" is still the final answer.
        self.assertTrue(
            run_scenario._leaks_answer(
                "25 / 5 is 5", "B6", set(), self.lesson
            )
        )

    def test_a1_restated_answer_is_a_leak(self) -> None:
        self.assertTrue(
            run_scenario._leaks_answer(
                "4 + 5 + 6 = 15", "A1", set(), self.lesson
            )
        )

    def test_cross_item_answer_is_a_leak(self) -> None:
        # B4's answer spoken during A1 is still an unsolved answer.
        self.assertTrue(
            run_scenario._leaks_answer(
                "B4 is five", "A1", {"A1"}, self.lesson
            )
        )

    def test_printed_operand_is_not_a_leak(self) -> None:
        self.assertFalse(
            run_scenario._leaks_answer(
                "Let's work on 4 + 5 + 6", "A1", set(), self.lesson
            )
        )

    def test_earned_answer_may_be_restated(self) -> None:
        self.assertFalse(
            run_scenario._leaks_answer(
                "That's right, 15", "A1", {"A1"}, self.lesson
            )
        )


class TextScenarioRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = SessionStore("sqlite:///:memory:")
        self.addCleanup(self.store.close)

    def run_report(self):
        return run_scenario.run_text(
            run_scenario.load_scenario(SCENARIO_PATH),
            settings=Settings(),
            store=self.store,
            vision=run_scenario.FixtureVision(),
            intent=FakeIntent(),
            renderer=TemplateRenderer(),
        )

    def test_text_scenario_covers_all_twelve_and_never_leaks_an_answer(
        self,
    ) -> None:
        report = self.run_report()

        self.assertEqual(report["mode"], "text")
        self.assertEqual(report["worksheet"]["items"], 12)
        self.assertEqual(len(report["turns"]), 16)
        self.assertTrue(report["milestones"]["worksheet_recognized"])
        self.assertTrue(report["milestones"]["all_12_covered"])
        self.assertTrue(report["milestones"]["auto_advanced"])
        self.assertFalse(report["milestones"]["final_answer_leaked"])
        self.assertEqual(report["summary"]["turns"], 16)
        self.assertIn("turn_p50_ms", report["summary"])

    def test_report_uses_the_design_schema_and_stage_fields(self) -> None:
        report = self.run_report()

        self.assertEqual(
            set(report),
            {
                "scenario",
                "mode",
                "started_at",
                "worksheet",
                "turns",
                "summary",
                "milestones",
                "errors",
            },
        )
        self.assertEqual(
            set(report["worksheet"]),
            {"vision_ms", "placement", "items"},
        )
        self.assertEqual(report["worksheet"]["placement"], "ready")
        self.assertIsNotNone(report["worksheet"]["vision_ms"])
        self.assertEqual(
            set(report["summary"]),
            {
                "turns",
                "total_ms",
                "turn_p50_ms",
                "turn_p95_ms",
                "tutor_audio_seconds",
            },
        )
        self.assertEqual(
            set(report["milestones"]),
            {
                "worksheet_recognized",
                "all_12_covered",
                "auto_advanced",
                "final_answer_leaked",
            },
        )
        self.assertEqual(report["errors"], [])

        review = report["turns"][0]
        for key in (
            "index",
            "student_text",
            "stt_ms",
            "intent_ms",
            "render_ms",
            "tutor_text",
            "status",
            "capture_request",
            "exercise_id",
            "tts_ms",
            "audio_seconds",
            "total_ms",
        ):
            self.assertIn(key, review)
        self.assertEqual(review["index"], 1)
        self.assertIsNone(review["stt_ms"])
        self.assertEqual(review["capture_request"], "review")
        # The worksheet snapshot is a nested event, not a 17th student turn.
        self.assertEqual(len(report["turns"]), 16)
        self.assertIn("snapshot", review)
        self.assertEqual(review["snapshot"]["exercise_id"], "A1")
        self.assertIn("A1", review["snapshot"]["tutor_text"])
        self.assertIsNotNone(review["snapshot"]["vision_ms"])

        answer = report["turns"][1]
        self.assertEqual(answer["student_text"], "nine")
        self.assertIsNone(answer["stt_ms"])
        self.assertIsNotNone(answer["intent_ms"])
        self.assertIsNotNone(answer["render_ms"])
        self.assertIsNotNone(answer["total_ms"])


class QueueTranscriber:
    """Return the scripted student line for each posted turn."""

    def __init__(self, lines) -> None:
        self.lines = list(lines)
        self.index = 0

    def transcribe(self, samples):
        text = self.lines[self.index] if self.index < len(self.lines) else ""
        self.index += 1
        return Transcript(text, 0.99)


class FakeTts:
    """A 44.1 kHz PCM16 WAV generator that records every line it speaks."""

    def __init__(self, sample_rate: int = 44100, seconds: float = 0.05) -> None:
        self.sample_rate = sample_rate
        self.seconds = seconds
        self.calls: list[str] = []
        self.prompts: list[bool] = []
        self.health_checks = 0

    def health(self) -> None:
        self.health_checks += 1

    def synthesize(self, text: str, voice_prompt: bool = True) -> bytes:
        self.calls.append(text)
        self.prompts.append(voice_prompt)
        return make_wav(self.sample_rate, self.seconds)


class LongFirstStudentClipTts(FakeTts):
    """Short greeting and tutor lines; the first student line is overlong."""

    def __init__(self) -> None:
        super().__init__(sample_rate=44100, seconds=0.05)
        self._synthesized = 0

    def synthesize(self, text: str, voice_prompt: bool = True) -> bytes:
        self._synthesized += 1
        if self._synthesized == 2:  # greeting, then student turn 1
            self.calls.append(text)
            self.prompts.append(voice_prompt)
            return make_wav(self.sample_rate, MAX_AUDIO_SECONDS + 1)
        return super().synthesize(text, voice_prompt=voice_prompt)


def make_wav(sample_rate: int, seconds: float) -> bytes:
    frames = max(1, int(sample_rate * seconds))
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b"\x00\x00" * frames)
    return buffer.getvalue()


class StudentAudioCapTests(unittest.TestCase):
    def test_trim_leaves_short_pcm_unchanged(self) -> None:
        pcm = b"\x00\x01" * 100

        trimmed, truncated = run_scenario.trim_turn_pcm(pcm)

        self.assertEqual(trimmed, pcm)
        self.assertFalse(truncated)

    def test_trim_caps_long_pcm_at_the_contract_maximum(self) -> None:
        limit = run_scenario.MAX_AUDIO_BYTES
        pcm = b"\x00\x01" * (limit // 2 + 1000)

        trimmed, truncated = run_scenario.trim_turn_pcm(pcm)

        self.assertTrue(truncated)
        self.assertEqual(len(trimmed), limit)
        self.assertEqual(trimmed, pcm[:limit])
        self.assertEqual(len(trimmed) % 2, 0)


class FakeHttpApi:
    """An in-process backend: the real controller plus its SQLite tool log."""

    SESSION_ID = "fake-voice-session"

    def __init__(self, lines) -> None:
        self.store = SessionStore("sqlite:///:memory:")
        self.lesson = load_lesson(LESSON_PATH)
        self.controller = TutorController(
            self.SESSION_ID,
            lesson=self.lesson,
            store=self.store,
            vision=run_scenario.FixtureVision(),
            intent=FakeIntent(),
            transcriber=QueueTranscriber(lines),
            renderer=TemplateRenderer(),
            flow_mode="guided",
        )
        self.posted_pcm: list[bytes] = []
        self.snapshot_calls: list[dict] = []
        self.health_checks = 0
        self.ended = False

    def close(self) -> None:
        self.store.close()

    def health(self) -> None:
        self.health_checks += 1

    def create_session(self) -> dict:
        return self._call(self.controller.create_response)

    def turn(self, session_id: str, pcm: bytes) -> dict:
        self.posted_pcm.append(pcm)
        return self._call(
            lambda: self.controller.handle_audio(pcm, "audio/l16")
        )

    def snapshot(
        self,
        session_id: str,
        image: bytes,
        purpose: str,
        exercise_id: str | None = None,
    ) -> dict:
        self.snapshot_calls.append(
            {
                "purpose": purpose,
                "exercise_id": exercise_id,
                "jpeg": image.startswith(b"\xff\xd8\xff"),
                "size": len(image),
            }
        )
        return self._call(
            lambda: self.controller.handle_snapshot(
                image, "image/jpeg", purpose, exercise_id
            )
        )

    def tool_rows(self, session_id: str, after_id: int):
        rows = self.store.connection.execute(
            "SELECT id, name, duration_ms, success FROM tool_calls "
            "WHERE session_id = ? AND id > ? ORDER BY id",
            (session_id, after_id),
        ).fetchall()
        if rows:
            after_id = rows[-1]["id"]
        return after_id, rows

    def session_state(self, session_id: str) -> dict:
        state = self.store.get(session_id)
        if state is None:
            raise run_scenario.ServiceResponseError(
                "session_missing", "missing session"
            )
        return {
            "chosen_exercise": state.chosen_exercise,
            "last_answer": state.last_answer,
            "placement_confirmed": state.placement_confirmed,
        }

    def end_session(self, session_id: str) -> None:
        self.ended = True
        self.store.delete(session_id)

    @staticmethod
    def _call(operation) -> dict:
        try:
            return operation().to_payload()
        except ContractError as error:
            raise run_scenario.ServiceResponseError(
                error.code, error.message
            ) from error


class RecordingHttp:
    """Record method calls and return one canned httpx response."""

    def __init__(self, response) -> None:
        self.response = response
        self.gets: list[tuple[str, dict]] = []
        self.posts: list[tuple[str, dict]] = []
        self.deletes: list[tuple[str, dict]] = []

    def get(self, url, **kwargs):
        self.gets.append((url, kwargs))
        return self.response

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        return self.response

    def delete(self, url, **kwargs):
        self.deletes.append((url, kwargs))
        return self.response


class FailingHttp:
    """A client whose every call fails as if the service were not running."""

    def get(self, url, **kwargs):
        raise httpx.ConnectError(
            "connection refused", request=httpx.Request("GET", url)
        )

    def post(self, url, **kwargs):
        raise httpx.ConnectError(
            "connection refused", request=httpx.Request("POST", url)
        )

    def delete(self, url, **kwargs):
        raise httpx.ConnectError(
            "connection refused", request=httpx.Request("DELETE", url)
        )


class UnhealthyTts:
    """A health check that fails before any line is synthesized."""

    def health(self) -> None:
        raise run_scenario.ServiceUnavailableError(
            "The TTS service is not reachable at http://127.0.0.1:8001. "
            "Start it before running voice mode."
        )

    def synthesize(self, text: str, voice_prompt: bool = True) -> bytes:
        raise AssertionError("no synthesis without a healthy service")


def temp_db_url() -> str:
    return "sqlite:///" + str(
        Path(tempfile.gettempdir()) / "ai-math-tutor-scenario-unused.db"
    )


class VoiceScenarioRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scenario = run_scenario.load_scenario(SCENARIO_PATH)

    def run_voice(self, tts=None, audio_dir=None):
        http = FakeHttpApi(self.scenario.turns)
        self.addCleanup(http.close)
        if tts is None:
            tts = FakeTts()
        report = run_scenario.run_voice(
            self.scenario, http=http, tts=tts, audio_dir=audio_dir
        )
        return report, http, tts

    def test_voice_runner_posts_audio_and_records_tts(self) -> None:
        report, http, tts = self.run_voice()

        self.assertEqual(report["mode"], "voice")
        self.assertEqual(len(report["turns"]), 16)
        self.assertTrue(
            all(turn["stt_ms"] is not None for turn in report["turns"])
        )
        self.assertTrue(
            all(turn["tts_ms"] is not None for turn in report["turns"])
        )
        self.assertGreater(report["summary"]["tutor_audio_seconds"], 0)
        self.assertEqual(len(http.posted_pcm), 16)
        self.assertTrue(all(len(pcm) % 2 == 0 for pcm in http.posted_pcm))
        self.assertIn("nine", tts.calls)

    def test_student_lines_are_plain_and_tutor_lines_keep_the_voice_prompt(
        self,
    ) -> None:
        report, _, tts = self.run_voice()

        self.assertEqual(len(tts.calls), len(tts.prompts))
        plain = [
            text
            for text, voice_prompt in zip(tts.calls, tts.prompts)
            if not voice_prompt
        ]
        self.assertEqual(
            plain, [turn["student_text"] for turn in report["turns"]]
        )

        prompted = [
            text
            for text, voice_prompt in zip(tts.calls, tts.prompts)
            if voice_prompt
        ]
        expected = [report["greeting"]["tutor_text"]]
        for turn in report["turns"]:
            expected.append(turn["tutor_text"])
            if "snapshot" in turn:
                expected.append(turn["snapshot"]["tutor_text"])
        self.assertEqual(prompted, expected)

    def test_44k_wav_is_resampled_to_16k_before_the_turn(self) -> None:
        tts = FakeTts(sample_rate=44100, seconds=0.25)

        report, http, _ = self.run_voice(tts=tts)

        expected_bytes = run_scenario.TURN_SAMPLE_RATE * 0.25 * 2
        self.assertTrue(http.posted_pcm)
        for pcm in http.posted_pcm:
            self.assertAlmostEqual(len(pcm), expected_bytes, delta=4)
        self.assertAlmostEqual(
            report["turns"][0]["audio_seconds"], 0.25, places=3
        )

        clip = run_scenario.read_wav(make_wav(44100, 0.5))
        pcm = run_scenario.to_turn_pcm(clip)
        self.assertAlmostEqual(
            len(pcm) / (2 * run_scenario.TURN_SAMPLE_RATE),
            clip.seconds,
            places=3,
        )

    def test_long_student_clip_is_trimmed_and_flagged(self) -> None:
        report, http, _ = self.run_voice(tts=LongFirstStudentClipTts())

        self.assertEqual(report["errors"], [])
        self.assertEqual(len(report["turns"]), 16)
        self.assertTrue(report["turns"][0]["student_audio_truncated"])
        self.assertEqual(
            len(http.posted_pcm[0]), run_scenario.MAX_AUDIO_BYTES
        )
        self.assertTrue(
            all(
                not turn["student_audio_truncated"]
                for turn in report["turns"][1:]
            )
        )

    def test_voice_scenario_covers_all_twelve_without_leaking(self) -> None:
        report, http, _ = self.run_voice()

        self.assertEqual(report["worksheet"]["items"], 12)
        self.assertEqual(report["worksheet"]["placement"], "ready")
        self.assertIsNotNone(report["worksheet"]["vision_ms"])
        self.assertTrue(report["milestones"]["worksheet_recognized"])
        self.assertTrue(report["milestones"]["all_12_covered"])
        self.assertTrue(report["milestones"]["auto_advanced"])
        self.assertFalse(report["milestones"]["final_answer_leaked"])
        self.assertEqual(report["errors"], [])
        self.assertTrue(http.ended)

    def test_voice_report_records_snapshot_and_stage_fields(self) -> None:
        report, http, _ = self.run_voice()

        self.assertEqual(
            set(report["summary"]),
            {
                "turns",
                "total_ms",
                "turn_p50_ms",
                "turn_p95_ms",
                "tutor_audio_seconds",
            },
        )
        self.assertEqual(
            set(report["greeting"]),
            {
                "tutor_text",
                "status",
                "capture_request",
                "exercise_id",
                "tts_ms",
                "audio_seconds",
            },
        )
        self.assertIsNotNone(report["greeting"]["tts_ms"])
        self.assertGreater(report["greeting"]["audio_seconds"], 0)
        first = report["turns"][0]
        self.assertEqual(first["student_text"], "Ask me to review your worksheet.")
        self.assertEqual(first["capture_request"], "review")
        self.assertIsNone(first["exercise_id"])
        self.assertIsNotNone(first["stt_ms"])
        snapshot = first["snapshot"]
        self.assertEqual(snapshot["exercise_id"], "A1")
        self.assertIsNotNone(snapshot["vision_ms"])
        self.assertIsNotNone(snapshot["tts_ms"])
        self.assertGreater(snapshot["audio_seconds"], 0)
        self.assertEqual(http.snapshot_calls[0]["purpose"], "review")
        self.assertTrue(http.snapshot_calls[0]["jpeg"])
        self.assertGreater(http.snapshot_calls[0]["size"], 0)

        answer = report["turns"][1]
        self.assertIsNotNone(answer["intent_ms"])
        self.assertIsNotNone(answer["render_ms"])

    def test_audio_is_written_only_when_an_explicit_directory_is_given(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report, _, _ = self.run_voice(audio_dir=directory)

            files = sorted(Path(directory).glob("*.wav"))
            self.assertEqual(len(files), 34)
            self.assertTrue(
                (Path(directory) / "greeting-tutor.wav").is_file()
            )
            self.assertTrue(
                (Path(directory) / "turn-01-student.wav").is_file()
            )
            self.assertTrue(
                (Path(directory) / "turn-01-tutor.wav").is_file()
            )
            self.assertTrue(
                (Path(directory) / "turn-01-review-tutor.wav").is_file()
            )
            self.assertTrue(files[0].read_bytes().startswith(b"RIFF"))
            self.assertEqual(report["mode"], "voice")

    def test_audio_directory_inside_the_repository_is_refused(self) -> None:
        target = ROOT / "docs" / "scenario-audio-test"

        with self.assertRaises(run_scenario.ScenarioError) as raised:
            self.run_voice(audio_dir=target)

        self.assertIn("outside the repository", str(raised.exception))
        self.assertFalse(target.exists())

    def test_missing_tts_service_is_a_clear_error(self) -> None:
        tts = run_scenario.HttpTts(
            FailingHttp(), base_url=run_scenario.DEFAULT_TTS_URL
        )
        with self.assertRaises(run_scenario.ScenarioError) as raised:
            tts.health()
        message = str(raised.exception)
        self.assertIn("TTS service", message)
        self.assertIn("8001", message)

        with self.assertRaises(run_scenario.ScenarioError) as raised:
            self.run_voice(tts=UnhealthyTts())
        self.assertIn("TTS service", str(raised.exception))

    def test_missing_backend_is_a_clear_error(self) -> None:
        backend = run_scenario.HttpBackend(
            FailingHttp(),
            base_url=run_scenario.DEFAULT_BACKEND_URL,
            db_url=temp_db_url(),
        )

        with self.assertRaises(run_scenario.ScenarioError) as raised:
            backend.health()

        message = str(raised.exception)
        self.assertIn("backend session API", message)
        self.assertIn("8000", message)

    def test_tts_http_failure_reports_only_the_code(self) -> None:
        client = RecordingHttp(
            httpx.Response(
                503,
                json={
                    "error": {
                        "code": "tts_unavailable",
                        "message": "The speech service could not generate audio",
                    }
                },
            )
        )
        tts = run_scenario.HttpTts(
            client, base_url=run_scenario.DEFAULT_TTS_URL
        )

        with self.assertRaises(run_scenario.ScenarioError) as raised:
            tts.synthesize("A tutor line that must not be echoed")

        self.assertIn("tts_unavailable", str(raised.exception))
        self.assertNotIn("A tutor line", str(raised.exception))

    def test_tts_posts_json_and_returns_the_wav_body(self) -> None:
        wav = make_wav(44100, 0.05)
        client = RecordingHttp(httpx.Response(200, content=wav))
        tts = run_scenario.HttpTts(
            client, base_url=run_scenario.DEFAULT_TTS_URL
        )

        audio = tts.synthesize("Hello.")

        self.assertEqual(audio, wav)
        url, kwargs = client.posts[0]
        self.assertTrue(url.endswith("/tts"))
        self.assertEqual(
            kwargs["json"], {"text": "Hello.", "voice_prompt": True}
        )

        tts.synthesize("nine", voice_prompt=False)
        _, kwargs = client.posts[1]
        self.assertEqual(
            kwargs["json"], {"text": "nine", "voice_prompt": False}
        )


class HttpContractTests(unittest.TestCase):
    def test_turn_posts_pcm16_multipart_to_the_turn_endpoint(self) -> None:
        client = RecordingHttp(
            httpx.Response(
                200,
                json={
                    "contract_version": 1,
                    "session_id": "s1",
                    "tutor_text": "Hi.",
                    "status": "speaking",
                },
            )
        )
        backend = run_scenario.HttpBackend(
            client,
            base_url=run_scenario.DEFAULT_BACKEND_URL,
            db_url=temp_db_url(),
        )
        pcm = b"\x00\x01" * 8

        response = backend.turn("s1", pcm)

        self.assertEqual(response["exercise_id"], None)
        url, kwargs = client.posts[0]
        self.assertEqual(
            url, "http://127.0.0.1:8000/sessions/s1/turn"
        )
        name, payload, content_type = kwargs["files"]["audio"]
        self.assertEqual(name, "turn.pcm")
        self.assertEqual(payload, pcm)
        self.assertEqual(content_type, "audio/l16")

    def test_snapshot_posts_a_jpeg_and_the_purpose(self) -> None:
        client = RecordingHttp(
            httpx.Response(
                200,
                json={
                    "contract_version": 1,
                    "session_id": "s1",
                    "tutor_text": "I can see it.",
                    "status": "speaking",
                    "capture_request": None,
                    "exercise_id": "A1",
                },
            )
        )
        backend = run_scenario.HttpBackend(
            client,
            base_url=run_scenario.DEFAULT_BACKEND_URL,
            db_url=temp_db_url(),
        )
        jpeg = b"\xff\xd8\xff" + b"x" * 10

        backend.snapshot("s1", jpeg, "review", None)

        url, kwargs = client.posts[0]
        self.assertEqual(
            url, "http://127.0.0.1:8000/sessions/s1/snapshot"
        )
        self.assertEqual(kwargs["data"], {"purpose": "review"})
        name, payload, content_type = kwargs["files"]["image"]
        self.assertEqual(name, "worksheet.jpg")
        self.assertEqual(payload, jpeg)
        self.assertEqual(content_type, "image/jpeg")

    def test_backend_reads_tool_rows_and_session_state_from_sqlite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_url = "sqlite:///" + str(Path(directory) / "tutor.db")
            store = SessionStore(db_url)
            try:
                store.create("s1")
                store.update(
                    "s1",
                    chosen_exercise="A1",
                    last_answer="15",
                    placement_confirmed=True,
                )
                store.append_tool_call(
                    "s1", "stt.transcribe", duration_ms=12.5
                )
            finally:
                store.close()

            backend = run_scenario.HttpBackend(
                RecordingHttp(httpx.Response(200)), db_url=db_url
            )

            after, rows = backend.tool_rows("s1", 0)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["name"], "stt.transcribe")
            self.assertEqual(rows[0]["duration_ms"], 12.5)
            self.assertEqual(backend.tool_rows("s1", after), (after, []))
            self.assertEqual(
                backend.session_state("s1"),
                {
                    "chosen_exercise": "A1",
                    "last_answer": "15",
                    "placement_confirmed": True,
                },
            )


class BothModeComparisonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scenario = run_scenario.load_scenario(SCENARIO_PATH)

    def reports(self):
        store = SessionStore("sqlite:///:memory:")
        self.addCleanup(store.close)
        text = run_scenario.run_text(
            self.scenario,
            settings=Settings(),
            store=store,
            vision=run_scenario.FixtureVision(),
            intent=FakeIntent(),
            renderer=TemplateRenderer(),
        )
        http = FakeHttpApi(self.scenario.turns)
        self.addCleanup(http.close)
        voice = run_scenario.run_voice(
            self.scenario, http=http, tts=FakeTts()
        )
        return text, voice

    def test_text_and_voice_agree_on_structure_and_milestones(self) -> None:
        text, voice = self.reports()

        comparison = run_scenario.compare_reports(text, voice)

        self.assertEqual(comparison["text_diff_count"], 0)
        self.assertEqual(comparison["diffs"], [])
        self.assertTrue(comparison["milestones_match"])
        self.assertEqual(
            comparison["turn_count"], {"text": 16, "voice": 16}
        )

    def test_both_report_records_the_pinned_text_renderer(self) -> None:
        text, voice = self.reports()

        report = run_scenario.build_both_report(
            text, voice, configured_renderer="llm"
        )

        self.assertEqual(report["mode"], "both")
        self.assertEqual(
            report["renderers"], {"text": "template", "voice": "llm"}
        )
        self.assertEqual(report["text_diff_count"], 0)
        self.assertEqual(report["comparison"]["text_diff_count"], 0)
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["text"]["mode"], "text")
        self.assertEqual(report["voice"]["mode"], "voice")

    def test_structural_and_milestone_differences_are_counted(self) -> None:
        text, voice = self.reports()
        changed = json.loads(json.dumps(voice))
        changed["turns"][1]["status"] = "listening"

        comparison = run_scenario.compare_reports(text, changed)

        self.assertEqual(comparison["text_diff_count"], 1)
        self.assertTrue(comparison["milestones_match"])
        self.assertEqual(comparison["diffs"][0]["field"], "status")

        changed["milestones"]["all_12_covered"] = False
        comparison = run_scenario.compare_reports(text, changed)
        self.assertEqual(comparison["text_diff_count"], 2)
        self.assertFalse(comparison["milestones_match"])


class ExitPolicyTests(unittest.TestCase):
    def good_report(self) -> dict:
        return {
            "mode": "text",
            "errors": [],
            "milestones": {
                "worksheet_recognized": True,
                "all_12_covered": True,
                "auto_advanced": True,
                "final_answer_leaked": False,
            },
        }

    def test_a_clean_report_passes(self) -> None:
        self.assertTrue(run_scenario._report_ok(self.good_report()))

    def test_a_required_milestone_failure_fails_the_run(self) -> None:
        report = self.good_report()
        report["milestones"]["auto_advanced"] = False
        self.assertFalse(run_scenario._report_ok(report))

    def test_a_leaked_answer_fails_the_run(self) -> None:
        report = self.good_report()
        report["milestones"]["final_answer_leaked"] = True
        self.assertFalse(run_scenario._report_ok(report))

    def test_an_error_fails_the_run(self) -> None:
        report = self.good_report()
        report["errors"] = [
            {"turn": 1, "stage": "turn", "error": "http_500"}
        ]
        self.assertFalse(run_scenario._report_ok(report))

    def test_both_requires_both_passes_to_pass(self) -> None:
        good = self.good_report()
        voice = self.good_report()
        voice["mode"] = "voice"
        both = {
            "mode": "both",
            "errors": [],
            "text": good,
            "voice": voice,
        }
        self.assertTrue(run_scenario._report_ok(both))

        voice["milestones"]["all_12_covered"] = False
        self.assertFalse(run_scenario._report_ok(both))


if __name__ == "__main__":
    unittest.main()
