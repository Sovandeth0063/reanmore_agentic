import unittest
from pathlib import Path

from agent.lesson import UnknownExercise, load_lesson


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


if __name__ == "__main__":
    unittest.main()
