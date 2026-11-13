"""Unit tests for controller rendering, the guided flow, and help intents.

The controller is driven directly (no HTTP) with fake providers. Every test
uses the real lesson, calculator, tutor state machine, and response catalog so
the number guards are exercised against the authored worksheet.
"""

import unittest
from pathlib import Path

from agent.controller import TutorController
from agent.lesson import load_lesson
from agent.llm import TutorIntent
from agent.memory import SessionStore
from agent.render import RenderResult, TemplateRenderer
from agent.responses import placement_prompt, select_response
from agent.stt import Transcript
from agent.tutor import TutorState
from agent.vision import PLACEMENT_MISSING, ParsedItem, WorksheetParse
from server.contract import ContractError

LESSON_PATH = (
    Path(__file__).parents[1] / "agent" / "lessons" / "grade3_demo.yaml"
)
SESSION_ID = "controller-test"
JPEG_BYTES = b"\xff\xd8\xff\xe0controller-test-image"


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


class FakeVision:
    def __init__(self, lesson) -> None:
        self.worksheet = valid_parse(lesson)
        self.parse_calls = 0

    def parse_worksheet(self, image):
        self.parse_calls += 1
        return self.worksheet

    def locate_answer_area(self, image, exercise):
        raise AssertionError("unit tests never check handwriting")

    def read_handwriting(self, image, exercise):
        raise AssertionError("unit tests never check handwriting")


class FakeIntent:
    def __init__(self) -> None:
        self.intent = TutorIntent("UNCLEAR", None, None, None)
        self.calls = []
        self.provider = "ollama"

    def interpret(self, transcript, state, exercise):
        self.calls.append((transcript, state, exercise))
        return self.intent


class FakeTranscriber:
    def transcribe(self, samples):
        raise AssertionError("these tests call handle_transcript directly")


class RecordingRenderer:
    """Keeps every request and returns the deterministic template line."""

    def __init__(self) -> None:
        self.requests = []
        self.provider = "recording"

    def render(self, request) -> RenderResult:
        self.requests.append(request)
        return RenderResult(request.template_text, self.provider, False)


class FailingRenderer:
    """A hosted renderer that already fell back to the template."""

    provider = "opencode"

    def render(self, request) -> RenderResult:
        return RenderResult(request.template_text, "template", True)


class RaisingRenderer:
    def render(self, request) -> RenderResult:
        raise RuntimeError("hosted renderer exploded")


class CustomRenderer:
    provider = "recording"

    def render(self, request) -> RenderResult:
        return RenderResult(
            "Nice try. Look at the first two numbers.", self.provider, False
        )


class ControllerTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.store = SessionStore("sqlite:///:memory:")
        self.lesson = load_lesson(LESSON_PATH)
        self.vision = FakeVision(self.lesson)
        self.intent = FakeIntent()
        self.transcriber = FakeTranscriber()
        self.store.create(SESSION_ID)

    def tearDown(self) -> None:
        self.store.close()

    def controller(
        self, *, flow_mode: str = "choice", renderer=None
    ) -> TutorController:
        return TutorController(
            SESSION_ID,
            lesson=self.lesson,
            store=self.store,
            vision=self.vision,
            intent=self.intent,
            transcriber=self.transcriber,
            renderer=renderer,
            flow_mode=flow_mode,
        )

    def review(self, controller: TutorController):
        return controller.handle_snapshot(JPEG_BYTES, "image/jpeg", "review")

    def choose(self, controller: TutorController, exercise_id: str = "A1"):
        self.intent.intent = TutorIntent(
            "CHOOSE_EXERCISE", exercise_id, None, None
        )
        return controller.handle_transcript(Transcript(exercise_id, 0.99))

    def at_a1(self, controller: TutorController) -> None:
        """Choice mode: review, then choose A1 through the fast path."""
        reviewed = self.review(controller)
        self.assertEqual(reviewed.status, "listening")
        chosen = self.choose(controller, "A1")
        self.assertEqual(chosen.exercise_id, "A1")

    def say(self, controller: TutorController, text: str, intent: TutorIntent):
        self.intent.intent = intent
        return controller.handle_transcript(Transcript(text, 0.99))

    def check(
        self, controller: TutorController, text: str, answer: str
    ):
        return self.say(
            controller,
            text,
            TutorIntent("CHECK_SPOKEN_ANSWER", None, answer, None),
        )

    def render_rows(self):
        return self.store.connection.execute(
            "SELECT name, details, success, duration_ms FROM tool_calls "
            "WHERE session_id = ? AND name = 'tutor.render' ORDER BY id",
            (SESSION_ID,),
        ).fetchall()


class GuidedFlowTests(ControllerTestCase):
    def test_guided_review_presents_a1(self) -> None:
        controller = self.controller(flow_mode="guided")

        response = self.review(controller)

        self.assertEqual(response.status, "speaking")
        self.assertEqual(response.exercise_id, "A1")
        self.assertIn("A1", response.tutor_text)
        self.assertIsNone(response.capture_request)
        state = self.store.get(SESSION_ID)
        self.assertTrue(state.placement_confirmed)
        self.assertEqual(state.chosen_exercise, "A1")
        self.assertEqual(controller.tutor.state, TutorState.STUDENT_WORKING)

    def test_correct_check_renders_praise_and_auto_advances(self) -> None:
        renderer = RecordingRenderer()
        controller = self.controller(flow_mode="guided", renderer=renderer)
        self.review(controller)

        response = self.check(controller, "fifteen", "fifteen")

        self.assertEqual(response.status, "speaking")
        self.assertEqual(response.exercise_id, "A2")
        self.assertIn("A2", response.tutor_text)
        self.assertIn("63 + 24", response.tutor_text)
        self.assertEqual(self.store.get(SESSION_ID).chosen_exercise, "A2")

        self.assertEqual(len(renderer.requests), 1)
        request = renderer.requests[0]
        self.assertEqual(request.mode, "praise")
        self.assertEqual(request.exercise.id, "A1")
        self.assertEqual(request.child_answer, "15")
        # The earned answer may be restated; the next exercise's printed
        # numbers may be named; its unsolved answer may not.
        self.assertIn(15, request.allowed_numbers)
        self.assertIn(63, request.allowed_numbers)
        self.assertIn(24, request.allowed_numbers)
        self.assertNotIn(87, request.allowed_numbers)

        row = self.render_rows()[-1]
        self.assertEqual(row["success"], 1)
        self.assertEqual(row["details"], "recording")
        self.assertGreaterEqual(row["duration_ms"], 0.0)

    def test_guided_intermediate_stays_on_the_exercise(self) -> None:
        controller = self.controller(flow_mode="guided")
        self.review(controller)

        response = self.check(controller, "nine", "nine")

        self.assertEqual(response.status, "speaking")
        self.assertEqual(response.exercise_id, "A1")
        self.assertIn("Add 6 to 9", response.tutor_text)
        state = self.store.get(SESSION_ID)
        self.assertEqual(state.chosen_exercise, "A1")
        self.assertEqual(state.current_step, 2)

    def test_auto_advance_never_allows_the_next_unsolved_answer(self) -> None:
        renderer = RecordingRenderer()
        controller = self.controller(flow_mode="guided", renderer=renderer)
        self.review(controller)
        exercises = self.lesson.exercises

        for index in range(len(exercises) - 1):
            current = exercises[index]
            following = exercises[index + 1]
            response = self.check(
                controller, str(current.answer), str(current.answer)
            )

            self.assertEqual(response.exercise_id, following.id)
            self.assertEqual(renderer.requests[-1].exercise.id, current.id)
            allowed = renderer.requests[-1].allowed_numbers
            if following.answer == current.answer:
                # B1 -> B2 share 24: the number was just earned, so it may
                # legitimately remain allowed.
                self.assertIn(following.answer, allowed)
            else:
                self.assertNotIn(
                    following.answer, allowed, following.id
                )

        # B5 -> B6 is the regression: B6's printed problem "25 / 5" contains
        # its own answer, so a naive printed-number union would release it.
        b5_request = renderer.requests[-1]
        self.assertEqual(b5_request.exercise.id, "B5")
        self.assertNotIn(5, b5_request.allowed_numbers)

    def test_guided_choice_mid_exercise_stays_on_the_current_item(self) -> None:
        renderer = RecordingRenderer()
        controller = self.controller(flow_mode="guided", renderer=renderer)
        self.review(controller)

        response = self.say(
            controller,
            "let's do B2",
            TutorIntent("CHOOSE_EXERCISE", "B2", None, None),
        )

        self.assertEqual(response.status, "speaking")
        self.assertEqual(response.exercise_id, "A1")
        self.assertEqual(
            response.tutor_text, select_response("stay_on_exercise")
        )
        self.assertIsNone(response.capture_request)
        self.assertEqual(self.store.get(SESSION_ID).chosen_exercise, "A1")
        self.assertEqual(controller.tutor.state, TutorState.STUDENT_WORKING)
        self.assertEqual(renderer.requests, [])

    def test_bare_number_while_working_is_a_spoken_answer(self) -> None:
        renderer = RecordingRenderer()
        controller = self.controller(flow_mode="guided", renderer=renderer)
        self.review(controller)

        # The classifier can return a bare number as CHOOSE_EXERCISE while A1
        # is in progress. A1 step 1 needs 9, so 2 is a real spoken answer:
        # the turn grades it and hints, instead of asking to stay.
        response = self.say(
            controller,
            "two",
            TutorIntent("CHOOSE_EXERCISE", None, None, None, None, 2),
        )

        self.assertEqual(response.status, "speaking")
        self.assertEqual(response.exercise_id, "A1")
        self.assertIsNone(response.capture_request)
        self.assertNotEqual(
            response.tutor_text, select_response("stay_on_exercise")
        )
        self.assertNotIn(
            select_response("spoken_only_fallback"), response.tutor_text
        )
        # The graded wrong answer speaks the first vetted hint for step 1.
        self.assertIn(
            self.lesson.get("A1").steps[0].hints[0], response.tutor_text
        )
        request = renderer.requests[-1]
        self.assertEqual(request.mode, "hint")
        self.assertEqual(request.exercise.id, "A1")
        self.assertEqual(request.child_answer, "2")
        state = self.store.get(SESSION_ID)
        self.assertEqual(state.chosen_exercise, "A1")
        self.assertEqual(state.current_step, 1)
        self.assertEqual(state.attempts, 1)
        self.assertEqual(controller.tutor.state, TutorState.STUDENT_WORKING)

    def test_guided_choice_after_wrap_up_is_not_a_stay_line(self) -> None:
        controller = self.controller(flow_mode="guided")
        self.review(controller)
        for exercise in self.lesson.exercises:
            self.check(controller, str(exercise.answer), str(exercise.answer))
        self.assertEqual(controller.tutor.state, TutorState.WRAP_UP)

        with self.assertRaises(ContractError) as raised:
            self.say(
                controller,
                "let's do B2",
                TutorIntent("CHOOSE_EXERCISE", "B2", None, None),
            )

        # There is no in-progress exercise to finish, so the guided fallback
        # must not pretend there is: a choice here is a real state error.
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(raised.exception.code, "not_allowed_in_state")
        self.assertEqual(self.store.get(SESSION_ID).chosen_exercise, "B6")

    def test_guided_flow_covers_all_twelve_and_wraps_up(self) -> None:
        renderer = RecordingRenderer()
        controller = self.controller(flow_mode="guided", renderer=renderer)
        self.review(controller)
        ids = [exercise.id for exercise in self.lesson.exercises]

        for index, exercise in enumerate(self.lesson.exercises):
            response = self.check(
                controller, str(exercise.answer), str(exercise.answer)
            )
            if index + 1 < len(ids):
                self.assertEqual(
                    response.exercise_id, ids[index + 1], exercise.id
                )
                self.assertIn(ids[index + 1], response.tutor_text)
            else:
                self.assertEqual(response.exercise_id, "B6")
                self.assertIn(
                    select_response("wrap_up"), response.tutor_text
                )

        self.assertEqual(len(renderer.requests), len(ids))
        self.assertEqual(controller.tutor.state, TutorState.WRAP_UP)


class RenderFailureTests(ControllerTestCase):
    def test_renderer_failure_uses_template_and_still_answers(self) -> None:
        controller = self.controller(renderer=FailingRenderer())
        self.at_a1(controller)

        response = self.check(controller, "fifteen", "15")

        self.assertTrue(response.tutor_text)
        self.assertIn("correct", response.tutor_text.lower())
        self.assertEqual(response.exercise_id, "A1")
        rows = self.render_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[-1]["success"], 0)
        self.assertEqual(rows[-1]["details"], "template")

    def test_raising_renderer_never_breaks_the_turn(self) -> None:
        controller = self.controller(renderer=RaisingRenderer())
        self.at_a1(controller)

        response = self.check(controller, "fifteen", "15")

        self.assertIn("correct", response.tutor_text.lower())
        row = self.render_rows()[-1]
        self.assertEqual(row["success"], 0)
        self.assertEqual(row["details"], "RuntimeError")

    def test_a_successful_render_replaces_the_template(self) -> None:
        controller = self.controller(renderer=CustomRenderer())
        self.at_a1(controller)

        response = self.check(controller, "seven", "7")

        self.assertIn(
            "Nice try. Look at the first two numbers.", response.tutor_text
        )
        self.assertEqual(self.render_rows()[-1]["success"], 1)


class ChoiceModeTests(ControllerTestCase):
    def test_default_flow_is_choice_with_the_template_renderer(self) -> None:
        controller = self.controller()

        self.assertEqual(controller.flow_mode, "choice")
        self.assertIsInstance(controller.renderer, TemplateRenderer)
        response = self.review(controller)
        self.assertEqual(response.status, "listening")
        self.assertIsNone(self.store.get(SESSION_ID).chosen_exercise)

    def test_choice_check_renders_praise_without_advancing(self) -> None:
        renderer = RecordingRenderer()
        controller = self.controller(flow_mode="choice", renderer=renderer)
        self.at_a1(controller)

        response = self.check(controller, "fifteen", "15")

        self.assertEqual(response.exercise_id, "A1")
        self.assertNotIn("Next is", response.tutor_text)
        self.assertEqual(self.store.get(SESSION_ID).chosen_exercise, "A1")
        self.assertEqual(renderer.requests[-1].mode, "praise")
        self.assertIn(15, renderer.requests[-1].allowed_numbers)

    def test_default_template_render_records_its_provider(self) -> None:
        controller = self.controller()
        self.at_a1(controller)

        self.check(controller, "fifteen", "15")

        row = self.render_rows()[-1]
        self.assertEqual(row["details"], "template")
        self.assertEqual(row["success"], 1)

    def test_choice_mode_mid_exercise_choice_still_returns_409(self) -> None:
        controller = self.controller(flow_mode="choice")
        self.at_a1(controller)

        with self.assertRaises(ContractError) as raised:
            self.say(
                controller,
                "let's do B2",
                TutorIntent("CHOOSE_EXERCISE", "B2", None, None),
            )

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(raised.exception.code, "not_allowed_in_state")
        self.assertEqual(self.store.get(SESSION_ID).chosen_exercise, "A1")

    def test_first_wrong_answer_renders_a_hint_and_hides_the_answer(self) -> None:
        renderer = RecordingRenderer()
        controller = self.controller(renderer=renderer)
        self.at_a1(controller)

        response = self.check(controller, "seven", "7")

        self.assertEqual(response.status, "speaking")
        self.assertNotIn("15", response.tutor_text)
        request = renderer.requests[-1]
        self.assertEqual(request.mode, "hint")
        self.assertNotIn(15, request.allowed_numbers)
        # The wrong answer is never added to the allowed set.
        self.assertNotIn(7, request.allowed_numbers)
        # The selected first hint mentions "two", which is not a printed
        # operand, so its numbers must be unioned into the allowed set.
        self.assertIn(2, request.allowed_numbers)

    def test_second_wrong_answer_rotates_to_the_next_hint_and_explains(self) -> None:
        renderer = RecordingRenderer()
        controller = self.controller(renderer=renderer)
        self.at_a1(controller)
        self.check(controller, "seven", "7")

        response = self.check(controller, "eight", "8")

        self.assertEqual(response.status, "speaking")
        self.assertNotIn("15", response.tutor_text)
        request = renderer.requests[-1]
        self.assertEqual(request.mode, "explain")
        self.assertNotIn(15, request.allowed_numbers)
        # The second hint no longer mentions "two".
        self.assertNotIn(2, request.allowed_numbers)

    def test_wrong_answers_speak_different_vetted_hints(self) -> None:
        renderer = RecordingRenderer()
        controller = self.controller(renderer=renderer)
        self.at_a1(controller)
        hints = self.lesson.get("A1").steps[0].hints

        first = self.check(controller, "seven", "7")
        second = self.check(controller, "eight", "8")

        # The template path speaks the authored hint, not the same step line
        # twice: attempt 0 selects hints[0], attempt 1 selects hints[1].
        self.assertNotEqual(first.tutor_text, second.tutor_text)
        self.assertIn(hints[0], first.tutor_text)
        self.assertIn(hints[1], second.tutor_text)
        self.assertEqual(renderer.requests[0].template_text, hints[0])
        self.assertEqual(renderer.requests[1].template_text, hints[1])

    def test_correct_intermediate_may_be_spoken_back(self) -> None:
        renderer = RecordingRenderer()
        controller = self.controller(renderer=renderer)
        self.at_a1(controller)

        response = self.check(controller, "nine", "nine")

        self.assertIn("Add 6 to 9", response.tutor_text)
        request = renderer.requests[-1]
        self.assertEqual(request.mode, "hint")
        self.assertEqual(request.step.index, 2)
        self.assertEqual(request.child_answer, "9")
        self.assertIn(9, request.allowed_numbers)
        self.assertNotIn(15, request.allowed_numbers)

    def test_bare_number_advances_the_step_instead_of_deferring_a_choice(
        self,
    ) -> None:
        renderer = RecordingRenderer()
        controller = self.controller(renderer=renderer)
        self.review(controller)
        self.choose(controller, "A3")

        # The live finding: A3 step 1 expects 2, so "two" is the ones digit.
        # It must be graded and advance the step, not ask to stay on A3.
        response = self.say(
            controller,
            "two",
            TutorIntent("CHOOSE_EXERCISE", None, None, None, None, 2),
        )

        self.assertEqual(response.status, "speaking")
        self.assertEqual(response.exercise_id, "A3")
        self.assertIsNone(response.capture_request)
        self.assertNotIn(
            select_response("stay_on_exercise"), response.tutor_text
        )
        self.assertIn("Subtract the tens", response.tutor_text)
        request = renderer.requests[-1]
        self.assertEqual(request.mode, "hint")
        self.assertEqual(request.exercise.id, "A3")
        self.assertEqual(request.child_answer, "2")
        state = self.store.get(SESSION_ID)
        self.assertEqual(state.chosen_exercise, "A3")
        self.assertEqual(state.current_step, 2)

    def test_hint_numbers_are_allowed_for_a_borrowing_step(self) -> None:
        renderer = RecordingRenderer()
        controller = self.controller(renderer=renderer)
        self.review(controller)
        self.choose(controller, "A4")

        # A4's first hint says "The 1 in 71 ..."; 1 is not a printed operand.
        self.check(controller, "five", "5")

        request = renderer.requests[-1]
        self.assertIn(1, request.allowed_numbers)
        self.assertNotIn(63, request.allowed_numbers)

    def test_check_without_a_candidate_still_requests_writing(self) -> None:
        controller = self.controller()
        self.at_a1(controller)

        response = self.say(
            controller,
            "let me show you",
            TutorIntent("CHECK_SPOKEN_ANSWER", None, None, None),
        )

        self.assertEqual(response.status, "reading_work")
        self.assertEqual(response.capture_request, "check")
        self.assertEqual(self.render_rows(), [])


class ConversationIntentTests(ControllerTestCase):
    def test_help_explains_the_current_step_without_the_answer(self) -> None:
        renderer = RecordingRenderer()
        controller = self.controller(renderer=renderer)
        self.at_a1(controller)

        response = self.say(
            controller,
            "I don't understand",
            TutorIntent("HELP", None, None, None),
        )

        self.assertEqual(response.status, "speaking")
        self.assertEqual(response.exercise_id, "A1")
        self.assertIn("Add 4 and 5", response.tutor_text)
        self.assertNotIn("15", response.tutor_text)
        request = renderer.requests[-1]
        self.assertEqual(request.mode, "explain")
        self.assertEqual(request.step.index, 1)
        self.assertNotIn(15, request.allowed_numbers)
        self.assertEqual(self.render_rows()[-1]["success"], 1)

    def test_ask_for_the_answer_never_reveals_it(self) -> None:
        renderer = RecordingRenderer()
        controller = self.controller(renderer=renderer)
        self.at_a1(controller)

        response = self.say(
            controller,
            "just tell me the answer",
            TutorIntent("ASK_ANSWER", None, None, None),
        )

        self.assertEqual(response.status, "speaking")
        self.assertEqual(response.exercise_id, "A1")
        self.assertIn(
            select_response("ready_with_exercise"), response.tutor_text
        )
        self.assertNotIn("15", response.tutor_text)
        self.assertNotIn("fifteen", response.tutor_text.lower())
        request = renderer.requests[-1]
        self.assertEqual(request.mode, "hint")
        self.assertNotIn(15, request.allowed_numbers)
        self.assertEqual(self.store.get(SESSION_ID).attempts, 0)

    def test_help_before_placement_asks_for_the_sheet(self) -> None:
        controller = self.controller()

        response = self.say(
            controller,
            "I don't understand",
            TutorIntent("HELP", None, None, None),
        )

        self.assertEqual(response.status, "adjust_sheet")
        self.assertEqual(response.capture_request, "review")
        self.assertEqual(
            response.tutor_text, placement_prompt(PLACEMENT_MISSING)
        )
        self.assertEqual(self.render_rows(), [])

    def test_help_without_an_exercise_lists_the_worksheet(self) -> None:
        controller = self.controller()
        self.review(controller)

        response = self.say(
            controller,
            "I don't understand",
            TutorIntent("HELP", None, None, None),
        )

        self.assertEqual(response.status, "listening")
        self.assertIn("addition and subtraction", response.tutor_text)
        self.assertIsNone(self.store.get(SESSION_ID).chosen_exercise)
        self.assertEqual(self.render_rows(), [])

    def test_ask_answer_without_an_exercise_is_placement_gated(self) -> None:
        controller = self.controller()

        response = self.say(
            controller,
            "just tell me the answer",
            TutorIntent("ASK_ANSWER", None, None, None),
        )

        self.assertEqual(response.status, "adjust_sheet")
        self.assertEqual(response.capture_request, "review")
        self.assertEqual(
            response.tutor_text, placement_prompt(PLACEMENT_MISSING)
        )


if __name__ == "__main__":
    unittest.main()
