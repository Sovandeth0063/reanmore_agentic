"""API tests for the snapshot session, speech-turn, and snapshot endpoints."""

import asyncio
import io
import os
import re
import threading
import time
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
from PIL import Image

from agent.config import Settings
from agent.controller import TutorController
from agent.lesson import load_lesson
from agent.llm import IntentError, TutorIntent
from agent.memory import SessionStore
from agent.responses import placement_prompt, select_response
from agent.sheet_layout import load_layout
from agent.stt import STTError, Transcript
from agent.tutor import TutorState
from agent.vision import (
    PLACEMENT_DIFFERENT_SHEET,
    PLACEMENT_MISSING,
    PLACEMENT_PARTIAL,
    PLACEMENT_UNREADABLE,
    VISIBILITY_BLANK,
    AnswerArea,
    HandwritingRead,
    ParsedItem,
    VisionError,
    WorksheetParse,
)
from server.contract import (
    JPEG_MAGIC,
    MAX_AUDIO_BYTES,
    MAX_IMAGE_BYTES,
)
from server.session_api import SessionRegistry, create_app

LESSON_PATH = (
    Path(__file__).parents[1] / "agent" / "lessons" / "grade3_demo.yaml"
)


def _valid_jpeg() -> bytes:
    """A decodable stand-in photo; the controller crops it for real."""
    buffer = io.BytesIO()
    Image.new("RGB", (320, 428), (250, 250, 250)).save(
        buffer, format="JPEG", quality=90
    )
    return buffer.getvalue()


VALID_JPEG = _valid_jpeg()
SHEET_CORNERS = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))
AUDIO_BYTES = b"\x00\x00" * 160


def valid_parse(lesson) -> WorksheetParse:
    return WorksheetParse(
        items=[
            ParsedItem(
                item=exercise.id,
                section=exercise.section,
                problem=exercise.problem,
                expression=exercise.verification_expression,
            )
            for exercise in lesson.exercises
        ],
        confidence=0.95,
    )


def bad_parse() -> WorksheetParse:
    return WorksheetParse(items=[], confidence=0.1)


class FakeTranscriber:
    def __init__(self) -> None:
        self.transcript = Transcript("review my worksheet", 0.95)
        self.error = None
        self.calls = 0

    def transcribe(self, samples):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.transcript


class FakeIntent:
    def __init__(self) -> None:
        self.intent = TutorIntent("REVIEW", None, None, None)
        self.error = None
        self.calls = []

    def interpret(self, transcript, state, exercise):
        self.calls.append((transcript, state, exercise))
        if self.error is not None:
            raise self.error
        return self.intent


class FakeVision:
    def __init__(self, lesson) -> None:
        self.worksheet = valid_parse(lesson)
        self.reading = None
        self.area = None
        self.layout = load_layout()
        self.parse_error = None
        self.locate_error = None
        self.read_error = None
        self.parse_calls = 0
        self.locate_calls = 0
        self.read_calls = 0

    def parse_worksheet(self, image):
        self.parse_calls += 1
        if self.parse_error is not None:
            raise self.parse_error
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
        if self.read_error is not None:
            raise self.read_error
        return self.reading


class SessionApiTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.store = SessionStore("sqlite:///:memory:")
        self.lesson = load_lesson(LESSON_PATH)
        self.transcriber = FakeTranscriber()
        self.intent = FakeIntent()
        self.vision = FakeVision(self.lesson)
        self.app = self._build_app()
        # Keep one TestClient portal/event loop for the whole test so the
        # per-session asyncio.Lock is acquired on a stable loop.
        self._client_context = TestClient(self.app)
        self.client = self._client_context.__enter__()

    def tearDown(self) -> None:
        self._client_context.__exit__(None, None, None)
        self.store.close()

    def _factory(self, session_id):
        return TutorController(
            session_id,
            lesson=self.lesson,
            store=self.store,
            vision=self.vision,
            intent=self.intent,
            transcriber=self.transcriber,
        )

    def _build_app(self):
        return create_app(
            store=self.store,
            lesson=self.lesson,
            controller_factory=self._factory,
        )

    def create(self, **kwargs):
        return self.client.post("/sessions", **kwargs)

    def create_session(self) -> str:
        response = self.create()
        self.assertEqual(response.status_code, 200)
        return response.json()["session_id"]

    def turn(self, session_id, data=AUDIO_BYTES, content_type="audio/l16"):
        return self.client.post(
            f"/sessions/{session_id}/turn",
            files={"audio": ("turn.raw", data, content_type)},
        )

    def snapshot(
        self,
        session_id,
        purpose,
        image=VALID_JPEG,
        content_type="image/jpeg",
        exercise_id=None,
    ):
        form = {"purpose": purpose}
        if exercise_id is not None:
            form["exercise_id"] = exercise_id
        return self.client.post(
            f"/sessions/{session_id}/snapshot",
            data=form,
            files={"image": ("sheet.jpg", image, content_type)},
        )

    def set_turn(self, text, intent, confidence=0.95) -> None:
        self.transcriber.transcript = Transcript(text, confidence)
        self.intent.intent = intent

    def place_worksheet(self, session_id):
        self.set_turn(
            "review my worksheet", TutorIntent("REVIEW", None, None, None)
        )
        asking = self.turn(session_id)
        self.assertEqual(asking.status_code, 200)
        self.assertEqual(asking.json()["capture_request"], "review")
        review = self.snapshot(session_id, "review")
        self.assertEqual(review.status_code, 200)
        return review

    def choose(self, session_id, exercise_id="A1"):
        self.set_turn(
            exercise_id,
            TutorIntent("CHOOSE_EXERCISE", exercise_id, None, None),
        )
        return self.turn(session_id)

    def rows(self, table, session_id) -> int:
        return self.store.connection.execute(
            f"SELECT COUNT(*) FROM {table} WHERE session_id = ?",
            (session_id,),
        ).fetchone()[0]


class LifecycleTests(SessionApiTestCase):
    def test_create_turn_review_choose_check_snapshot_delete(self) -> None:
        response = self.create()
        self.assertEqual(response.status_code, 200)
        initial = response.json()
        self.assertEqual(initial["contract_version"], 1)
        self.assertEqual(initial["status"], "ready")
        self.assertEqual(
            initial["tutor_text"], "Ask me to review your worksheet."
        )
        self.assertIsNone(initial["capture_request"])
        self.assertIsNone(initial["exercise_id"])
        session_id = initial["session_id"]

        reviewed = self.place_worksheet(session_id)
        self.assertEqual(reviewed.json()["status"], "listening")
        self.assertTrue(self.store.get(session_id).placement_confirmed)

        chosen = self.choose(session_id, "A1")
        self.assertEqual(chosen.status_code, 200)
        # Choosing presents the problem: speech, not a work read, and no
        # capture is requested.
        self.assertEqual(chosen.json()["status"], "speaking")
        self.assertIsNone(chosen.json()["capture_request"])
        self.assertEqual(chosen.json()["exercise_id"], "A1")
        self.assertEqual(self.store.get(session_id).chosen_exercise, "A1")

        self.set_turn("check", TutorIntent("CHECK_ANSWER", None, None, None))
        check_request = self.turn(session_id)
        self.assertEqual(check_request.json()["status"], "reading_work")
        self.assertEqual(check_request.json()["capture_request"], "check")
        self.assertEqual(check_request.json()["exercise_id"], "A1")

        exercise = self.lesson.get("A1")
        self.vision.reading = HandwritingRead(
            raw_text=str(exercise.answer),
            value=str(exercise.answer),
            confidence=0.95,
            visible_work=str(exercise.answer),
        )
        checked = self.snapshot(session_id, "check", exercise_id="A1")
        self.assertEqual(checked.status_code, 200)
        payload = checked.json()
        self.assertEqual(payload["status"], "speaking")
        self.assertEqual(payload["exercise_id"], "A1")
        self.assertIn("correct", payload["tutor_text"])

        tool_names = [
            row["name"]
            for row in self.store.connection.execute(
                "SELECT name FROM tool_calls WHERE session_id = ?",
                (session_id,),
            )
        ]
        for name in (
            "stt.transcribe",
            "ollama.interpret",
            "vision.parse_worksheet",
            "vision.read_handwriting",
        ):
            self.assertIn(name, tool_names)

        ended = self.client.delete(f"/sessions/{session_id}")
        self.assertEqual(ended.status_code, 200)
        self.assertEqual(
            ended.json(),
            {
                "contract_version": 1,
                "session_id": session_id,
                "ended": True,
            },
        )
        self.assertIsNone(self.store.get(session_id))
        self.assertEqual(self.rows("turns", session_id), 0)
        self.assertEqual(self.rows("tool_calls", session_id), 0)


class PlacementTests(SessionApiTestCase):
    def ask_for_review(self, session_id) -> None:
        self.set_turn(
            "review my worksheet", TutorIntent("REVIEW", None, None, None)
        )
        asking = self.turn(session_id)
        self.assertEqual(asking.status_code, 200)
        self.assertEqual(asking.json()["capture_request"], "review")

    def test_unreadable_parse_returns_adjust_sheet_and_retry_works(self) -> None:
        session_id = self.create_session()
        self.ask_for_review(session_id)
        self.vision.worksheet = bad_parse()

        bad = self.snapshot(session_id, "review")
        self.assertEqual(bad.status_code, 200)
        payload = bad.json()
        self.assertEqual(payload["status"], "adjust_sheet")
        self.assertEqual(payload["capture_request"], "review")
        self.assertEqual(
            payload["tutor_text"],
            placement_prompt(PLACEMENT_UNREADABLE),
        )
        state = self.store.get(session_id)
        self.assertFalse(state.placement_confirmed)
        self.assertEqual(state.turns, ())
        self.assertEqual(
            self._factory(session_id).tutor.state,
            TutorState.WAITING_FOR_PLACEMENT,
        )

        self.vision.worksheet = valid_parse(self.lesson)
        retried = self.snapshot(session_id, "review")
        self.assertEqual(retried.json()["status"], "listening")
        self.assertTrue(self.store.get(session_id).placement_confirmed)

    def test_each_placement_status_returns_its_specific_prompt(self) -> None:
        base = valid_parse(self.lesson)
        wrong = list(base.items)
        wrong[0] = ParsedItem(
            wrong[0].item,
            wrong[0].section,
            wrong[0].problem,
            "9 + 9",
        )
        cases = [
            (PLACEMENT_MISSING, replace(base, items=[])),
            (PLACEMENT_PARTIAL, replace(base, items=base.items[:-1])),
            (PLACEMENT_UNREADABLE, replace(base, confidence=0.2)),
            (PLACEMENT_DIFFERENT_SHEET, replace(base, items=wrong)),
            (
                PLACEMENT_DIFFERENT_SHEET,
                replace(base, placement=PLACEMENT_DIFFERENT_SHEET),
            ),
        ]
        for index, (status, worksheet) in enumerate(cases):
            with self.subTest(status=status, case=index):
                session_id = self.create_session()
                self.ask_for_review(session_id)
                self.vision.worksheet = worksheet

                response = self.snapshot(session_id, "review")

                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertEqual(payload["status"], "adjust_sheet")
                self.assertEqual(payload["capture_request"], "review")
                self.assertEqual(
                    payload["tutor_text"], placement_prompt(status)
                )
                self.assertFalse(
                    self.store.get(session_id).placement_confirmed
                )
                self.assertEqual(self.store.get(session_id).turns, ())

    def test_ready_review_summarizes_sections_without_naming_ids(self) -> None:
        session_id = self.create_session()

        reviewed = self.place_worksheet(session_id)

        payload = reviewed.json()
        self.assertEqual(payload["status"], "listening")
        self.assertEqual(
            payload["tutor_text"],
            select_response("worksheet_summary")
            + " "
            + select_response("ask_choice"),
        )
        self.assertIn("addition and subtraction", payload["tutor_text"])
        self.assertIn("multiplication and division", payload["tutor_text"])
        for exercise in self.lesson.exercises:
            with self.subTest(exercise=exercise.id):
                self.assertNotIn(exercise.id, payload["tutor_text"])
        self.assertTrue(self.store.get(session_id).placement_confirmed)

    def test_choice_before_review_is_blocked(self) -> None:
        session_id = self.create_session()

        response = self.choose(session_id, "A1")

        self.assertEqual(response.json()["status"], "adjust_sheet")
        self.assertEqual(response.json()["capture_request"], "review")
        self.assertEqual(
            response.json()["tutor_text"],
            placement_prompt(PLACEMENT_MISSING),
        )
        self.assertIsNone(self.store.get(session_id).chosen_exercise)

    def test_list_worksheet_before_placement_returns_the_retry(self) -> None:
        session_id = self.create_session()
        self.set_turn(
            "which exercises are there",
            TutorIntent("LIST_WORKSHEET", None, None, None),
        )

        response = self.turn(session_id)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "adjust_sheet")
        self.assertEqual(payload["capture_request"], "review")
        self.assertEqual(
            payload["tutor_text"], placement_prompt(PLACEMENT_MISSING)
        )
        for exercise in self.lesson.exercises:
            self.assertNotIn(exercise.id, payload["tutor_text"])
        self.assertFalse(self.store.get(session_id).placement_confirmed)

    def test_next_before_placement_returns_the_retry(self) -> None:
        session_id = self.create_session()
        self.set_turn("next", TutorIntent("NEXT", None, None, None))

        response = self.turn(session_id)

        self.assertEqual(response.json()["status"], "adjust_sheet")
        self.assertEqual(
            response.json()["tutor_text"],
            placement_prompt(PLACEMENT_MISSING),
        )
        self.assertIsNone(self.store.get(session_id).chosen_exercise)

    def test_bad_review_during_exercise_keeps_check_usable(self) -> None:
        session_id = self.create_session()
        self.place_worksheet(session_id)
        self.choose(session_id, "A1")
        self.vision.worksheet = replace(
            valid_parse(self.lesson), confidence=0.2
        )

        review = self.snapshot(session_id, "review")

        self.assertEqual(review.status_code, 200)
        payload = review.json()
        self.assertEqual(payload["status"], "adjust_sheet")
        self.assertEqual(payload["capture_request"], "review")
        self.assertEqual(
            payload["tutor_text"], placement_prompt(PLACEMENT_UNREADABLE)
        )
        # The failed re-review must not unset the active exercise.
        self.assertEqual(self.store.get(session_id).chosen_exercise, "A1")

        self.set_turn("15", TutorIntent("CHECK_ANSWER", None, "15", None))
        checked = self.turn(session_id)

        self.assertEqual(checked.status_code, 200)
        self.assertEqual(checked.json()["status"], "speaking")
        self.assertEqual(checked.json()["exercise_id"], "A1")
        self.assertTrue(
            checked.json()["tutor_text"].startswith(
                select_response("spoken_only_fallback") + " "
            )
        )
        self.assertIn("correct", checked.json()["tutor_text"].lower())

    def test_valid_review_during_exercise_returns_speaking(self) -> None:
        session_id = self.create_session()
        self.place_worksheet(session_id)
        self.choose(session_id, "A1")

        reviewed = self.snapshot(session_id, "review")

        self.assertEqual(reviewed.status_code, 200)
        payload = reviewed.json()
        self.assertEqual(payload["status"], "speaking")
        self.assertEqual(payload["exercise_id"], "A1")
        self.assertIsNone(payload["capture_request"])
        self.assertIn(
            self.lesson.get("A1").problem, payload["tutor_text"]
        )

    def test_retake_after_a_poor_photo_reaches_choice_on_the_same_session(
        self,
    ) -> None:
        session_id = self.create_session()
        self.ask_for_review(session_id)
        self.vision.worksheet = replace(
            valid_parse(self.lesson), placement=PLACEMENT_PARTIAL
        )

        poor = self.snapshot(session_id, "review")
        self.assertEqual(poor.json()["status"], "adjust_sheet")
        self.assertEqual(
            poor.json()["tutor_text"], placement_prompt(PLACEMENT_PARTIAL)
        )

        self.vision.worksheet = valid_parse(self.lesson)
        retaken = self.snapshot(session_id, "review")
        self.assertEqual(retaken.json()["status"], "listening")
        self.assertIn("addition and subtraction", retaken.json()["tutor_text"])
        self.assertTrue(self.store.get(session_id).placement_confirmed)

        chosen = self.choose(session_id, "A1")

        self.assertEqual(chosen.json()["status"], "speaking")
        self.assertEqual(chosen.json()["exercise_id"], "A1")
        self.assertEqual(self.store.get(session_id).chosen_exercise, "A1")

    def test_review_provider_failure_keeps_placement_retryable(self) -> None:
        session_id = self.create_session()
        self.vision.parse_error = VisionError("provider key sk-secret")

        failed = self.snapshot(session_id, "review")
        self.assertEqual(failed.status_code, 200)
        payload = failed.json()
        self.assertEqual(payload["status"], "adjust_sheet")
        self.assertEqual(payload["capture_request"], "review")
        self.assertIn("try again", payload["tutor_text"].lower())
        self.assertNotIn("sk-secret", failed.text)
        self.assertNotIn("I can see the worksheet", payload["tutor_text"])
        state = self.store.get(session_id)
        self.assertFalse(state.placement_confirmed)
        self.assertEqual(state.turns, ())

        self.vision.parse_error = None
        retried = self.snapshot(session_id, "review")
        self.assertEqual(retried.json()["status"], "listening")
        self.assertTrue(self.store.get(session_id).placement_confirmed)


class CheckGuardTests(SessionApiTestCase):
    def test_check_snapshot_requires_selected_exercise(self) -> None:
        session_id = self.create_session()
        self.snapshot(session_id, "review")

        response = self.snapshot(session_id, "check")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json()["error"]["code"], "not_allowed_in_state"
        )

    def test_check_snapshot_rejects_other_exercise_id(self) -> None:
        session_id = self.create_session()
        self.place_worksheet(session_id)
        self.choose(session_id, "A1")
        before = self.store.get(session_id)

        response = self.snapshot(session_id, "check", exercise_id="A2")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "invalid_request")
        after = self.store.get(session_id)
        self.assertEqual(after.chosen_exercise, "A1")
        self.assertEqual(after.current_step, before.current_step)

    def test_check_provider_failure_is_retryable(self) -> None:
        session_id = self.create_session()
        self.place_worksheet(session_id)
        self.choose(session_id, "A1")
        self.vision.read_error = VisionError("provider key sk-secret")

        failed = self.snapshot(session_id, "check")
        self.assertEqual(failed.status_code, 200)
        payload = failed.json()
        self.assertEqual(payload["status"], "reading_work")
        self.assertEqual(payload["capture_request"], "check")
        self.assertEqual(payload["exercise_id"], "A1")
        self.assertNotIn("sk-secret", failed.text)
        self.assertEqual(self.store.get(session_id).chosen_exercise, "A1")

        exercise = self.lesson.get("A1")
        self.vision.read_error = None
        self.vision.reading = HandwritingRead(
            raw_text=str(exercise.answer),
            value=str(exercise.answer),
            confidence=0.95,
            visible_work="",
        )
        retried = self.snapshot(session_id, "check")
        self.assertEqual(retried.json()["exercise_id"], "A1")

    def test_uncertain_read_returns_adjust_sheet_and_retry_works(self) -> None:
        session_id = self.create_session()
        self.place_worksheet(session_id)
        self.choose(session_id, "A1")
        self.vision.reading = HandwritingRead(
            "", None, 0.95, "", VISIBILITY_BLANK
        )

        uncertain = self.snapshot(session_id, "check", exercise_id="A1")

        self.assertEqual(uncertain.status_code, 200)
        payload = uncertain.json()
        self.assertEqual(payload["status"], "adjust_sheet")
        self.assertEqual(payload["capture_request"], "check")
        self.assertEqual(payload["exercise_id"], "A1")
        self.assertEqual(
            payload["tutor_text"],
            select_response("reading_blank"),
        )
        state = self.store.get(session_id)
        self.assertEqual(state.chosen_exercise, "A1")
        self.assertEqual(state.attempts, 0)

        exercise = self.lesson.get("A1")
        self.vision.reading = HandwritingRead(
            str(exercise.answer),
            str(exercise.answer),
            0.95,
            "",
        )
        retried = self.snapshot(session_id, "check", exercise_id="A1")

        self.assertEqual(retried.json()["status"], "speaking")
        self.assertIsNone(retried.json()["capture_request"])
        self.assertIn("correct", retried.json()["tutor_text"].lower())
        self.assertEqual(self.store.get(session_id).attempts, 1)

    def test_spoken_check_after_failed_snapshot_is_prefixed(self) -> None:
        session_id = self.create_session()
        self.place_worksheet(session_id)
        self.choose(session_id, "A1")
        self.vision.read_error = VisionError("provider down")

        failed = self.snapshot(session_id, "check")
        self.assertEqual(failed.json()["status"], "reading_work")

        self.set_turn("is 15 right", TutorIntent("CHECK_SPOKEN_ANSWER", None, "15", None))
        spoken = self.turn(session_id)

        self.assertEqual(spoken.json()["status"], "speaking")
        self.assertIsNone(spoken.json()["capture_request"])
        self.assertTrue(
            spoken.json()["tutor_text"].startswith(
                select_response("spoken_only_fallback") + " "
            )
        )
        self.assertIn("correct", spoken.json()["tutor_text"].lower())


class FastPathTests(SessionApiTestCase):
    def tool_names(self, session_id) -> list[str]:
        return [
            row["name"]
            for row in self.store.connection.execute(
                "SELECT name FROM tool_calls WHERE session_id = ?",
                (session_id,),
            )
        ]

    def test_clear_command_records_the_fast_path_and_skips_ollama(self) -> None:
        session_id = self.create_session()
        self.place_worksheet(session_id)
        # The review request is itself a clear command.
        self.assertEqual(self.intent.calls, [])
        rows = len(self.tool_names(session_id))

        # The fake would answer REVIEW; only the fast path yields READY here.
        self.set_turn("I'm ready", TutorIntent("REVIEW", None, None, None))
        response = self.turn(session_id)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "listening")
        self.assertEqual(self.intent.calls, [])
        # The turn starts with STT, then the fast path replaces the model call.
        self.assertEqual(
            self.tool_names(session_id)[rows:],
            ["stt.transcribe", "intent.fast_path"],
        )

    def test_clear_id_choice_after_placement_skips_ollama(self) -> None:
        session_id = self.create_session()
        self.place_worksheet(session_id)
        calls = len(self.intent.calls)
        rows = len(self.tool_names(session_id))

        self.set_turn(
            "section a, number 2", TutorIntent("UNCLEAR", None, None, None)
        )
        response = self.turn(session_id)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["exercise_id"], "A2")
        self.assertEqual(self.store.get(session_id).chosen_exercise, "A2")
        self.assertEqual(len(self.intent.calls), calls)
        self.assertEqual(
            self.tool_names(session_id)[rows:],
            ["stt.transcribe", "intent.fast_path"],
        )

    def test_conversational_turn_still_reaches_ollama(self) -> None:
        session_id = self.create_session()
        self.place_worksheet(session_id)
        calls = len(self.intent.calls)
        rows = len(self.tool_names(session_id))

        self.set_turn(
            "can you help me with this one",
            TutorIntent("OFF_TOPIC", None, None, None),
        )
        response = self.turn(session_id)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "listening")
        self.assertEqual(len(self.intent.calls), calls + 1)
        # No fast-path row: STT is followed by the model call, as before.
        self.assertEqual(
            self.tool_names(session_id)[rows:],
            ["stt.transcribe", "ollama.interpret"],
        )


class MediaValidationTests(SessionApiTestCase):
    def test_invalid_session_returns_explicit_error(self) -> None:
        responses = [
            self.turn("missing"),
            self.snapshot("missing", "review"),
            self.client.delete("/sessions/missing"),
        ]
        for response in responses:
            with self.subTest(path=response.request.url.path):
                self.assertEqual(response.status_code, 404)
                self.assertEqual(
                    response.json()["error"]["code"], "invalid_session"
                )
                self.assertNotIn(
                    "missing", response.json()["error"]["message"].lower()
                )

    def test_wrong_purpose(self) -> None:
        session_id = self.create_session()

        response = self.snapshot(session_id, "snapshot")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "wrong_purpose")

    def test_oversized_audio(self) -> None:
        session_id = self.create_session()

        response = self.turn(
            session_id, data=b"\x00" * (MAX_AUDIO_BYTES + 2)
        )

        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()["error"]["code"], "audio_too_long")

    def test_oversized_image(self) -> None:
        session_id = self.create_session()

        response = self.snapshot(
            session_id,
            "review",
            image=JPEG_MAGIC + b"\x00" * MAX_IMAGE_BYTES,
        )

        self.assertEqual(response.status_code, 413)
        self.assertEqual(
            response.json()["error"]["code"], "payload_too_large"
        )

    def test_unsupported_mime_types(self) -> None:
        session_id = self.create_session()

        audio = self.turn(session_id, content_type="audio/webm")
        self.assertEqual(audio.status_code, 415)
        self.assertEqual(
            audio.json()["error"]["code"], "unsupported_audio_format"
        )

        image = self.snapshot(session_id, "review", content_type="image/png")
        self.assertEqual(image.status_code, 415)
        self.assertEqual(
            image.json()["error"]["code"], "unsupported_image_format"
        )

    def test_empty_and_odd_audio(self) -> None:
        session_id = self.create_session()

        empty = self.turn(session_id, data=b"")
        self.assertEqual(empty.status_code, 400)
        self.assertEqual(empty.json()["error"]["code"], "empty_audio")

        odd = self.turn(session_id, data=b"\x00\x00\x00")
        self.assertEqual(odd.status_code, 400)
        self.assertEqual(odd.json()["error"]["code"], "invalid_request")

    def test_missing_fields_return_non_secret_error(self) -> None:
        session_id = self.create_session()

        missing_purpose = self.client.post(
            f"/sessions/{session_id}/snapshot",
            files={"image": ("sheet.jpg", VALID_JPEG, "image/jpeg")},
        )
        self.assertEqual(missing_purpose.status_code, 400)
        self.assertEqual(
            missing_purpose.json()["error"]["code"], "invalid_request"
        )

        missing_audio = self.client.post(f"/sessions/{session_id}/turn")
        self.assertEqual(missing_audio.status_code, 400)
        self.assertEqual(
            missing_audio.json()["error"]["code"], "invalid_request"
        )


class AudioFailureTests(SessionApiTestCase):
    def test_stt_failure_returns_service_text_and_session_survives(self) -> None:
        session_id = self.create_session()
        self.transcriber.error = STTError("model path /secret/model")

        response = self.turn(session_id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "listening")
        self.assertIn("try again", response.json()["tutor_text"].lower())
        self.assertNotIn("secret", response.text)

        self.transcriber.error = None
        self.set_turn(
            "review my worksheet", TutorIntent("REVIEW", None, None, None)
        )
        retried = self.turn(session_id)
        self.assertEqual(retried.json()["capture_request"], "review")

    def test_intent_failure_returns_service_text_and_session_survives(
        self,
    ) -> None:
        session_id = self.create_session()
        # A conversational turn still needs the classifier, so the failure is
        # reachable; a clear command would take the fast path instead.
        self.set_turn(
            "can you help me with this one",
            TutorIntent("REVIEW", None, None, None),
        )
        self.intent.error = IntentError("provider key sk-secret")

        response = self.turn(session_id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "listening")
        self.assertNotIn("sk-secret", response.text)

        self.intent.error = None
        self.set_turn(
            "review my worksheet", TutorIntent("REVIEW", None, None, None)
        )
        retried = self.turn(session_id)
        self.assertEqual(retried.json()["capture_request"], "review")

    def test_empty_or_low_confidence_transcript_does_not_advance(self) -> None:
        session_id = self.create_session()

        for text, confidence in (("", 0.99), ("review", 0.1)):
            with self.subTest(text=text, confidence=confidence):
                self.set_turn(
                    text,
                    TutorIntent("REVIEW", None, None, None),
                    confidence,
                )
                response = self.turn(session_id)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["status"], "listening")
                self.assertIn(
                    "could not read",
                    response.json()["tutor_text"].lower(),
                )
                self.assertFalse(
                    self.store.get(session_id).placement_confirmed
                )
                self.assertEqual(self.intent.calls, [])


class SessionIdentityTests(SessionApiTestCase):
    def test_opaque_ids_and_client_answers_are_ignored(self) -> None:
        first = self.create(json={"answer": "15", "exercise_id": "A1"})
        second = self.create()
        payload = first.json()

        self.assertRegex(payload["session_id"], r"^[0-9a-f]{32}$")
        self.assertNotEqual(
            payload["session_id"], second.json()["session_id"]
        )
        self.assertIsNone(payload["exercise_id"])
        self.assertIsNone(
            self.store.get(payload["session_id"]).chosen_exercise
        )


class SessionLifetimeTests(SessionApiTestCase):
    def test_reconnect_uses_same_session_after_selection(self) -> None:
        session_id = self.create_session()
        self.place_worksheet(session_id)
        self.choose(session_id, "A1")

        app = self._build_app()
        with TestClient(app) as client:
            self.set_turn(
                "check", TutorIntent("CHECK_ANSWER", None, None, None)
            )
            response = client.post(
                f"/sessions/{session_id}/turn",
                files={"audio": ("turn.raw", AUDIO_BYTES, "audio/l16")},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["exercise_id"], "A1")
        self.assertEqual(response.json()["capture_request"], "check")

    def test_reconnect_between_review_and_choice(self) -> None:
        session_id = self.create_session()
        self.place_worksheet(session_id)

        app = self._build_app()
        with TestClient(app) as client:
            self.set_turn(
                "A2", TutorIntent("CHOOSE_EXERCISE", "A2", None, None)
            )
            response = client.post(
                f"/sessions/{session_id}/turn",
                files={"audio": ("turn.raw", AUDIO_BYTES, "audio/l16")},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["exercise_id"], "A2")

    def test_reconnect_after_confirmed_placement_restores_choice(self) -> None:
        session_id = self.create_session()
        self.place_worksheet(session_id)

        rebuilt = self._factory(session_id)

        self.assertEqual(rebuilt.tutor.state, TutorState.CHOOSE_EXERCISE)
        resumed = rebuilt.create_response()
        self.assertEqual(resumed.status, "listening")
        self.assertEqual(
            resumed.tutor_text,
            select_response("worksheet_summary")
            + " "
            + select_response("ask_choice"),
        )

    def test_rebuilt_controller_resumes_a_selected_exercise(self) -> None:
        session_id = self.create_session()
        self.place_worksheet(session_id)
        self.choose(session_id, "A2")

        # A restart loses the in-memory controller; the store survives and the
        # rebuilt controller resumes the presented exercise.
        resumed = self._factory(session_id).create_response()

        self.assertEqual(resumed.status, "speaking")
        self.assertEqual(resumed.exercise_id, "A2")
        self.assertIsNone(resumed.capture_request)

    def test_expired_session_is_pruned_on_first_use(self) -> None:
        self.store.create("expired")
        stamp = (
            datetime.now(timezone.utc) - timedelta(hours=48)
        ).isoformat()
        self.store.connection.execute(
            "UPDATE sessions SET updated_at = ? WHERE session_id = ?",
            (stamp, "expired"),
        )
        self.store.connection.commit()

        app = self._build_app()
        with TestClient(app) as client:
            self.assertEqual(client.post("/sessions").status_code, 200)

        self.assertIsNone(self.store.get("expired"))


class RegistrySerializationTests(unittest.TestCase):
    def test_run_executes_overlapping_operations_one_at_a_time(self) -> None:
        registry = SessionRegistry()
        events = []
        state = {"value": 0}

        async def operation(name):
            events.append(f"{name}:start")
            current = state["value"]
            await asyncio.sleep(0.01)
            state["value"] = current + 1
            events.append(f"{name}:end")

        async def run_together():
            await asyncio.gather(
                registry.run("session-1", operation, "first"),
                registry.run("session-1", operation, "second"),
            )

        asyncio.run(run_together())

        self.assertEqual(state["value"], 2)
        self.assertEqual(
            events,
            ["first:start", "first:end", "second:start", "second:end"],
        )

    def test_different_sessions_use_different_locks(self) -> None:
        registry = SessionRegistry()
        events = []

        async def operation(name):
            events.append(f"{name}:start")
            await asyncio.sleep(0.01)
            events.append(f"{name}:end")

        async def run_together():
            await asyncio.gather(
                registry.run("session-1", operation, "one"),
                registry.run("session-2", operation, "two"),
            )

        asyncio.run(run_together())

        self.assertEqual(events[:2], ["one:start", "two:start"])

    def test_run_prevents_lost_state_updates(self) -> None:
        registry = SessionRegistry()
        store = SessionStore("sqlite:///:memory:")
        store.create("session-1")

        async def increment():
            state = store.get("session-1")
            await asyncio.sleep(0.01)
            store.update("session-1", attempts=state.attempts + 1)

        async def run_together():
            await asyncio.gather(
                registry.run("session-1", increment),
                registry.run("session-1", increment),
            )

        try:
            asyncio.run(run_together())
            self.assertEqual(store.get("session-1").attempts, 2)
        finally:
            store.close()

    def test_run_moves_blocking_sync_operations_off_the_event_loop(
        self,
    ) -> None:
        registry = SessionRegistry()
        ticks = []

        def blocking():
            time.sleep(0.15)
            return "done"

        async def ticker() -> None:
            for _ in range(15):
                await asyncio.sleep(0.01)
                ticks.append(1)

        async def run_together():
            result, _ = await asyncio.gather(
                registry.run("session-1", blocking), ticker()
            )
            return result

        self.assertEqual(asyncio.run(run_together()), "done")
        # A synchronous operation would starve the ticker entirely.
        self.assertGreater(len(ticks), 1)

    def test_run_orders_blocking_sync_operations_for_one_session(self) -> None:
        registry = SessionRegistry()
        events = []

        def operation(name):
            events.append(f"{name}:start")
            time.sleep(0.01)
            events.append(f"{name}:end")

        async def run_together():
            await asyncio.gather(
                registry.run("session-1", operation, "first"),
                registry.run("session-1", operation, "second"),
            )

        asyncio.run(run_together())

        self.assertEqual(
            events,
            ["first:start", "first:end", "second:start", "second:end"],
        )


class BlockingTranscriber:
    """Blocks inside a worker thread until the test releases it."""

    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    def transcribe(self, samples):
        self.started.set()
        self.release.wait(5)
        return Transcript("review my worksheet", 0.95)


class TurnIsolationTests(unittest.TestCase):
    def test_blocked_turn_does_not_block_creating_another_session(self) -> None:
        store = SessionStore("sqlite:///:memory:")
        store.create("busy-session")
        lesson = load_lesson(LESSON_PATH)
        transcriber = BlockingTranscriber()
        vision = FakeVision(lesson)
        intent = FakeIntent()

        def factory(session_id):
            return TutorController(
                session_id,
                lesson=lesson,
                store=store,
                vision=vision,
                intent=intent,
                transcriber=transcriber,
            )

        app = create_app(
            store=store, lesson=lesson, controller_factory=factory
        )

        async def wait_for_start() -> None:
            while not transcriber.started.is_set():
                await asyncio.sleep(0.005)

        async def scenario():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                turn = asyncio.create_task(
                    client.post(
                        "/sessions/busy-session/turn",
                        files={
                            "audio": ("turn.raw", AUDIO_BYTES, "audio/l16")
                        },
                    )
                )
                try:
                    await asyncio.wait_for(wait_for_start(), timeout=5)
                    created = await asyncio.wait_for(
                        client.post("/sessions"), timeout=5
                    )
                    turn_was_blocked = not turn.done()
                finally:
                    transcriber.release.set()
                turn_response = await asyncio.wait_for(turn, timeout=5)
                return created, turn_was_blocked, turn_response

        try:
            created, turn_was_blocked, turn_response = asyncio.run(scenario())
        finally:
            store.close()

        self.assertTrue(turn_was_blocked)
        self.assertEqual(created.status_code, 200)
        self.assertEqual(turn_response.status_code, 200)


class SharedRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = SessionStore("sqlite:///:memory:")
        self.lesson = load_lesson(LESSON_PATH)

    def tearDown(self) -> None:
        self.store.close()

    def test_default_factory_shares_one_transcriber_and_one_client(
        self,
    ) -> None:
        clients = []

        class CountingClient:
            def __init__(self, *args, **kwargs) -> None:
                clients.append(self)
                self.closed = 0

            def close(self) -> None:
                self.closed += 1

        with patch("httpx.Client", CountingClient):
            app = create_app(
                settings=Settings(),
                store=self.store,
                lesson=self.lesson,
            )
            runtime = app.state.runtime
            runtime.ensure()
            first = runtime.controller_factory("session-one")
            second = runtime.controller_factory("session-two")

        self.assertEqual(len(clients), 1)
        self.assertIs(runtime.http, clients[0])
        self.assertIs(first.transcriber, second.transcriber)
        self.assertIs(first.transcriber, runtime.transcriber)
        self.assertIs(first.vision.http, runtime.http)
        self.assertIs(first.intent.http, runtime.http)
        self.assertIs(second.vision.http, runtime.http)
        self.assertIs(second.intent.http, runtime.http)


class RuntimeShutdownTests(unittest.TestCase):
    def test_shutdown_closes_the_runtime_client_once_and_leaves_the_store(
        self,
    ) -> None:
        lesson = load_lesson(LESSON_PATH)

        class FakeClient:
            def __init__(self) -> None:
                self.closed = 0

            def close(self) -> None:
                self.closed += 1

        class FakeStore:
            def __init__(self) -> None:
                self.closed = 0

            def prune(self) -> None:
                return None

            def close(self) -> None:
                self.closed += 1

        client = FakeClient()
        store = FakeStore()

        with patch("httpx.Client", return_value=client):
            app = create_app(
                settings=Settings(), store=store, lesson=lesson
            )
            # TestClient enters and exits the app lifespan, which owns the
            # one shared-client close.
            with TestClient(app):
                runtime = app.state.runtime
                runtime.ensure()
                self.assertIs(runtime.http, client)

        self.assertEqual(client.closed, 1)
        self.assertIsNone(runtime.http)
        self.assertIsNone(runtime.transcriber)
        runtime.close()
        self.assertEqual(client.closed, 1)
        self.assertEqual(store.closed, 0)


class IsolationTests(SessionApiTestCase):
    def test_controller_and_api_import_no_livekit(self) -> None:
        import agent.controller as controller_module
        import server.session_api as api_module

        for module in (controller_module, api_module):
            source = Path(module.__file__).read_text(encoding="utf-8")
            with self.subTest(module=module.__name__):
                self.assertIsNone(
                    re.search(
                        r"^\s*(?:from|import)\s+livekit\b",
                        source,
                        re.MULTILINE,
                    )
                )

    def test_app_runs_with_no_livekit_credentials(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            app = self._build_app()
            with TestClient(app) as client:
                response = client.post("/sessions")

        self.assertEqual(response.status_code, 200)

    def test_no_media_rows_or_files(self) -> None:
        import agent.controller as controller_module
        import server.session_api as api_module

        for module in (controller_module, api_module):
            source = Path(module.__file__).read_text(encoding="utf-8")
            for marker in (
                "open(",
                "write_bytes",
                "write_text",
                "NamedTemporaryFile",
            ):
                with self.subTest(module=module.__name__, marker=marker):
                    self.assertNotIn(marker, source)

        session_id = self.create_session()
        self.place_worksheet(session_id)
        self.choose(session_id, "A1")
        exercise = self.lesson.get("A1")
        self.vision.reading = HandwritingRead(
            raw_text=str(exercise.answer),
            value=str(exercise.answer),
            confidence=0.95,
            visible_work="",
        )
        self.snapshot(session_id, "check")

        tables = {
            row[0]
            for row in self.store.connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        self.assertFalse({"media", "images", "audio"} & tables)


if __name__ == "__main__":
    unittest.main()

