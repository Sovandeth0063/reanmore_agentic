"""Tests for the fixed, approved response catalog."""

import unittest
from pathlib import Path

from agent.calculator import check_answer, verified_numbers
from agent.lesson import load_lesson
from agent.responses import (
    UnknownResponse,
    guidance_for,
    guard_numbers,
    numbers_in,
    placement_prompt,
    response_keys,
    select_response,
    uncertain_prompt,
)


EXERCISE_IDS = tuple(
    f"{section}{number}" for section in "AB" for number in range(1, 7)
)

BENIGN_VALUES = {
    "items": "A1, A2, A3",
    "text": "Let's try that again.",
    "problem": "4 + 5 + 6",
    "praise": "Nice work.",
    "focus": "Add the ones first.",
}


class ResponseCatalogTests(unittest.TestCase):
    def test_every_key_formats_with_benign_values(self) -> None:
        keys = response_keys()
        self.assertTrue(keys)
        for key in keys:
            with self.subTest(key=key):
                text = select_response(key, **BENIGN_VALUES)
                self.assertIsInstance(text, str)
                self.assertTrue(text)
                self.assertNotIn("{", text)
                self.assertNotIn("}", text)

    def test_unknown_key_raises_unknown_response(self) -> None:
        with self.assertRaises(UnknownResponse):
            select_response("not-a-key")

    def test_all_exercise_keys_exist_for_the_twelve_items(self) -> None:
        keys = set(response_keys())
        self.assertEqual(len(EXERCISE_IDS), 12)
        for exercise_id in EXERCISE_IDS:
            for prefix in ("present", "correct", "incorrect"):
                key = f"{prefix}.{exercise_id}"
                with self.subTest(key=key):
                    self.assertIn(key, keys)
                    self.assertTrue(select_response(key, **BENIGN_VALUES))

    def test_formatting_is_deterministic(self) -> None:
        for key in response_keys():
            with self.subTest(key=key):
                self.assertEqual(
                    select_response(key, **BENIGN_VALUES),
                    select_response(key, **BENIGN_VALUES),
                )

    def test_snapshot_session_keys_are_approved(self) -> None:
        self.assertEqual(
            select_response("review_prompt"),
            "Ask me to review your worksheet.",
        )
        self.assertEqual(
            select_response("review_request"),
            "Let me look at your worksheet.",
        )
        self.assertEqual(
            select_response("placement_retry"),
            "Please place the whole sheet in the camera view. "
            "Say ready when it is there.",
        )
        self.assertEqual(
            select_response("ask_section"),
            "Which section is that, A or B?",
        )
        self.assertEqual(
            select_response("ask_step"),
            "What do you think the first step is?",
        )
        self.assertEqual(
            select_response("ready_with_exercise"),
            "Tell me your next step when you are ready.",
        )

    def test_worksheet_summary_is_exact_and_names_no_exercise_ids(self) -> None:
        summary = select_response("worksheet_summary")

        self.assertEqual(
            summary,
            "I can see the worksheet. Section A is addition and subtraction. "
            "Section B is multiplication and division.",
        )
        for exercise_id in EXERCISE_IDS:
            with self.subTest(exercise_id=exercise_id):
                self.assertNotIn(exercise_id, summary)

    def test_placement_prompts_are_exact(self) -> None:
        self.assertEqual(
            select_response("placement_missing"),
            "I cannot see the worksheet. Please place the whole sheet in the "
            "camera view. Say ready when it is there.",
        )
        self.assertEqual(
            select_response("placement_partial"),
            "I can only see part of the worksheet. Please move the camera so "
            "the whole sheet fits. Say ready when it is there.",
        )
        self.assertEqual(
            select_response("placement_unreadable"),
            "I cannot read the worksheet clearly. Please move it closer and "
            "keep it steady. Say ready when it is there.",
        )
        self.assertEqual(
            select_response("placement_different"),
            "This does not look like our practice worksheet. Please show the "
            "grade three practice sheet. Say ready when it is there.",
        )

    def test_placement_prompt_maps_each_status_and_falls_back(self) -> None:
        for status, key in (
            ("missing", "placement_missing"),
            ("partial", "placement_partial"),
            ("unreadable", "placement_unreadable"),
            ("different_sheet", "placement_different"),
        ):
            with self.subTest(status=status):
                self.assertEqual(
                    placement_prompt(status), select_response(key)
                )
        for status in ("ready", "unknown", ""):
            with self.subTest(status=status):
                self.assertEqual(
                    placement_prompt(status),
                    select_response("placement_retry"),
                )

    def test_uncertain_prompts_are_exact(self) -> None:
        self.assertEqual(
            select_response("reading_blank"),
            "I cannot see an answer yet. Please write your answer and say ready.",
        )
        self.assertEqual(
            select_response("reading_obscured"),
            "I cannot see the answer clearly. Please move your hand or shadow "
            "away and say ready.",
        )
        self.assertEqual(
            select_response("reading_overwritten"),
            "That answer is hard to read. Please rewrite it clearly and say ready.",
        )
        self.assertEqual(
            select_response("reading_multiple"),
            "I can see more than one answer. Please show just the answer you "
            "want me to check.",
        )
        self.assertEqual(
            select_response("reading_wrong_item"),
            "I cannot find the answer for this item. Please show the answer "
            "space for this exercise.",
        )

    def test_uncertain_prompt_maps_visibility_and_falls_back(self) -> None:
        for visibility, key in (
            ("blank", "reading_blank"),
            ("obscured", "reading_obscured"),
            ("overwritten", "reading_overwritten"),
            ("multiple_answer", "reading_multiple"),
            ("wrong_item", "reading_wrong_item"),
        ):
            with self.subTest(visibility=visibility):
                self.assertEqual(
                    uncertain_prompt(visibility), select_response(key)
                )
        for visibility in ("clear", "unknown", ""):
            with self.subTest(visibility=visibility):
                self.assertEqual(
                    uncertain_prompt(visibility),
                    select_response("unclear"),
                )

    def test_spoken_only_fallback_is_exact(self) -> None:
        self.assertEqual(
            select_response("spoken_only_fallback"),
            "I can check what you said, but I cannot read your writing yet.",
        )

    def test_worksheet_list_key_is_removed(self) -> None:
        self.assertNotIn("worksheet_list", response_keys())


class NumberGuardTests(unittest.TestCase):
    def test_numbers_in_extracts_every_integer(self) -> None:
        self.assertEqual(numbers_in("Add 4 and 5, then 15."), {4, 5, 15})
        self.assertEqual(numbers_in("Add the ones"), set())

    def test_guard_accepts_only_verified_numbers(self) -> None:
        self.assertTrue(guard_numbers("Add 4 and 5", {4, 5, 6}))
        self.assertTrue(guard_numbers("Add the ones", set()))

    def test_guard_rejects_unverified_number(self) -> None:
        self.assertFalse(guard_numbers("The answer is 99", {15}))
        self.assertFalse(guard_numbers("Add 4 and 5", {4}))

    def test_numbers_in_reads_number_words(self) -> None:
        self.assertEqual(numbers_in("The answer is fifteen and 3."), {15, 3})
        self.assertEqual(numbers_in("eighty-seven"), {87})

    def test_guard_rejects_a_word_number(self) -> None:
        self.assertFalse(guard_numbers("The answer is fifteen", {14}))


class GuidanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.lesson = load_lesson(
            Path(__file__).parents[1] / "agent" / "lessons" / "grade3_demo.yaml"
        )

    def test_guidance_never_echoes_wrong_answer(self) -> None:
        exercise = self.lesson.get("A1")
        check = check_answer(exercise.verification_expression, "14")
        text = guidance_for(exercise, check)
        self.assertNotIn(14, numbers_in(text))
        self.assertLessEqual(numbers_in(text), verified_numbers(exercise, check))

    def test_guidance_uses_step_index(self) -> None:
        exercise = self.lesson.get("A1")
        check = check_answer(exercise.verification_expression, "14")
        self.assertEqual(guidance_for(exercise, check, step_index=2), "Add 6 to 9")

    def test_guidance_never_speaks_a_partial_student_answer(self) -> None:
        exercise = self.lesson.get("A1")
        check = check_answer(exercise.verification_expression, "9")
        text = guidance_for(exercise, check)
        self.assertNotIn(9, numbers_in(text))
        self.assertLessEqual(numbers_in(text), verified_numbers(exercise, check))

    def test_guidance_unknown_step_index_uses_first_unreached_step(self) -> None:
        exercise = self.lesson.get("A1")
        check = check_answer(exercise.verification_expression, "14")
        self.assertFalse(guard_numbers("Say 99", verified_numbers(exercise, check)))
        self.assertEqual(guidance_for(exercise, check, step_index=99), "Add 4 and 5")

    def test_present_and_praise_numbers_are_verified(self) -> None:
        for exercise in self.lesson.exercises:
            # No student answer: `verified_numbers` discards it by contract,
            # and for B6 the answer (5) is also a printed operand.
            check = check_answer(exercise.verification_expression, None)
            allowed = verified_numbers(exercise, check)
            with self.subTest(exercise=exercise.id):
                presented = select_response(
                    f"present.{exercise.id}", problem=exercise.problem
                )
                praised = select_response(
                    f"correct.{exercise.id}", praise=exercise.praise
                )
                self.assertLessEqual(numbers_in(presented), allowed)
                self.assertLessEqual(numbers_in(praised), allowed)


if __name__ == "__main__":
    unittest.main()
