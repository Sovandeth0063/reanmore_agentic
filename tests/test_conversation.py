"""Scripted speech-only conversations for the review and step flow."""

import json
import unittest
from pathlib import Path

from agent.config import Settings
from agent.controller import TutorController
from agent.lesson import load_lesson
from agent.llm import VALID_INTENTS, OllamaClient, TutorIntent
from agent.memory import SessionStore
from agent.responses import select_response
from agent.sheet_layout import load_layout
from agent.stt import Transcript
from agent.tutor import TutorState
from agent.vision import AnswerArea, ParsedItem, WorksheetParse
from server.contract import (
    STATUS_ADJUST_SHEET,
    STATUS_CHECKING_SHEET,
    STATUS_LISTENING,
    STATUS_READY,
    STATUS_READING_WORK,
    STATUS_SPEAKING,
)

LESSON_PATH = Path(__file__).parents[1] / "agent" / "lessons" / "grade3_demo.yaml"
PROMPT_PATH = Path(__file__).parents[1] / "agent" / "prompts" / "tutor.md"
SESSION_ID = "conversation"
JPEG_BYTES = b"\xff\xd8\xff\xe0conversation-test-image"
SHEET_CORNERS = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))


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


class ScriptedTranscriber:
    def __init__(self) -> None:
        self.text = ""
        self.confidence = 0.95

    def transcribe(self, samples):
        return Transcript(self.text, self.confidence)


class ScriptedIntent:
    def __init__(self) -> None:
        self.result = TutorIntent("UNCLEAR", None, None, None)
        self.calls = []

    def interpret(self, transcript, state, exercise):
        self.calls.append((transcript, state, exercise))
        return self.result


class RecordingVision:
    def __init__(self, worksheet) -> None:
        self.worksheet = worksheet
        self.reading = None
        self.area = None
        self.layout = load_layout()
        self.locate_calls = 0
        self.parse_calls = 0
        self.read_calls = 0

    def parse_worksheet(self, image):
        self.parse_calls += 1
        return self.worksheet

    def locate_answer_area(self, image, exercise):
        self.locate_calls += 1
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
        return self.reading


class ConversationTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.store = SessionStore("sqlite:///:memory:")
        self.lesson = load_lesson(LESSON_PATH)
        self.transcriber = ScriptedTranscriber()
        self.intent = ScriptedIntent()
        self.vision = RecordingVision(valid_parse(self.lesson))
        self.controller = self.build_controller()

    def tearDown(self) -> None:
        self.store.close()

    def build_controller(self) -> TutorController:
        return TutorController(
            SESSION_ID,
            lesson=self.lesson,
            store=self.store,
            vision=self.vision,
            intent=self.intent,
            transcriber=self.transcriber,
        )

    def say(self, text, intent, confidence=0.95):
        self.transcriber.text = text
        self.transcriber.confidence = confidence
        self.intent.result = intent
        return self.controller.handle_transcript(Transcript(text, confidence))

    def tool_names(self) -> list[str]:
        return [
            row["name"]
            for row in self.store.connection.execute(
                "SELECT name FROM tool_calls WHERE session_id = ?",
                (SESSION_ID,),
            )
        ]

    def snapshot(self, purpose="review"):
        return self.controller.handle_snapshot(
            JPEG_BYTES, "image/jpeg", purpose
        )

    def place_worksheet(self):
        self.vision.worksheet = valid_parse(self.lesson)
        self.say(
            "review my worksheet", TutorIntent("REVIEW", None, None, None)
        )
        response = self.snapshot("review")
        self.assertEqual(response.status, STATUS_LISTENING)
        self.assertTrue(self.store.get(SESSION_ID).placement_confirmed)
        return response

    def choose(self, exercise_id):
        return self.say(
            exercise_id,
            TutorIntent("CHOOSE_EXERCISE", exercise_id, None, None),
        )


class SpeechFlowTests(ConversationTestCase):
    def test_review_placement_choice_step_repeat_and_checks(self) -> None:
        created = self.controller.create_response()
        self.assertEqual(created.status, STATUS_READY)
        self.assertIsNone(created.capture_request)

        # Review request: the only speech intents that ask for an image.
        asking = self.say(
            "review my worksheet", TutorIntent("REVIEW", None, None, None)
        )
        self.assertEqual(asking.status, STATUS_CHECKING_SHEET)
        self.assertEqual(asking.capture_request, "review")
        self.assertEqual(self.vision.parse_calls, 0)

        # Placement retry: an unusable photo asks for another one.
        self.vision.worksheet = None
        retry = self.snapshot("review")
        self.assertEqual(retry.status, STATUS_ADJUST_SHEET)
        self.assertEqual(retry.capture_request, "review")
        self.assertFalse(self.store.get(SESSION_ID).placement_confirmed)

        # "Ready" before placement is a review request, not a start.
        ready = self.say("ready", TutorIntent("READY", None, None, None))
        self.assertEqual(ready.status, STATUS_CHECKING_SHEET)
        self.assertEqual(ready.capture_request, "review")
        self.assertEqual(self.vision.parse_calls, 1)

        # A good retake confirms placement and summarizes the worksheet.
        self.vision.worksheet = valid_parse(self.lesson)
        summary = self.snapshot("review")
        self.assertEqual(summary.status, STATUS_LISTENING)
        self.assertIsNone(summary.capture_request)
        self.assertIn("addition and subtraction", summary.tutor_text)
        self.assertIn("multiplication and division", summary.tutor_text)
        self.assertTrue(self.store.get(SESSION_ID).placement_confirmed)
        self.assertIsNone(self.store.get(SESSION_ID).chosen_exercise)

        # A2 choice presents the fixed expression and its first step.
        chosen = self.choose("A2")
        self.assertEqual(chosen.status, STATUS_SPEAKING)
        self.assertIsNone(chosen.capture_request)
        self.assertEqual(chosen.exercise_id, "A2")
        exercise = self.lesson.get("A2")
        self.assertIn(exercise.problem, chosen.tutor_text)
        self.assertIn(exercise.steps[0].prompt, chosen.tutor_text)
        self.assertNotIn(str(exercise.answer), chosen.tutor_text)
        self.assertEqual(self.store.get(SESSION_ID).current_step, 1)

        # Ordinary speech turns never capture or call vision.
        parse_calls = self.vision.parse_calls
        read_calls = self.vision.read_calls
        asked = self.say(
            "what is the first step",
            TutorIntent("ASK_STEP", None, None, None),
        )
        self.assertEqual(asked.status, STATUS_SPEAKING)
        self.assertIsNone(asked.capture_request)
        self.assertIn(exercise.steps[0].prompt, asked.tutor_text)
        repeated = self.say(
            "say that again", TutorIntent("REPEAT", None, None, None)
        )
        self.assertIsNone(repeated.capture_request)
        self.assertIn(asked.tutor_text, repeated.tutor_text)
        self.assertEqual(self.vision.parse_calls, parse_calls)
        self.assertEqual(self.vision.read_calls, read_calls)

        # "Check my writing" always requests a fresh written-work image.
        writing = self.say(
            "check my writing",
            TutorIntent("CHECK_WRITING", None, None, None),
        )
        self.assertEqual(writing.status, STATUS_READING_WORK)
        self.assertEqual(writing.capture_request, "check")
        self.assertEqual(writing.exercise_id, "A2")

        # A spoken number uses the calculator and never requests a photo.
        spoken = self.say(
            "is 87 right",
            TutorIntent("CHECK_SPOKEN_ANSWER", None, "87", None),
        )
        self.assertEqual(spoken.status, STATUS_SPEAKING)
        self.assertIsNone(spoken.capture_request)
        self.assertEqual(spoken.exercise_id, "A2")
        self.assertTrue(
            spoken.tutor_text.startswith(
                select_response("spoken_only_fallback") + " "
            )
        )
        self.assertIn("correct", spoken.tutor_text.lower())
        self.assertEqual(self.vision.parse_calls, parse_calls)
        self.assertEqual(self.vision.read_calls, read_calls)
        self.assertEqual(self.store.get(SESSION_ID).current_step, 2)

    def test_bare_number_asks_for_section_and_leaves_state_unchanged(self) -> None:
        self.place_worksheet()
        before = self.store.get(SESSION_ID)

        response = self.say(
            "number two",
            TutorIntent("CHOOSE_EXERCISE", None, None, None, None, 2),
        )

        after = self.store.get(SESSION_ID)
        self.assertEqual(response.tutor_text, select_response("ask_section"))
        self.assertEqual(response.status, STATUS_SPEAKING)
        self.assertIsNone(response.exercise_id)
        self.assertIsNone(after.chosen_exercise)
        self.assertIsNone(after.current_step)
        self.assertEqual(after.placement_confirmed, before.placement_confirmed)
        self.assertEqual(self.controller.tutor.state, TutorState.CHOOSE_EXERCISE)

    def test_section_and_number_slots_select_the_exercise(self) -> None:
        self.place_worksheet()

        # Extra words keep this on the model path so the Task 24 section and
        # number slots stay covered; a bare "section A, number two" is now a
        # parser hit.
        response = self.say(
            "section A, number two please",
            TutorIntent("CHOOSE_EXERCISE", None, None, None, "A", 2),
        )

        self.assertEqual(response.exercise_id, "A2")
        self.assertIsNone(response.capture_request)
        self.assertIn(self.lesson.get("A2").steps[0].prompt, response.tutor_text)

    def test_ask_step_without_an_exercise_is_placement_gated(self) -> None:
        before = self.store.get(SESSION_ID)

        response = self.say(
            "what is the first step",
            TutorIntent("ASK_STEP", None, None, None),
        )

        self.assertEqual(response.status, STATUS_ADJUST_SHEET)
        self.assertEqual(response.capture_request, "review")
        self.assertFalse(self.store.get(SESSION_ID).placement_confirmed)
        self.assertEqual(self.store.get(SESSION_ID).turns, before.turns)

        self.place_worksheet()
        summary = self.say(
            "what is the first step",
            TutorIntent("ASK_STEP", None, None, None),
        )
        self.assertEqual(summary.status, STATUS_LISTENING)
        self.assertIsNone(summary.capture_request)
        self.assertIn("addition and subtraction", summary.tutor_text)
        self.assertIsNone(self.store.get(SESSION_ID).chosen_exercise)

    def test_next_and_done_remain_valid_and_never_capture(self) -> None:
        self.place_worksheet()
        self.choose("A1")

        offered = self.say("next", TutorIntent("NEXT", None, None, None))
        self.assertEqual(offered.tutor_text, select_response("ask_choice"))
        self.assertIsNone(offered.capture_request)

        wrapped = self.say("I am done", TutorIntent("DONE", None, None, None))
        self.assertEqual(wrapped.tutor_text, select_response("wrap_up"))
        self.assertIsNone(wrapped.capture_request)

    def test_ready_after_placement_offers_choice_then_next_step(self) -> None:
        self.place_worksheet()

        ready = self.say("ready", TutorIntent("READY", None, None, None))
        self.assertEqual(ready.status, STATUS_LISTENING)
        self.assertIsNone(ready.capture_request)
        self.assertIn("addition and subtraction", ready.tutor_text)

        self.choose("A1")
        ready_again = self.say(
            "ready", TutorIntent("READY", None, None, None)
        )
        self.assertIsNone(ready_again.capture_request)
        self.assertEqual(ready_again.exercise_id, "A1")
        self.assertEqual(
            ready_again.tutor_text,
            select_response("ready_with_exercise"),
        )


class FastPathTests(ConversationTestCase):
    def test_clear_command_skips_the_model_and_is_recorded(self) -> None:
        self.place_worksheet()
        calls = len(self.intent.calls)
        rows = len(self.tool_names())

        response = self.say(
            "say that again", TutorIntent("REPEAT", None, None, None)
        )

        self.assertEqual(len(self.intent.calls), calls)
        self.assertEqual(self.tool_names()[rows:], ["intent.fast_path"])
        self.assertEqual(response.status, STATUS_SPEAKING)
        self.assertIsNone(response.capture_request)
        row = self.store.connection.execute(
            "SELECT details, duration_ms FROM tool_calls "
            "WHERE session_id = ? AND name = 'intent.fast_path'",
            (SESSION_ID,),
        ).fetchone()
        self.assertEqual(row["details"], "")
        self.assertIsNotNone(row["duration_ms"])

    def test_conversational_turn_still_reaches_the_model(self) -> None:
        self.place_worksheet()
        self.choose("A1")
        calls = len(self.intent.calls)

        response = self.say(
            "can you help me with this problem",
            TutorIntent("OFF_TOPIC", None, None, None),
        )

        self.assertEqual(len(self.intent.calls), calls + 1)
        self.assertIn("ollama.interpret", self.tool_names())
        self.assertEqual(response.status, STATUS_LISTENING)
        self.assertIsNone(response.capture_request)

    def test_low_confidence_clear_command_uses_neither_path(self) -> None:
        self.place_worksheet()
        calls = len(self.intent.calls)
        rows = len(self.tool_names())

        response = self.say(
            "ready", TutorIntent("READY", None, None, None), confidence=0.1
        )

        self.assertEqual(response.tutor_text, select_response("unclear"))
        self.assertEqual(response.status, STATUS_LISTENING)
        self.assertEqual(len(self.intent.calls), calls)
        self.assertEqual(len(self.tool_names()), rows)

    def test_clear_exercise_id_before_placement_still_asks_for_the_sheet(
        self,
    ) -> None:
        calls = len(self.intent.calls)
        rows = len(self.tool_names())

        response = self.choose("A2")

        self.assertEqual(response.status, STATUS_ADJUST_SHEET)
        self.assertEqual(response.capture_request, "review")
        self.assertIsNone(self.store.get(SESSION_ID).chosen_exercise)
        # Before placement the id is not a clear choice: it reaches the model
        # and the placement gate answers, exactly as before the fast path.
        self.assertEqual(len(self.intent.calls), calls + 1)
        self.assertEqual(self.tool_names()[rows:], ["ollama.interpret"])

    def test_check_my_writing_with_a_spoken_number_still_needs_an_image(
        self,
    ) -> None:
        self.place_worksheet()
        self.choose("A1")
        attempts = self.store.get(SESSION_ID).attempts
        rows = len(self.tool_names())

        response = self.say(
            "check my writing, it's 15",
            TutorIntent("CHECK_SPOKEN_ANSWER", None, "15", None),
        )

        self.assertEqual(response.status, STATUS_READING_WORK)
        self.assertEqual(response.capture_request, "check")
        self.assertEqual(response.exercise_id, "A1")
        self.assertEqual(self.vision.read_calls, 0)
        self.assertEqual(self.store.get(SESSION_ID).attempts, attempts)
        self.assertEqual(self.tool_names()[rows:], ["intent.fast_path"])


class GateTests(ConversationTestCase):
    def test_off_topic_and_unknown_intents_cannot_bypass_placement(self) -> None:
        for intent in (
            TutorIntent("OFF_TOPIC", "A1", None, None),
            TutorIntent("UNCLEAR", "B2", None, None),
            TutorIntent("HINT", "A1", None, None),
        ):
            with self.subTest(intent=intent.intent):
                response = self.say("not math", intent)
                state = self.store.get(SESSION_ID)
                self.assertEqual(response.status, STATUS_LISTENING)
                self.assertIsNone(response.capture_request)
                self.assertIsNone(state.chosen_exercise)
                self.assertFalse(state.placement_confirmed)
                self.assertEqual(
                    self.controller.tutor.state,
                    TutorState.WAITING_FOR_PLACEMENT,
                )

    def test_choice_before_placement_stays_in_the_gate(self) -> None:
        response = self.choose("A1")

        self.assertEqual(response.status, STATUS_ADJUST_SHEET)
        self.assertEqual(response.capture_request, "review")
        self.assertIsNone(self.store.get(SESSION_ID).chosen_exercise)
        self.assertFalse(self.store.get(SESSION_ID).placement_confirmed)

    def test_written_work_needs_an_exercise(self) -> None:
        from server.contract import ContractError

        self.place_worksheet()

        with self.assertRaises(ContractError) as raised:
            self.say(
                "check my paper",
                TutorIntent("CHECK_WRITING", None, None, None),
            )

        self.assertEqual(raised.exception.status_code, 409)
        self.assertIsNone(self.store.get(SESSION_ID).chosen_exercise)

    def test_written_work_with_a_candidate_still_needs_an_image(self) -> None:
        self.place_worksheet()
        self.choose("A1")

        response = self.say(
            "check my writing, I wrote 15",
            TutorIntent("CHECK_WRITING", "A1", "15", None),
        )

        self.assertEqual(response.status, STATUS_READING_WORK)
        self.assertEqual(response.capture_request, "check")
        self.assertEqual(self.vision.read_calls, 0)


class IntentPayloadTests(ConversationTestCase):
    def test_intent_payload_has_no_answer_or_intermediate(self) -> None:
        self.place_worksheet()
        self.choose("A1")
        # A conversational turn is the one that still reaches the classifier.
        self.say(
            "can you help me solve this one",
            TutorIntent("ASK_STEP", None, None, None),
        )

        self.assertTrue(self.intent.calls)
        for _, _, payload in self.intent.calls:
            if not payload:
                continue
            self.assertEqual(set(payload), {"id", "problem", "steps"})
            self.assertEqual(payload["id"], "A1")
            self.assertEqual(
                payload["problem"], self.lesson.get("A1").problem
            )
            self.assertTrue(payload["steps"])
            for step in payload["steps"]:
                self.assertEqual(set(step), {"index", "prompt"})
            serialized = json.dumps(payload)
            self.assertNotIn("answer", serialized)
            self.assertNotIn("expected_intermediate", serialized)


class AliasTests(ConversationTestCase):
    def test_choose_and_check_answer_aliases_route_like_the_new_names(self) -> None:
        self.place_worksheet()

        chosen = self.say(
            "choose A1", TutorIntent("CHOOSE", "A1", None, None)
        )
        self.assertEqual(chosen.exercise_id, "A1")
        self.assertEqual(self.store.get(SESSION_ID).chosen_exercise, "A1")

        writing = self.say(
            "check", TutorIntent("CHECK_ANSWER", None, None, None)
        )
        self.assertEqual(writing.status, STATUS_READING_WORK)
        self.assertEqual(writing.capture_request, "check")

        spoken = self.say(
            "fifteen", TutorIntent("CHECK_ANSWER", None, "15", None)
        )
        self.assertEqual(spoken.status, STATUS_SPEAKING)
        self.assertIsNone(spoken.capture_request)
        self.assertTrue(
            spoken.tutor_text.startswith(
                select_response("spoken_only_fallback") + " "
            )
        )
        self.assertIn("correct", spoken.tutor_text.lower())


class AliasParserTests(unittest.TestCase):
    def settings(self) -> Settings:
        return Settings(
            ollama_model="model",
        )

    def interpret(self, content):
        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {"message": {"content": json.dumps(content)}}

        class FakeHttp:
            def post(self, *args, **kwargs):
                return FakeResponse()

        return OllamaClient(self.settings(), FakeHttp()).interpret(
            "check", {}, {"steps": []}
        )

    def test_aliases_normalize(self) -> None:
        cases = [
            ({"intent": "CHOOSE", "exercise_id": "A2"}, "CHOOSE_EXERCISE"),
            (
                {"intent": "CHECK_ANSWER", "candidate_answer": "15"},
                "CHECK_SPOKEN_ANSWER",
            ),
            ({"intent": "CHECK_ANSWER"}, "CHECK_WRITING"),
        ]
        for content, expected in cases:
            with self.subTest(content=content):
                self.assertEqual(self.interpret(content).intent, expected)


class PromptTests(unittest.TestCase):
    def test_prompt_file_lists_the_canonical_vocabulary(self) -> None:
        text = PROMPT_PATH.read_text(encoding="utf-8")

        for name in VALID_INTENTS:
            with self.subTest(intent=name):
                self.assertIn(name, text)
        self.assertIn("section", text)
        self.assertIn("number", text)
        self.assertIn("never state an unverified number", text.lower())
        self.assertIn("return json only", text.lower())


class ReconnectTests(ConversationTestCase):
    def test_correct_answer_advances_the_step_for_a_rebuilt_controller(self) -> None:
        self.place_worksheet()
        self.choose("A1")
        exercise = self.lesson.get("A1")

        first = self.say(
            "is 15 right",
            TutorIntent("CHECK_SPOKEN_ANSWER", None, "15", None),
        )
        self.assertTrue(
            first.tutor_text.startswith(
                select_response("spoken_only_fallback") + " "
            )
        )
        self.assertIn("correct", first.tutor_text.lower())
        self.assertEqual(self.store.get(SESSION_ID).current_step, 2)

        rebuilt = self.build_controller()
        resumed = rebuilt.create_response()

        self.assertEqual(resumed.status, STATUS_SPEAKING)
        self.assertEqual(resumed.exercise_id, "A1")
        self.assertIsNone(resumed.capture_request)
        self.assertIn(exercise.problem, resumed.tutor_text)
        self.assertIn(exercise.steps[1].prompt, resumed.tutor_text)
        self.assertNotIn(exercise.steps[0].prompt, resumed.tutor_text)


if __name__ == "__main__":
    unittest.main()
