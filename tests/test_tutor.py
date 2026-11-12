import unittest

from agent.calculator import verified_numbers
from agent.lesson import Lesson, load_lesson
from agent.memory import SessionStore
from agent.responses import (
    numbers_in,
    placement_prompt,
    select_response,
    uncertain_prompt,
)
from agent.tutor import (
    _TRANSITIONS,
    InvalidTransition,
    TutorSession,
    TutorState,
    next_state,
    worksheet_placement,
)
from agent.vision import (
    PLACEMENT_DIFFERENT_SHEET,
    PLACEMENT_MISSING,
    PLACEMENT_PARTIAL,
    PLACEMENT_READY,
    PLACEMENT_UNKNOWN,
    PLACEMENT_UNREADABLE,
    VISIBILITY_BLANK,
    VISIBILITY_OVERWRITTEN,
    VISIBILITY_UNCLEAR,
    HandwritingRead,
    ParsedItem,
    WorksheetParse,
)


def _sheet(
    lesson: Lesson,
    expressions: dict[str, str] | None = None,
    items: list[str] | None = None,
    confidence: float = 0.99,
    placement: str = PLACEMENT_READY,
    reason: str = "",
) -> WorksheetParse:
    expressions = expressions or {}
    ids = items if items is not None else [exercise.id for exercise in lesson.exercises]
    return WorksheetParse(
        [
            ParsedItem(
                item_id,
                lesson.get(item_id).section,
                lesson.get(item_id).problem,
                expressions.get(
                    item_id, lesson.get(item_id).verification_expression
                ),
            )
            for item_id in ids
        ],
        confidence,
        placement,
        reason,
    )


def _extra_item_sheet(lesson: Lesson) -> WorksheetParse:
    return WorksheetParse(
        [
            ParsedItem(
                exercise.id,
                exercise.section,
                exercise.problem,
                exercise.verification_expression,
            )
            for exercise in lesson.exercises
        ]
        + [ParsedItem("C1", "C", "2 + 2", "2 + 2")],
        0.99,
    )


def _unknown_item_sheet(lesson: Lesson) -> WorksheetParse:
    items = [
        ParsedItem(
            exercise.id,
            exercise.section,
            exercise.problem,
            exercise.verification_expression,
        )
        for exercise in lesson.exercises
    ]
    items[-1] = ParsedItem("A7", "A", "1 + 1", "1 + 1")
    return WorksheetParse(items, 0.99)


class TutorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = SessionStore("sqlite:///:memory:")
        self.session = TutorSession(
            load_lesson("agent/lessons/grade3_demo.yaml"), self.store, "s1"
        )

    def tearDown(self) -> None:
        self.store.close()

    def _new_session(self, session_id: str) -> TutorSession:
        return TutorSession(self.session.lesson, self.store, session_id)

    def test_transition_table_matches_architecture(self) -> None:
        # docs/architecture/02-Architecture-ai-math-tutor.md §3.9, plus the
        # placement gate from task 23. Guide and Praise have no shortcut edges
        # into CheckAnswer or PresentExercise.
        self.assertEqual(
            _TRANSITIONS,
            {
                (TutorState.GREETING, "start"): TutorState.PARSE_WORKSHEET,
                (TutorState.WAITING_FOR_PLACEMENT, "start"): (
                    TutorState.PARSE_WORKSHEET
                ),
                (TutorState.PARSE_WORKSHEET, "parsed"): TutorState.PRESENT_LIST,
                (TutorState.PARSE_WORKSHEET, "parse_failed"): (
                    TutorState.WAITING_FOR_PLACEMENT
                ),
                (TutorState.PRESENT_LIST, "presented"): TutorState.CHOOSE_EXERCISE,
                (TutorState.CHOOSE_EXERCISE, "choice_valid"): (
                    TutorState.PRESENT_EXERCISE
                ),
                (TutorState.CHOOSE_EXERCISE, "choice_unclear"): (
                    TutorState.CHOOSE_EXERCISE
                ),
                (TutorState.PRESENT_EXERCISE, "presented"): (
                    TutorState.STUDENT_WORKING
                ),
                (TutorState.STUDENT_WORKING, "pause"): TutorState.OBSERVE_WORK,
                (TutorState.STUDENT_WORKING, "check"): TutorState.OBSERVE_WORK,
                (TutorState.OBSERVE_WORK, "read_confident"): TutorState.CHECK_ANSWER,
                (TutorState.OBSERVE_WORK, "read_unclear"): TutorState.GUIDE,
                (TutorState.OBSERVE_WORK, "vision_failed"): TutorState.RECOVER,
                (TutorState.CHECK_ANSWER, "correct"): TutorState.PRAISE,
                (TutorState.CHECK_ANSWER, "incorrect"): TutorState.GUIDE,
                (TutorState.CHECK_ANSWER, "vision_failed"): TutorState.RECOVER,
                (TutorState.GUIDE, "presented"): TutorState.STUDENT_WORKING,
                (TutorState.PRAISE, "more"): TutorState.NEXT_EXERCISE,
                (TutorState.PRAISE, "done"): TutorState.WRAP_UP,
                (TutorState.NEXT_EXERCISE, "choose"): TutorState.CHOOSE_EXERCISE,
                (TutorState.RECOVER, "resumed"): TutorState.STUDENT_WORKING,
            },
        )

    def test_new_session_waits_for_placement(self) -> None:
        self.assertEqual(
            self.session.state, TutorState.WAITING_FOR_PLACEMENT
        )

    def test_state_enum_is_string_compatible(self) -> None:
        self.assertIsInstance(TutorState.GREETING, str)
        self.assertEqual(str(TutorState.GREETING), "Greeting")
        self.assertEqual(TutorState.GREETING.value, "Greeting")
        self.assertEqual(
            next_state(TutorState.GREETING, "start"),
            TutorState.PARSE_WORKSHEET,
        )

    def test_worksheet_placement_statuses(self) -> None:
        lesson = self.session.lesson
        ids = [exercise.id for exercise in lesson.exercises]
        cases = [
            ("none", None, PLACEMENT_MISSING),
            (
                "unknown placement with exact sheet",
                _sheet(
                    lesson,
                    placement="Center and Bottom",
                ),
                PLACEMENT_READY,
            ),
            (
                "explicit unreadable",
                _sheet(lesson, placement=PLACEMENT_UNREADABLE),
                PLACEMENT_UNREADABLE,
            ),
            (
                "explicit partial",
                _sheet(lesson, placement=PLACEMENT_PARTIAL),
                PLACEMENT_PARTIAL,
            ),
            (
                "explicit different",
                _sheet(lesson, placement=PLACEMENT_DIFFERENT_SHEET),
                PLACEMENT_DIFFERENT_SHEET,
            ),
            (
                "explicit missing",
                _sheet(lesson, placement=PLACEMENT_MISSING),
                PLACEMENT_MISSING,
            ),
            (
                "low confidence",
                _sheet(lesson, confidence=0.5),
                PLACEMENT_UNREADABLE,
            ),
            (
                "no items",
                _sheet(lesson, items=[]),
                PLACEMENT_MISSING,
            ),
            (
                "missing items",
                _sheet(lesson, items=ids[:-1]),
                PLACEMENT_PARTIAL,
            ),
            (
                "extra item",
                _extra_item_sheet(lesson),
                PLACEMENT_DIFFERENT_SHEET,
            ),
            (
                "unknown id",
                _unknown_item_sheet(lesson),
                PLACEMENT_DIFFERENT_SHEET,
            ),
            (
                "duplicate id",
                _sheet(lesson, items=ids[:-1] + ["A1"]),
                PLACEMENT_DIFFERENT_SHEET,
            ),
            (
                "wrong expression",
                _sheet(lesson, expressions={"A2": "63 + 25"}),
                PLACEMENT_DIFFERENT_SHEET,
            ),
            ("exact sheet", _sheet(lesson), PLACEMENT_READY),
        ]
        for name, worksheet, expected in cases:
            with self.subTest(name=name):
                self.assertEqual(
                    worksheet_placement(worksheet, lesson), expected
                )

    def test_observed_position_description_with_valid_sheet_is_ready(
        self,
    ) -> None:
        worksheet = _sheet(
            self.session.lesson, placement="Center and Bottom"
        )

        self.assertEqual(worksheet.placement, "Center and Bottom")
        self.assertEqual(
            worksheet_placement(worksheet, self.session.lesson),
            PLACEMENT_READY,
        )
        response = self.session.start(worksheet)
        self.assertIn("addition and subtraction", response)
        self.assertEqual(self.session.state, TutorState.CHOOSE_EXERCISE)

    def test_unknown_placement_falls_through_to_content_checks(self) -> None:
        lesson = self.session.lesson
        ids = [exercise.id for exercise in lesson.exercises]
        cases = [
            (
                "short sheet",
                _sheet(
                    lesson, items=ids[:-1], placement=PLACEMENT_UNKNOWN
                ),
                PLACEMENT_PARTIAL,
            ),
            (
                "blank sheet",
                _sheet(lesson, items=[], placement=PLACEMENT_UNKNOWN),
                PLACEMENT_MISSING,
            ),
            (
                "wrong expression",
                _sheet(
                    lesson,
                    expressions={"A2": "63 + 25"},
                    placement=PLACEMENT_UNKNOWN,
                ),
                PLACEMENT_DIFFERENT_SHEET,
            ),
            (
                "low confidence",
                _sheet(lesson, confidence=0.5, placement=PLACEMENT_UNKNOWN),
                PLACEMENT_UNREADABLE,
            ),
        ]
        for name, worksheet, expected in cases:
            with self.subTest(name=name):
                self.assertEqual(
                    worksheet_placement(worksheet, lesson), expected
                )

    def test_explicit_non_ready_placement_wins_over_content(self) -> None:
        lesson = self.session.lesson
        for placement in (
            PLACEMENT_MISSING,
            PLACEMENT_PARTIAL,
            PLACEMENT_UNREADABLE,
            PLACEMENT_DIFFERENT_SHEET,
        ):
            with self.subTest(placement=placement):
                self.assertEqual(
                    worksheet_placement(
                        _sheet(lesson, placement=placement), lesson
                    ),
                    placement,
                )

    def test_start_without_worksheet_waits_for_placement(self) -> None:
        response = self.session.start()

        self.assertEqual(response, placement_prompt(PLACEMENT_MISSING))
        self.assertEqual(
            self.session.state, TutorState.WAITING_FOR_PLACEMENT
        )
        self.assertEqual(self.store.get("s1").turns, ())

    def test_start_with_low_confidence_waits_for_placement(self) -> None:
        response = self.session.start(_sheet(self.session.lesson, confidence=0.5))

        self.assertEqual(response, placement_prompt(PLACEMENT_UNREADABLE))
        self.assertEqual(
            self.session.state, TutorState.WAITING_FOR_PLACEMENT
        )
        self.assertEqual(self.store.get("s1").turns, ())

    def test_worksheet_accepts_exact_sheet(self) -> None:
        response = self.session.start(_sheet(self.session.lesson))

        self.assertEqual(
            response,
            select_response("worksheet_summary")
            + " "
            + select_response("ask_choice"),
        )
        self.assertIn("addition and subtraction", response)
        self.assertIn("multiplication and division", response)
        for exercise in self.session.lesson.exercises:
            self.assertNotIn(exercise.id, response)
        self.assertEqual(self.session.state, TutorState.CHOOSE_EXERCISE)

    def test_worksheet_accepts_printed_multiplication_glyph(self) -> None:
        # The sheet prints "6 x 4"; the parsed expression is still exact after
        # normalize() maps the glyph to the evaluator's "*".
        expressions = {"B1": "6 x 4", "B4": "20 ÷ 4"}
        response = self.session.start(
            _sheet(self.session.lesson, expressions=expressions)
        )

        self.assertIn("addition and subtraction", response)
        self.assertEqual(self.session.state, TutorState.CHOOSE_EXERCISE)

    def test_worksheet_rejects_wrong_expression(self) -> None:
        worksheet = _sheet(self.session.lesson, expressions={"A2": "63 + 25"})
        response = self.session.start(worksheet)

        self.assertEqual(response, placement_prompt(PLACEMENT_DIFFERENT_SHEET))
        self.assertEqual(
            self.session.state, TutorState.WAITING_FOR_PLACEMENT
        )
        self.assertEqual(self.store.get("s1").turns, ())

    def test_worksheet_rejects_duplicate_or_missing_ids(self) -> None:
        ids = [exercise.id for exercise in self.session.lesson.exercises]
        cases = [
            ([*ids[:-1], "A1"], placement_prompt(PLACEMENT_DIFFERENT_SHEET)),
            (ids[:-1], placement_prompt(PLACEMENT_PARTIAL)),
        ]
        for items, expected in cases:
            with self.subTest(items=items):
                session = self._new_session(f"strict-{len(items)}-{items[0]}")
                response = session.start(_sheet(session.lesson, items=items))
                self.assertEqual(response, expected)
                self.assertEqual(
                    session.state, TutorState.WAITING_FOR_PLACEMENT
                )

    def test_retake_after_poor_image_reaches_choice_without_new_session(self) -> None:
        first = self.session.start(_sheet(self.session.lesson, confidence=0.4))
        self.assertEqual(first, placement_prompt(PLACEMENT_UNREADABLE))

        second = self.session.start(_sheet(self.session.lesson))
        self.assertIn("addition and subtraction", second)
        self.assertEqual(
            self.session.state, TutorState.CHOOSE_EXERCISE
        )
        self.assertIn("4 + 5 + 6", self.session.choose("A one"))
        self.assertEqual(self.session.state, TutorState.STUDENT_WORKING)

    def test_request_placement_stays_waiting_without_a_turn(self) -> None:
        response = self.session.request_placement(PLACEMENT_PARTIAL)

        self.assertEqual(response, placement_prompt(PLACEMENT_PARTIAL))
        self.assertEqual(
            self.session.state, TutorState.WAITING_FOR_PLACEMENT
        )
        self.assertEqual(self.store.get("s1").turns, ())

    def test_request_placement_after_a_choice_keeps_check_usable(self) -> None:
        self.session.start(_sheet(self.session.lesson))
        self.session.choose("A1")
        self.assertEqual(self.session.state, TutorState.STUDENT_WORKING)

        response = self.session.request_placement(PLACEMENT_UNREADABLE)

        self.assertEqual(response, placement_prompt(PLACEMENT_UNREADABLE))
        self.assertEqual(self.session.state, TutorState.STUDENT_WORKING)
        checked, result = self.session.check("15")
        self.assertTrue(result.correct)
        self.assertIn("correct", checked.lower())
        self.assertEqual(self.session.state, TutorState.PRAISE)

    def test_restore_after_confirmed_placement_starts_at_choice(self) -> None:
        self.store.update("s1", placement_confirmed=True)

        restored = self._new_session("s1")

        self.assertEqual(restored.state, TutorState.CHOOSE_EXERCISE)
        self.assertEqual(
            restored.list_worksheet(),
            select_response("worksheet_summary")
            + " "
            + select_response("ask_choice"),
        )

    def test_list_worksheet_requires_a_confirmed_placement(self) -> None:
        with self.assertRaises(InvalidTransition):
            self.session.list_worksheet()
        self.assertEqual(
            self.session.state, TutorState.WAITING_FOR_PLACEMENT
        )

        self.session.start(_sheet(self.session.lesson))
        self.assertIn(
            "addition and subtraction", self.session.list_worksheet()
        )

    def test_list_worksheet_from_next_exercise_returns_summary(self) -> None:
        self.session.start(_sheet(self.session.lesson))
        self.session.choose("A1")
        self.session.check("15")
        self.session.offer_next()
        self.assertEqual(self.session.state, TutorState.NEXT_EXERCISE)

        response = self.session.list_worksheet()

        self.assertEqual(
            response,
            select_response("worksheet_summary")
            + " "
            + select_response("ask_choice"),
        )
        self.assertEqual(self.session.state, TutorState.CHOOSE_EXERCISE)

    def test_full_choice_check_and_resume_flow(self) -> None:
        self.assertIn(
            "addition and subtraction",
            self.session.start(_sheet(self.session.lesson)),
        )
        self.assertIn("4 + 5 + 6", self.session.choose("A one"))
        response, result = self.session.check("15")
        self.assertTrue(result.correct)
        self.assertIn("correct", response.lower())
        resumed = TutorSession(self.session.lesson, self.store, "s1")
        self.assertEqual(resumed.state, TutorState.STUDENT_WORKING)

    def test_choice_candidates_need_a_section_for_a_bare_number(self) -> None:
        lesson = self.session.lesson
        self.assertEqual(lesson.choice_candidates("A two"), ("A2",))
        self.assertEqual(
            lesson.choice_candidates("section A, number two"), ("A2",)
        )
        self.assertEqual(
            lesson.choice_candidates("number two"), ("A2", "B2")
        )
        self.assertEqual(lesson.choice_candidates("seven"), ())
        self.assertEqual(lesson.resolve_choice("number two"), None)
        self.assertEqual(lesson.resolve_choice("A2"), "A2")

    def test_ambiguous_choice_asks_for_the_section_and_stays(self) -> None:
        self.session.start(_sheet(self.session.lesson))

        response = self.session.choose("number two")

        self.assertEqual(response, select_response("ask_section"))
        self.assertEqual(self.session.state, TutorState.CHOOSE_EXERCISE)
        self.assertIsNone(self.store.get("s1").chosen_exercise)

    def test_choice_presents_the_first_step_without_the_answer(self) -> None:
        self.session.start(_sheet(self.session.lesson))
        exercise = self.session.lesson.get("A2")

        response = self.session.choose("section A, number two")

        self.assertIn(exercise.problem, response)
        self.assertIn(exercise.steps[0].prompt, response)
        self.assertNotIn(exercise.answer, numbers_in(response))
        self.assertEqual(self.store.get("s1").current_step, 1)
        self.assertEqual(self.session.state, TutorState.STUDENT_WORKING)

    def test_ask_choice_uses_the_section_and_number_wording(self) -> None:
        expected = "Which section and number would you like to start with?"
        self.assertEqual(select_response("ask_choice"), expected)

        self.session.start(_sheet(self.session.lesson))
        self.assertEqual(
            self.session.list_worksheet(),
            select_response("worksheet_summary") + " " + expected,
        )
        self.session.choose("A1")
        self.assertEqual(self.session.offer_next(), expected)

    def test_ask_step_returns_the_current_step_without_state_change(self) -> None:
        self.session.start(_sheet(self.session.lesson))
        self.session.choose("A1")
        before = self.store.get("s1")

        response = self.session.ask_step()

        after = self.store.get("s1")
        self.assertEqual(
            response, self.session.lesson.get("A1").steps[0].prompt
        )
        self.assertEqual(after.chosen_exercise, before.chosen_exercise)
        self.assertEqual(after.current_step, before.current_step)
        self.assertEqual(self.session.state, TutorState.STUDENT_WORKING)

    def test_low_confidence_never_checks_answer(self) -> None:
        self.session.start(_sheet(self.session.lesson))
        self.session.choose("A1")
        response, result = self.session.check_handwriting(
            HandwritingRead("?", "15", 0.2, "")
        )
        self.assertIsNone(result)
        self.assertIn("again", response.lower())
        self.assertEqual(self.session.state, TutorState.STUDENT_WORKING)

    def test_uncertain_visibility_never_increments_attempts(self) -> None:
        self.session.start(_sheet(self.session.lesson))
        self.session.choose("A1")

        for visibility in (VISIBILITY_BLANK, VISIBILITY_OVERWRITTEN):
            with self.subTest(visibility=visibility):
                before = self.store.get("s1").attempts
                response, result = self.session.check_handwriting(
                    HandwritingRead("15", "15", 0.99, "", visibility)
                )
                self.assertIsNone(result)
                self.assertEqual(response, uncertain_prompt(visibility))
                self.assertEqual(self.store.get("s1").attempts, before)
                self.assertEqual(self.session.state, TutorState.STUDENT_WORKING)

        checked, final = self.session.check_handwriting(
            HandwritingRead("15", "15", 0.99, "")
        )
        self.assertTrue(final.correct)
        self.assertIn("correct", checked.lower())
        self.assertEqual(self.store.get("s1").attempts, 1)

    def test_unknown_visibility_is_uncertain_and_never_checks(self) -> None:
        self.session.start(_sheet(self.session.lesson))
        self.session.choose("A1")
        before = self.store.get("s1").attempts

        response, result = self.session.check_handwriting(
            HandwritingRead("15", "15", 0.99, "", VISIBILITY_UNCLEAR)
        )

        self.assertIsNone(result)
        self.assertEqual(response, uncertain_prompt(VISIBILITY_UNCLEAR))
        self.assertIn("again", response.lower())
        self.assertEqual(self.store.get("s1").attempts, before)
        self.assertEqual(self.session.state, TutorState.STUDENT_WORKING)

    def test_wrong_answer_returns_guidance(self) -> None:
        self.session.start(_sheet(self.session.lesson))
        self.session.choose("A1")
        response, result = self.session.check("14")
        self.assertFalse(result.correct)
        self.assertIn("next step", response.lower())
        # Guide --> StudentWorking, so the next check needs no special edge.
        self.assertEqual(self.session.state, TutorState.STUDENT_WORKING)

    def test_start_does_not_log_duplicate_vision_rows(self) -> None:
        self.session.start(_sheet(self.session.lesson))
        rows = self.store.connection.execute(
            "SELECT name FROM tool_calls WHERE session_id = ?", (self.session.session_id,)
        ).fetchall()
        self.assertEqual([row["name"] for row in rows], [])

    def test_check_uses_guidance_step(self) -> None:
        self.session.start(_sheet(self.session.lesson))
        self.session.choose("A1")
        response, result = self.session.check("14", step_index=2)
        self.assertFalse(result.correct)
        self.assertIn("Add 6 to 9", response)

    def test_handwriting_forwards_guidance_step(self) -> None:
        self.session.start(_sheet(self.session.lesson))
        self.session.choose("A1")
        response, result = self.session.check_handwriting(
            HandwritingRead("14", "14", 0.99, ""), step_index=2
        )
        self.assertFalse(result.correct)
        self.assertIn("Add 6 to 9", response)

    def test_every_wrong_answer_response_speaks_only_verified_numbers(self) -> None:
        for exercise in self.session.lesson.exercises:
            with self.subTest(exercise=exercise.id):
                session = self._new_session(f"guard-{exercise.id}")
                session.start(_sheet(session.lesson))
                session.choose(exercise.id)
                response, result = session.check(str(exercise.answer + 1))
                self.assertFalse(result.correct)
                self.assertLessEqual(
                    numbers_in(response), verified_numbers(exercise, result)
                )


if __name__ == "__main__":
    unittest.main()
