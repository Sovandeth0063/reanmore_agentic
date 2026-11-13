import unittest
from pathlib import Path

from agent.lesson import Step, UnknownExercise, load_lesson
from agent.responses import numbers_in


class LessonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.lesson = load_lesson(Path(__file__).parents[1] / "agent" / "lessons" / "grade3_demo.yaml")

    def test_contains_fixed_twelve_items(self) -> None:
        self.assertEqual(len(self.lesson.exercises), 12)
        self.assertEqual(self.lesson.get("A1").answer, 15)
        self.assertEqual(self.lesson.get("B6").answer, 5)

    def test_resolves_spoken_choices(self) -> None:
        self.assertEqual(self.lesson.resolve_choice("A one"), "A1")
        self.assertEqual(self.lesson.resolve_choice("exercise B six"), "B6")
        self.assertIsNone(self.lesson.resolve_choice("number one"))

    def test_rejects_unknown_exercise(self) -> None:
        with self.assertRaises(UnknownExercise):
            self.lesson.get("C1")

    def test_every_step_has_two_vetted_hints(self) -> None:
        for exercise in self.lesson.exercises:
            for step in exercise.steps:
                self.assertGreaterEqual(
                    len(step.hints), 2, f"{exercise.id} step {step.index}"
                )
                for hint in step.hints:
                    self.assertTrue(hint.strip(), f"{exercise.id} step {step.index}")
                    self.assertTrue(
                        all(0 <= n <= 100 for n in numbers_in(hint)),
                        f"{exercise.id} step {step.index}: {hint}",
                    )

    def test_hints_never_reveal_the_final_answer(self) -> None:
        for exercise in self.lesson.exercises:
            for step in exercise.steps:
                for hint in step.hints:
                    self.assertNotIn(
                        exercise.answer,
                        numbers_in(hint),
                        f"{exercise.id} step {step.index}: {hint}",
                    )

    def test_step_hints_default_to_empty(self) -> None:
        self.assertEqual(Step(1, "Add 4 and 5", 9).hints, ())


if __name__ == "__main__":
    unittest.main()
