import unittest
from pathlib import Path

from agent.calculator import (
    check_answer,
    evaluate,
    normalize,
    steps_for,
    verified_numbers,
)
from agent.lesson import load_lesson

DOCUMENTED_ERROR_TYPES = {
    "addition_error",
    "subtraction_error",
    "multiplication_table_error",
    "division_error",
    "off_by_one",
    "digit_reversal",
    "carry_borrow_error",
    "wrong_operation",
}


class CalculatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.lesson = load_lesson(Path(__file__).parents[1] / "agent" / "lessons" / "grade3_demo.yaml")

    def test_fixed_worksheet_answers(self) -> None:
        expressions = {
            "4 + 5 + 6": 15, "63 + 24": 87, "85 - 33": 52,
            "71 - 8": 63, "63 - 5": 58, "100 - 48": 52,
            "6 * 4": 24, "8 * 3": 24, "9 * 3": 27,
            "20 / 4": 5, "80 / 10": 8, "25 / 5": 5,
        }
        for expression, expected in expressions.items():
            with self.subTest(expression=expression):
                result = evaluate(expression)
                self.assertTrue(result.ok)
                self.assertEqual(result.value, expected)

    def test_precedence_parentheses_and_large_numbers(self) -> None:
        self.assertEqual(evaluate("1000 + 2000 * 3").value, 7000)
        self.assertEqual(evaluate("(1000 + 2000) * 3").value, 9000)

    def test_rejects_unsafe_or_invalid_expression(self) -> None:
        for expression in ("1 / 0", "1 / 2", "1.5 + 2", "__import__('os')", "1 ** 2"):
            with self.subTest(expression=expression):
                self.assertFalse(evaluate(expression).ok)

    def test_answer_error_types(self) -> None:
        self.assertEqual(check_answer("85 - 33", "25").error_type, "digit_reversal")
        self.assertEqual(check_answer("63 + 24", "86").error_type, "off_by_one")
        self.assertEqual(check_answer("100 - 48", "51").error_type, "carry_borrow_error")
        self.assertEqual(check_answer("6 * 4", "20").error_type, "multiplication_table_error")
        self.assertEqual(check_answer("20 / 4", "6").error_type, "division_error")

    def test_mixed_operation_wrong_answer_does_not_raise(self) -> None:
        cases = (("2 + 3 * 4", "20"), ("63 + 24 + 1", "90"), ("10 - 2 - 3", "6"))
        for expression, answer in cases:
            with self.subTest(expression=expression, answer=answer):
                result = check_answer(expression, answer)
                self.assertFalse(result.correct)
                self.assertIsInstance(result.error_type, str)
                self.assertNotEqual(result.error_type, "unreadable")

    def test_error_precedence_matches_contract(self) -> None:
        cases = (
            # 1. digit_reversal, even when a carry or borrow is also present.
            ("85 - 33", "25", "digit_reversal"),
            ("100 - 48", "25", "digit_reversal"),
            # 2. carry_borrow_error, before off_by_one and operation labels.
            ("100 - 48", "51", "carry_borrow_error"),
            ("4 + 5 + 6", "14", "carry_borrow_error"),
            # 3. division_error, before off_by_one and multiplication.
            ("20 / 4", "6", "division_error"),
            # 4. multiplication_table_error.
            ("6 * 4", "20", "multiplication_table_error"),
            # 5. off_by_one only when no earlier label applies.
            ("63 + 24", "86", "off_by_one"),
            # 6. operation families as the final fallback.
            ("63 + 24", "90", "addition_error"),
            ("85 - 33", "60", "subtraction_error"),
            ("5", "8", "wrong_operation"),
        )
        for expression, answer, expected_type in cases:
            with self.subTest(expression=expression, answer=answer):
                self.assertEqual(check_answer(expression, answer).error_type, expected_type)

    def test_every_sheet_item_wrong_by_one_classifies(self) -> None:
        self.assertEqual(len(self.lesson.exercises), 12)
        for exercise in self.lesson.exercises:
            with self.subTest(exercise=exercise.id):
                result = check_answer(exercise.verification_expression, exercise.answer + 1)
                self.assertFalse(result.correct)
                self.assertNotEqual(result.error_type, "unreadable")
                self.assertIn(result.error_type, DOCUMENTED_ERROR_TYPES)

    def test_check_answer_never_raises_for_evaluable_expressions(self) -> None:
        expressions = [exercise.verification_expression for exercise in self.lesson.exercises]
        expressions.extend(("2 + 3 * 4", "63 + 24 + 1", "10 - 2 - 3", "1000 + 2000 * 3", "5"))
        for expression in expressions:
            expected = evaluate(expression).value
            self.assertIsNotNone(expected)
            answers = {expected - 11, expected - 2, expected - 1, expected + 1, expected + 10}
            for answer in sorted(answers) + [None, "not a number", 1.5]:
                with self.subTest(expression=expression, answer=answer):
                    self.assertIsInstance(check_answer(expression, answer).error_type, str)

    def test_guards_return_unreadable_without_raising(self) -> None:
        cases = (("__import__('os')", "0"), ("1 / 0", "0"), ("1 / 2", "0"), ("4 + 5", None),
                 ("4 + 5", "five"), ("4 + 5", 1.5))
        for expression, answer in cases:
            with self.subTest(expression=expression, answer=answer):
                result = check_answer(expression, answer)
                self.assertFalse(result.correct)
                self.assertEqual(result.error_type, "unreadable")
                self.assertIsNone(result.expected)
        self.assertEqual(evaluate("1 / 2").error, "malformed_expression")

    def test_steps_fallback_never_exposes_unverified_value(self) -> None:
        self.assertIsNone(steps_for({"verification_expression": "1 / 0"})[0].expected_intermediate)

    def test_normalize_maps_operators_and_whitespace(self) -> None:
        self.assertEqual(normalize("6 X 4"), normalize("6 * 4"))
        self.assertEqual(normalize("6 × 4"), "6*4")
        self.assertEqual(normalize("80 ÷ 10"), "80/10")
        self.assertEqual(normalize(" A2 "), "a2")

    def test_normalize_treats_unicode_glyphs_as_operators(self) -> None:
        self.assertEqual(normalize("6 × 4"), normalize("6 x 4"))
        self.assertEqual(normalize("20 ÷ 4"), normalize("20 / 4"))

    def test_steps_for_uses_production_exercise(self) -> None:
        exercise = self.lesson.get("A1")
        steps = steps_for(exercise)
        self.assertEqual([step.index for step in steps], [1, 2])
        self.assertEqual(steps[0].prompt, "Add 4 and 5")
        self.assertEqual(steps[0].expected_intermediate, 9)

    def test_verified_numbers_excludes_student_answer(self) -> None:
        exercise = self.lesson.get("A3")
        check = check_answer(exercise.verification_expression, "25")
        numbers = verified_numbers(exercise, check)
        self.assertNotIn(25, numbers)
        self.assertIn(52, numbers)

    def test_verified_numbers_excludes_answer_even_when_it_is_an_operand(self) -> None:
        exercise = self.lesson.get("A2")
        check = check_answer(exercise.verification_expression, "63")
        numbers = verified_numbers(exercise, check)
        self.assertNotIn(63, numbers)
        self.assertIn(87, numbers)

    def test_verified_numbers_include_printed_operands_and_steps(self) -> None:
        exercise = self.lesson.get("A1")
        numbers = verified_numbers(exercise)
        self.assertEqual(numbers, {4, 5, 6, 9, 15})


if __name__ == "__main__":
    unittest.main()