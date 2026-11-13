"""Tests for selected-item handwriting reads and verified feedback."""

import json
import io
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from agent.config import Settings
from agent.controller import TutorController
from agent.lesson import load_lesson
from agent.llm import TutorIntent
from agent.memory import SessionStore
from agent.responses import select_response, uncertain_prompt
from agent.sheet_layout import load_layout
from agent.stt import Transcript
from agent.tutor import TutorSession, TutorState
from agent.vision import (
    VISIBILITY_BLANK,
    VISIBILITY_CLEAR,
    VISIBILITY_MULTIPLE_ANSWER,
    VISIBILITY_OBSCURED,
    VISIBILITY_OVERWRITTEN,
    VISIBILITY_UNCLEAR,
    VISIBILITY_WRONG_ITEM,
    AnswerArea,
    HandwritingRead,
    ParsedItem,
    VisionClient,
    VisionError,
    WorksheetParse,
)
from server.contract import (
    CAPTURE_CHECK,
    STATUS_ADJUST_SHEET,
    STATUS_READING_WORK,
    STATUS_SPEAKING,
)

LESSON_PATH = Path(__file__).parents[1] / "agent" / "lessons" / "grade3_demo.yaml"
SESSION_ID = "handwriting"


def _jpeg_bytes() -> bytes:
    """A decodable stand-in photo; crops are real image work, reads are faked."""
    buffer = io.BytesIO()
    Image.new("RGB", (320, 428), (250, 250, 250)).save(
        buffer, format="JPEG", quality=90
    )
    return buffer.getvalue()


JPEG_BYTES = _jpeg_bytes()
SHEET_CORNERS = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))
OPENCODE_BASE_URL = "https://opencode.ai/inference/openai/v1"
ENDPOINT = OPENCODE_BASE_URL + "/chat/completions"


class FakeResponse:
    def __init__(self, body: dict) -> None:
        self.body = body

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.body


class FakeHttp:
    def __init__(self, *responses) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []

    def post(self, url: str, headers=None, **kwargs):
        self.calls.append(
            {"url": url, "headers": headers, "json": kwargs.get("json")}
        )
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def hosted_body(content: str) -> dict:
    return {"choices": [{"message": {"content": content}}]}


def make_settings(**overrides) -> Settings:
    values = {
        "ollama_model": "model",
        "vision_provider": "hosted",
        "vision_base_url": OPENCODE_BASE_URL,
        "vision_model": "vision-model",
        "vision_api_key": "vision-key",
    }
    values.update(overrides)
    return Settings(**values)


def read_body(**overrides) -> dict:
    body = {
        "raw_text": "87",
        "value": "87",
        "confidence": 0.97,
        "visible_work": "63 + 24",
        "visibility": VISIBILITY_CLEAR,
        "location": "lower left answer box",
        "reasons": [],
    }
    body.update(overrides)
    return body


def valid_sheet(lesson) -> WorksheetParse:
    return WorksheetParse(
        [
            ParsedItem(
                exercise.id,
                exercise.section,
                exercise.problem,
                exercise.verification_expression,
            )
            for exercise in lesson.exercises
        ],
        0.99,
    )


class FakeTranscriber:
    def __init__(self) -> None:
        self.transcript = Transcript("", 0.95)

    def transcribe(self, samples):
        return self.transcript


class FakeIntent:
    def __init__(self) -> None:
        self.intent = TutorIntent("UNCLEAR", None, None, None)

    def interpret(self, transcript, state, exercise):
        return self.intent


class FakeVision:
    def __init__(self, worksheet) -> None:
        self.worksheet = worksheet
        self.reading = None
        self.area = None
        self.layout = load_layout()
        self.locate_error = None
        self.read_error = None
        self.locate_calls = 0
        self.readings: list[dict] = []
        self.read_calls = 0

    def parse_worksheet(self, image):
        return self.worksheet

    def locate_answer_area(self, image, exercise):
        self.locate_calls += 1
        if self.locate_error is not None:
            raise self.locate_error
        if self.area is not None:
            return self.area
        return AnswerArea(
            exercise["id"],
            self.layout.expected_box(exercise["id"]),
            SHEET_CORNERS,
            0.99,
            "sheet corners found",
        )

    def read_handwriting(self, image, exercise):
        self.read_calls += 1
        self.readings.append(exercise)
        if self.read_error is not None:
            raise self.read_error
        return self.reading


class HandwritingVisionTests(unittest.TestCase):
    def _read(self, **overrides) -> tuple[HandwritingRead, FakeHttp]:
        http = FakeHttp(
            FakeResponse(hosted_body(json.dumps(read_body(**overrides))))
        )
        client = VisionClient(make_settings(), http)
        return client.read_handwriting(b"image-bytes", {"id": "A2"}), http

    def test_returns_visibility_location_and_reasons(self) -> None:
        read, _ = self._read(
            visibility=VISIBILITY_OBSCURED,
            location="x" * 200,
            reasons=["hand covers it", "shadow", "blur", "tilt", "glare", "six"],
        )

        self.assertEqual(read.visibility, VISIBILITY_OBSCURED)
        self.assertEqual(read.location, "x" * 160)
        self.assertEqual(len(read.reasons), 5)
        self.assertEqual(read.reasons[0], "hand covers it")
        self.assertTrue(all(len(reason) <= 160 for reason in read.reasons))

    def test_reasons_are_capped_at_160_characters(self) -> None:
        read, _ = self._read(reasons=["y" * 200])

        self.assertEqual(read.reasons, ("y" * 160,))

    def test_missing_visibility_defaults_to_clear(self) -> None:
        body = read_body()
        body.pop("visibility")
        http = FakeHttp(FakeResponse(hosted_body(json.dumps(body))))
        parsed = VisionClient(make_settings(), http).read_handwriting(
            b"image-bytes", {"id": "A2"}
        )

        self.assertEqual(parsed.visibility, VISIBILITY_CLEAR)
        self.assertEqual(parsed.location, "lower left answer box")

    def test_unknown_visibility_becomes_unclear(self) -> None:
        http = FakeHttp(
            FakeResponse(
                hosted_body(json.dumps(read_body(visibility="sideways")))
            )
        )
        client = VisionClient(make_settings(), http)

        read = client.read_handwriting(b"image-bytes", {"id": "A2"})

        self.assertEqual(read.visibility, VISIBILITY_UNCLEAR)
        self.assertNotEqual(read.visibility, VISIBILITY_CLEAR)

    def test_non_object_json_payload_raises_for_both_reads(self) -> None:
        for method in ("parse_worksheet", "read_handwriting"):
            with self.subTest(method=method):
                http = FakeHttp(
                    FakeResponse(hosted_body(json.dumps(["not", "an", "object"])))
                )
                client = VisionClient(make_settings(), http)
                with self.assertRaises(VisionError):
                    if method == "parse_worksheet":
                        client.parse_worksheet(b"image-bytes")
                    else:
                        client.read_handwriting(b"image-bytes", {"id": "A2"})

    def test_instruction_requests_the_read_contract_for_one_item(self) -> None:
        _, http = self._read()
        content = http.calls[0]["json"]["messages"][0]["content"][0]["text"]
        instruction = json.loads(content)["instruction"]

        for field in (
            "raw_text",
            "value",
            "confidence",
            "visible_work",
            "visibility",
            "location",
            "reasons",
        ):
            with self.subTest(field=field):
                self.assertIn(field, instruction)
        self.assertIn("answer area", instruction.lower())
        self.assertIn("given item", instruction.lower())

    def test_existing_constructors_still_use_clear_defaults(self) -> None:
        read = HandwritingRead("87", "87", 0.9, "")

        self.assertEqual(read.visibility, VISIBILITY_CLEAR)
        self.assertEqual(read.location, "")
        self.assertEqual(read.reasons, ())


class HandwritingTutorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = SessionStore("sqlite:///:memory:")
        self.lesson = load_lesson(LESSON_PATH)

    def tearDown(self) -> None:
        self.store.close()

    def _selected(self, session_id: str, exercise: str = "A2") -> TutorSession:
        session = TutorSession(self.lesson, self.store, session_id)
        session.start(valid_sheet(self.lesson))
        session.choose(exercise)
        self.assertEqual(session.state, TutorState.STUDENT_WORKING)
        return session

    def test_each_uncertain_visibility_never_checks_or_counts(self) -> None:
        cases = (
            (VISIBILITY_BLANK, "write your answer and say ready"),
            (VISIBILITY_OBSCURED, "move your hand"),
            (VISIBILITY_OVERWRITTEN, "rewrite it"),
            (VISIBILITY_MULTIPLE_ANSWER, "just the answer"),
            (VISIBILITY_WRONG_ITEM, "answer space"),
        )
        for visibility, expected_phrase in cases:
            with self.subTest(visibility=visibility):
                session_id = f"visibility-{visibility}"
                session = self._selected(session_id)
                before = self.store.get(session_id)
                reading = HandwritingRead(
                    "87", "87", 0.99, "", visibility
                )

                with patch("agent.tutor.check_answer") as calculator:
                    response, result = session.check_handwriting(reading)

                self.assertIsNone(result)
                calculator.assert_not_called()
                self.assertEqual(response, uncertain_prompt(visibility))
                self.assertIn(expected_phrase, response.lower())
                after = self.store.get(session_id)
                self.assertEqual(after.attempts, before.attempts)
                self.assertIsNone(after.last_answer)
                self.assertEqual(session.state, TutorState.STUDENT_WORKING)

                retried, checked = session.check_handwriting(
                    HandwritingRead("87", "87", 0.99, "")
                )
                self.assertTrue(checked.correct)
                self.assertIn("correct", retried.lower())

    def test_missing_blank_or_low_confidence_value_is_uncertain(self) -> None:
        cases = (
            HandwritingRead("", "", 0.99, ""),
            HandwritingRead("?", None, 0.99, ""),
            HandwritingRead("87", "87", 0.4, ""),
        )
        for index, reading in enumerate(cases):
            with self.subTest(case=index):
                session_id = f"weak-{index}"
                session = self._selected(session_id)
                before = self.store.get(session_id)

                with patch("agent.tutor.check_answer") as calculator:
                    response, result = session.check_handwriting(reading)

                self.assertIsNone(result)
                calculator.assert_not_called()
                self.assertEqual(response, uncertain_prompt(VISIBILITY_CLEAR))
                self.assertEqual(
                    self.store.get(session_id).attempts, before.attempts
                )
                self.assertEqual(session.state, TutorState.STUDENT_WORKING)

    def test_clear_a2_read_checks_a2_while_b2_exists(self) -> None:
        self.assertIn("B2", {exercise.id for exercise in self.lesson.exercises})
        self.assertNotEqual(self.lesson.get("A2").answer, self.lesson.get("B2").answer)
        session = self._selected("clear-a2", "A2")

        response, result = session.check_handwriting(
            HandwritingRead("87", "87", 0.99, "63 + 24")
        )

        self.assertIsNotNone(result)
        self.assertTrue(result.correct)
        self.assertIn("correct", response.lower())
        self.assertEqual(self.store.get("clear-a2").chosen_exercise, "A2")
        self.assertEqual(self.store.get("clear-a2").attempts, 1)
        self.assertEqual(session.state, TutorState.PRAISE)

    def test_b2_answer_is_incorrect_for_the_clear_a2_read(self) -> None:
        session = self._selected("wrong-a2", "A2")
        b2_answer = str(self.lesson.get("B2").answer)

        response, result = session.check_handwriting(
            HandwritingRead(b2_answer, b2_answer, 0.99, "")
        )

        self.assertIsNotNone(result)
        self.assertFalse(result.correct)
        self.assertIn("next step", response.lower())
        self.assertEqual(self.store.get("wrong-a2").attempts, 1)
        self.assertEqual(session.state, TutorState.STUDENT_WORKING)


class ControllerCheckTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = SessionStore("sqlite:///:memory:")
        self.lesson = load_lesson(LESSON_PATH)
        self.vision = FakeVision(valid_sheet(self.lesson))
        self.intent = FakeIntent()
        self.transcriber = FakeTranscriber()
        self.controller = TutorController(
            SESSION_ID,
            lesson=self.lesson,
            store=self.store,
            vision=self.vision,
            intent=self.intent,
            transcriber=self.transcriber,
        )
        self.controller.handle_snapshot(
            JPEG_BYTES, "image/jpeg", "review"
        )
        self.choose("A2")

    def tearDown(self) -> None:
        self.store.close()

    def choose(self, exercise_id: str):
        self.intent.intent = TutorIntent(
            "CHOOSE_EXERCISE", exercise_id, None, None
        )
        return self.controller.handle_transcript(
            Transcript(exercise_id, 0.95)
        )

    def check_snapshot(self, exercise_id: str = "A2"):
        return self.controller.handle_snapshot(
            JPEG_BYTES, "image/jpeg", "check", exercise_id
        )

    def check_tool_rows(self) -> list[str]:
        return [
            row["name"]
            for row in self.store.connection.execute(
                "SELECT name FROM tool_calls WHERE session_id = ?",
                (SESSION_ID,),
            )
        ]

    def test_payload_is_the_selected_item_without_answers(self) -> None:
        self.vision.reading = HandwritingRead("87", "87", 0.99, "")

        response = self.check_snapshot("A2")

        self.assertEqual(response.status, STATUS_SPEAKING)
        payload = self.vision.readings[0]
        self.assertEqual(
            set(payload),
            {"id", "section", "item", "problem", "expression", "answer_area"},
        )
        self.assertEqual(payload["id"], "A2")
        self.assertEqual(payload["section"], "A")
        self.assertEqual(payload["item"], 2)
        self.assertEqual(payload["problem"], self.lesson.get("A2").problem)
        self.assertEqual(
            payload["expression"],
            self.lesson.get("A2").verification_expression,
        )
        self.assertEqual(
            payload["answer_area"],
            "the answer space for item A2 in section A",
        )
        self.assertNotIn("answer", payload)
        self.assertNotIn("expected_intermediate", payload)
        serialized = json.dumps(payload)
        self.assertNotIn('"answer":', serialized)
        self.assertNotIn('"expected_intermediate":', serialized)

    def test_written_words_force_one_fresh_image_even_with_a_number(self) -> None:
        cases = (
            ("CHECK_SPOKEN_ANSWER", "check my writing, it's 15"),
            ("CHECK_ANSWER", "check my writing, it's 15"),
            ("CHECK_SPOKEN_ANSWER", "is my paper right, 15"),
            ("CHECK_WRITING", "it's 15"),
        )
        for intent_name, text in cases:
            with self.subTest(intent=intent_name, text=text):
                before = self.store.get(SESSION_ID)
                self.intent.intent = TutorIntent(
                    intent_name, None, "15", None
                )

                response = self.controller.handle_transcript(
                    Transcript(text, 0.95)
                )

                self.assertEqual(response.status, STATUS_READING_WORK)
                self.assertEqual(response.capture_request, CAPTURE_CHECK)
                self.assertEqual(response.exercise_id, "A2")
                self.assertEqual(self.vision.read_calls, 0)
                self.assertNotIn("calculator.check_answer", self.check_tool_rows())
                self.assertEqual(
                    self.store.get(SESSION_ID).attempts, before.attempts
                )

    def test_uncertain_snapshot_asks_for_adjustment_and_retries(self) -> None:
        self.vision.reading = HandwritingRead(
            "", None, 0.99, "", VISIBILITY_BLANK
        )

        response = self.check_snapshot("A2")

        self.assertEqual(response.status, STATUS_ADJUST_SHEET)
        self.assertEqual(response.capture_request, CAPTURE_CHECK)
        self.assertEqual(response.exercise_id, "A2")
        self.assertEqual(
            response.tutor_text, uncertain_prompt(VISIBILITY_BLANK)
        )
        self.assertEqual(self.store.get(SESSION_ID).attempts, 0)
        self.assertEqual(
            self.store.get(SESSION_ID).chosen_exercise, "A2"
        )

        self.vision.reading = HandwritingRead("87", "87", 0.99, "")
        retried = self.check_snapshot("A2")
        self.assertEqual(retried.status, STATUS_SPEAKING)
        self.assertIsNone(retried.capture_request)
        self.assertIn("correct", retried.tutor_text.lower())
        self.assertEqual(self.store.get(SESSION_ID).attempts, 1)

    def test_wrong_item_read_asks_for_the_selected_answer_space(self) -> None:
        self.vision.reading = HandwritingRead(
            "24", "24", 0.99, "", VISIBILITY_WRONG_ITEM
        )

        response = self.check_snapshot("A2")

        self.assertEqual(response.status, STATUS_ADJUST_SHEET)
        self.assertEqual(response.capture_request, CAPTURE_CHECK)
        self.assertEqual(
            response.tutor_text, uncertain_prompt(VISIBILITY_WRONG_ITEM)
        )
        self.assertEqual(self.store.get(SESSION_ID).attempts, 0)

    def test_provider_failure_then_spoken_check_never_claims_a_read(self) -> None:
        self.vision.read_error = VisionError("provider down sk-secret")

        failed = self.check_snapshot("A2")

        self.assertEqual(failed.status, STATUS_READING_WORK)
        self.assertEqual(failed.capture_request, CAPTURE_CHECK)
        self.assertEqual(failed.exercise_id, "A2")
        self.assertNotIn("sk-secret", failed.tutor_text)
        self.assertIn("try again", failed.tutor_text.lower())
        self.assertEqual(self.store.get(SESSION_ID).chosen_exercise, "A2")
        self.assertEqual(self.store.get(SESSION_ID).attempts, 0)

        self.vision.read_error = None
        self.intent.intent = TutorIntent(
            "CHECK_SPOKEN_ANSWER", None, "87", None
        )
        spoken = self.controller.handle_transcript(
            Transcript("is 87 right", 0.95)
        )

        self.assertEqual(spoken.status, STATUS_SPEAKING)
        self.assertIsNone(spoken.capture_request)
        self.assertEqual(spoken.exercise_id, "A2")
        self.assertNotIn(
            select_response("spoken_only_fallback"), spoken.tutor_text
        )
        self.assertIn("correct", spoken.tutor_text.lower())
        self.assertNotIn("read from", spoken.tutor_text.lower())
        self.assertEqual(self.store.get(SESSION_ID).attempts, 1)
        self.assertEqual(self.vision.read_calls, 1)

    def test_genuine_spoken_check_has_no_disclaimer(self) -> None:
        self.intent.intent = TutorIntent(
            "CHECK_SPOKEN_ANSWER", None, "87", None
        )

        response = self.controller.handle_transcript(
            Transcript("is 87 right", 0.95)
        )

        self.assertNotIn(
            select_response("spoken_only_fallback"), response.tutor_text
        )
        self.assertEqual(response.status, STATUS_SPEAKING)
        self.assertIsNone(response.capture_request)
        self.assertEqual(self.vision.read_calls, 0)
        self.assertIn("calculator.check_answer", self.check_tool_rows())


class GuidedHandwritingCheckTests(unittest.TestCase):
    """A graded handwritten answer follows the same turn as a spoken one."""

    def setUp(self) -> None:
        self.store = SessionStore("sqlite:///:memory:")
        self.lesson = load_lesson(LESSON_PATH)
        self.vision = FakeVision(valid_sheet(self.lesson))
        self.intent = FakeIntent()
        self.controller = TutorController(
            SESSION_ID,
            lesson=self.lesson,
            store=self.store,
            vision=self.vision,
            intent=self.intent,
            transcriber=FakeTranscriber(),
            flow_mode="guided",
        )
        reviewed = self.controller.handle_snapshot(
            JPEG_BYTES, "image/jpeg", "review"
        )
        self.assertEqual(reviewed.exercise_id, "A1")

    def tearDown(self) -> None:
        self.store.close()

    def check_snapshot(self, exercise_id: str = "A1"):
        return self.controller.handle_snapshot(
            JPEG_BYTES, "image/jpeg", "check", exercise_id
        )

    def test_guided_correct_handwriting_auto_advances_to_a2(self) -> None:
        self.vision.reading = HandwritingRead("15", "15", 0.99, "4 + 5 + 6")

        response = self.check_snapshot("A1")

        self.assertEqual(response.status, STATUS_SPEAKING)
        self.assertIsNone(response.capture_request)
        self.assertEqual(response.exercise_id, "A2")
        self.assertIn("A2", response.tutor_text)
        self.assertIn("63 + 24", response.tutor_text)
        self.assertNotIn(
            select_response("stay_on_exercise"), response.tutor_text
        )
        state = self.store.get(SESSION_ID)
        self.assertEqual(state.chosen_exercise, "A2")
        self.assertEqual(self.controller.tutor.state, TutorState.STUDENT_WORKING)

    def test_guided_wrong_handwriting_stays_on_a1_and_hints(self) -> None:
        self.vision.reading = HandwritingRead("7", "7", 0.99, "4 + 5")

        response = self.check_snapshot("A1")

        self.assertEqual(response.status, STATUS_SPEAKING)
        self.assertEqual(response.exercise_id, "A1")
        self.assertIn(
            self.lesson.get("A1").steps[0].hints[0], response.tutor_text
        )
        state = self.store.get(SESSION_ID)
        self.assertEqual(state.chosen_exercise, "A1")
        self.assertEqual(state.attempts, 1)
        self.assertEqual(self.controller.tutor.state, TutorState.STUDENT_WORKING)


class ChoiceHandwritingCheckTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = SessionStore("sqlite:///:memory:")
        self.lesson = load_lesson(LESSON_PATH)
        self.vision = FakeVision(valid_sheet(self.lesson))
        self.intent = FakeIntent()
        self.controller = TutorController(
            SESSION_ID,
            lesson=self.lesson,
            store=self.store,
            vision=self.vision,
            intent=self.intent,
            transcriber=FakeTranscriber(),
            flow_mode="choice",
        )
        self.controller.handle_snapshot(JPEG_BYTES, "image/jpeg", "review")
        self.intent.intent = TutorIntent(
            "CHOOSE_EXERCISE", "A1", None, None
        )
        chosen = self.controller.handle_transcript(Transcript("A1", 0.95))
        self.assertEqual(chosen.exercise_id, "A1")

    def tearDown(self) -> None:
        self.store.close()

    def test_choice_mode_correct_handwriting_keeps_praise(self) -> None:
        self.vision.reading = HandwritingRead("15", "15", 0.99, "4 + 5 + 6")

        response = self.controller.handle_snapshot(
            JPEG_BYTES, "image/jpeg", "check", "A1"
        )

        self.assertEqual(response.status, STATUS_SPEAKING)
        self.assertEqual(response.exercise_id, "A1")
        self.assertIn("correct", response.tutor_text.lower())
        self.assertNotIn("Next is", response.tutor_text)
        self.assertEqual(self.store.get(SESSION_ID).chosen_exercise, "A1")
        self.assertEqual(self.controller.tutor.state, TutorState.PRAISE)


if __name__ == "__main__":
    unittest.main()
