"""Tests for fixed exercise progression and session recovery."""

import unittest

from agent.lesson import load_lesson
from agent.memory import SessionStore
from agent.responses import select_response
from agent.tutor import InvalidTransition, TutorSession, TutorState
from agent.vision import HandwritingRead, ParsedItem, WorksheetParse


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


class LessonFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = SessionStore("sqlite:///:memory:")
        self.lesson = load_lesson("agent/lessons/grade3_demo.yaml")
        self.session = TutorSession(self.lesson, self.store, "flow")

    def tearDown(self) -> None:
        self.store.close()

    def test_full_flow_survives_wrong_then_right_then_next(self) -> None:
        response = self.session.start(valid_sheet(self.lesson))
        self.assertIn("addition and subtraction", response)
        for exercise in self.lesson.exercises:
            self.assertNotIn(exercise.id, response)
        self.assertIn("4 + 5 + 6", self.session.choose("A one"))

        wrong, wrong_result = self.session.check("14")
        self.assertFalse(wrong_result.correct)
        self.assertIn("next step", wrong.lower())
        self.assertEqual(self.session.state, TutorState.STUDENT_WORKING)

        right, right_result = self.session.check("15")
        self.assertTrue(right_result.correct)
        self.assertIn("correct", right.lower())
        self.assertEqual(self.session.state, TutorState.PRAISE)

        self.assertEqual(self.session.offer_next(), select_response("ask_choice"))
        self.assertEqual(self.session.state, TutorState.NEXT_EXERCISE)

        self.assertIn("8 x 3", self.session.choose("B two"))
        self.assertEqual(self.session.state, TutorState.STUDENT_WORKING)
        _, b2_result = self.session.check("24")
        self.assertTrue(b2_result.correct)
        self.assertEqual(self.session.state, TutorState.PRAISE)

    def test_recover_keeps_exercise_and_allows_retry(self) -> None:
        self.session.start(valid_sheet(self.lesson))
        self.session.choose("A1")

        response, result = self.session.check_handwriting(None)
        self.assertIsNone(result)
        self.assertEqual(response, select_response("service_error"))
        self.assertEqual(self.session.state, TutorState.RECOVER)

        self.assertEqual(self.session.recover(), select_response("service_error"))
        self.assertEqual(self.session.state, TutorState.STUDENT_WORKING)

        saved = self.store.get("flow")
        self.assertIsNotNone(saved)
        self.assertEqual(saved.chosen_exercise, "A1")
        self.assertEqual(saved.current_step, 1)

        _, retry_result = self.session.check("15")
        self.assertTrue(retry_result.correct)
        self.assertEqual(self.store.get("flow").chosen_exercise, "A1")

    def test_check_after_guide_stays_usable(self) -> None:
        self.session.start(valid_sheet(self.lesson))
        self.session.choose("A1")

        _, first_result = self.session.check("14")
        self.assertFalse(first_result.correct)
        self.assertEqual(self.session.state, TutorState.STUDENT_WORKING)

        response, second_result = self.session.check("15")
        self.assertTrue(second_result.correct)
        self.assertIn("correct", response.lower())

    def test_guided_flow_takes_an_intermediate_then_the_final_answer(self) -> None:
        session = TutorSession(self.lesson, self.store, "guided-steps")

        session.begin_guided(valid_sheet(self.lesson))
        hint = session.check_with_mode("nine")

        self.assertEqual(hint.mode, "hint")
        self.assertEqual(self.store.get("guided-steps").current_step, 2)
        self.assertEqual(self.store.get("guided-steps").attempts, 0)

        praise = session.check_with_mode("15")

        self.assertEqual(praise.mode, "praise")
        self.assertTrue(praise.completed)
        self.assertIn("A2", session.advance_guided())

    def test_guided_flow_advances_every_exercise_and_wraps_up(self) -> None:
        session = TutorSession(self.lesson, self.store, "guided-flow")

        text = session.begin_guided(valid_sheet(self.lesson))

        self.assertIn("A1", text)
        self.assertIn(self.lesson.get("A1").problem, text)
        self.assertEqual(session.state, TutorState.STUDENT_WORKING)

        for position, exercise in enumerate(self.lesson.exercises):
            with self.subTest(exercise=exercise.id):
                outcome = session.check_with_mode(str(exercise.answer))
                self.assertEqual(outcome.mode, "praise")
                self.assertTrue(outcome.completed)

                text = session.advance_guided()

                if position + 1 < len(self.lesson.exercises):
                    following = self.lesson.exercises[position + 1]
                    self.assertIn(following.id, text)
                    self.assertIn(following.problem, text)
                    self.assertEqual(
                        self.store.get("guided-flow").chosen_exercise,
                        following.id,
                    )
                    self.assertEqual(
                        self.store.get("guided-flow").current_step, 1
                    )
                    self.assertEqual(self.store.get("guided-flow").attempts, 0)
                else:
                    self.assertEqual(text, select_response("wrap_up"))

        self.assertEqual(session.state, TutorState.WRAP_UP)

    def test_check_in_praise_routes_to_more_practice(self) -> None:
        self.session.start(valid_sheet(self.lesson))
        self.session.choose("A1")
        self.session.check("15")
        self.assertEqual(self.session.state, TutorState.PRAISE)

        response, result = self.session.check("15")
        self.assertEqual(response, select_response("ask_choice"))
        self.assertIsNone(result)
        self.assertEqual(self.session.state, TutorState.NEXT_EXERCISE)

        # The same exercise can be redone by choosing it again.
        self.assertIn("4 + 5 + 6", self.session.choose("A1"))
        self.assertEqual(self.session.state, TutorState.STUDENT_WORKING)

    def test_check_handwriting_from_student_working_after_pause(self) -> None:
        self.session.start(valid_sheet(self.lesson))
        self.session.choose("A1")

        response, result = self.session.check_handwriting(
            HandwritingRead("1?", "15", 0.2, "")
        )
        self.assertIsNone(result)
        self.assertEqual(response, select_response("unclear"))
        self.assertEqual(self.session.state, TutorState.STUDENT_WORKING)

        _, checked = self.session.check_handwriting(
            HandwritingRead("15", "15", 0.95, "")
        )
        self.assertTrue(checked.correct)
        self.assertEqual(self.session.state, TutorState.PRAISE)

    def test_resume_presents_saved_exercise(self) -> None:
        self.session.start(valid_sheet(self.lesson))
        self.session.choose("A1")
        self.session.check("14")

        resumed = TutorSession(self.lesson, self.store, "flow")
        self.assertEqual(resumed.state, TutorState.STUDENT_WORKING)
        response = resumed.resume()
        self.assertIn("4 + 5 + 6", response)
        self.assertIn(self.lesson.get("A1").steps[0].prompt, response)
        self.assertEqual(resumed.state, TutorState.STUDENT_WORKING)

    def test_start_twice_is_rejected(self) -> None:
        self.session.start(valid_sheet(self.lesson))
        with self.assertRaises(InvalidTransition):
            self.session.start()

        self.session.choose("A1")
        resumed = TutorSession(self.lesson, self.store, "flow")
        with self.assertRaises(InvalidTransition):
            resumed.start()
        self.assertIn("4 + 5 + 6", resumed.resume())

    def test_next_done_and_list_intents(self) -> None:
        # The controller owns intent routing now; the tutor methods it calls
        # are exercised directly here so this suite needs no transport module.
        self.session.start(valid_sheet(self.lesson))

        listed = self.session.list_worksheet()
        self.assertEqual(
            listed,
            select_response("worksheet_summary")
            + " "
            + select_response("ask_choice"),
        )
        for exercise in self.lesson.exercises:
            self.assertNotIn(exercise.id, listed)
        self.assertIn(select_response("ask_choice"), listed)
        self.assertEqual(self.session.state, TutorState.CHOOSE_EXERCISE)

        self.session.choose("A1")
        self.session.check("15")

        offered = self.session.offer_next()
        self.assertEqual(offered, select_response("ask_choice"))
        self.assertEqual(self.session.state, TutorState.NEXT_EXERCISE)

        self.session.choose("B2")
        self.session.check("24")
        wrapped = self.session.wrap_up()
        self.assertEqual(wrapped, select_response("wrap_up"))
        self.assertEqual(self.session.state, TutorState.WRAP_UP)


if __name__ == "__main__":
    unittest.main()
