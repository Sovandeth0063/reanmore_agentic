"""The clear-intent parser: accepted phrases, id forms, rejections, cost."""

import time
import unittest

from agent.intent_parser import parse_clear_intent

# Every accepted command phrase, with the canonical intent it must produce.
ACCEPTED_COMMANDS = (
    ("repeat", "REPEAT"),
    ("say that again", "REPEAT"),
    ("say it again", "REPEAT"),
    ("repeat that please", "REPEAT"),
    ("ready", "READY"),
    ("i'm ready", "READY"),
    ("i am ready", "READY"),
    ("ready now", "READY"),
    ("next", "NEXT"),
    ("next one", "NEXT"),
    ("next exercise", "NEXT"),
    ("done", "DONE"),
    ("i'm done", "DONE"),
    ("i am done", "DONE"),
    ("finish", "DONE"),
    ("first step", "ASK_STEP"),
    ("what's the first step", "ASK_STEP"),
    ("what is the first step", "ASK_STEP"),
    ("what's the next step", "ASK_STEP"),
    ("what is the next step", "ASK_STEP"),
    ("review my worksheet", "REVIEW"),
    ("review the worksheet", "REVIEW"),
    ("look at my worksheet", "REVIEW"),
    ("check my writing", "CHECK_WRITING"),
    ("check my paper", "CHECK_WRITING"),
    ("check my work", "CHECK_WRITING"),
)

# Accepted prefixes with tolerated trailing words.
ACCEPTED_PREFIXES = (
    ("review my worksheet please", "REVIEW"),
    ("review the worksheet now", "REVIEW"),
    ("look at my worksheet thanks", "REVIEW"),
    ("check my writing, it's 15", "CHECK_WRITING"),
    ("check my paper, I wrote 15", "CHECK_WRITING"),
    ("check my work please", "CHECK_WRITING"),
)

REJECTED = (
    # Incomplete or out-of-range choices: the section question must still run.
    "number two",
    "number 2",
    "C1",
    "C 1",
    "A7",
    "A0",
    "B8",
    "section C number two",
    "A",
    "1",
    # Context-dependent or conversational: only the model can decide.
    "check my answer",
    "is fifteen right",
    "is 15 right",
    "fifteen",
    "what is a hint",
    "check",
    "review",
    "hello there",
    "can you help me with this problem",
    "I have fifteen",
    # Whole commands only: extra words fall through.
    "repeat the first step please",
    "say that again please no wait next",
    # Mixed commands stay with the model.
    "check my writing and repeat that",
    "repeat and next",
    "next exercise and done",
    "review my worksheet and check my writing",
    # Empty or punctuation-only input.
    "",
    "   ",
    "?!",
)

_ITEM_WORDS = {
    1: "one",
    2: "two",
    3: "three",
    4: "four",
    5: "five",
    6: "six",
}


def exercise_id_forms(exercise_id: str) -> tuple[str, ...]:
    """Every documented spelling of one complete fixed id."""
    section = exercise_id[0]
    number = int(exercise_id[1])
    word = _ITEM_WORDS[number]
    return (
        exercise_id,
        exercise_id.lower(),
        f"{section.lower()} {number}",
        f"section {section} number {word}",
        f"section {section.lower()}, number {number}",
    )


class AcceptedCommandTests(unittest.TestCase):
    def test_every_accepted_phrase_returns_its_canonical_intent(self) -> None:
        for text, expected in ACCEPTED_COMMANDS:
            with self.subTest(text=text):
                intent = parse_clear_intent(text, allow_choice=True)
                self.assertIsNotNone(intent)
                self.assertEqual(intent.intent, expected)
                self.assertIsNone(intent.exercise_id)
                self.assertIsNone(intent.candidate_answer)
                self.assertIsNone(intent.guidance_step)

    def test_case_punctuation_and_whitespace_are_normalized(self) -> None:
        cases = (
            ("Repeat!", "REPEAT"),
            ("  SAY   THAT   AGAIN  ", "REPEAT"),
            ("I\u2019m ready", "READY"),
            ("Ready now.", "READY"),
            ("WHAT IS THE NEXT STEP?", "ASK_STEP"),
            ("check-my-work", "CHECK_WRITING"),
        )
        for text, expected in cases:
            with self.subTest(text=text):
                intent = parse_clear_intent(text, allow_choice=True)
                self.assertIsNotNone(intent)
                self.assertEqual(intent.intent, expected)

    def test_prefixes_tolerate_only_documented_trailing_words(self) -> None:
        for text, expected in ACCEPTED_PREFIXES:
            with self.subTest(text=text):
                intent = parse_clear_intent(text, allow_choice=True)
                self.assertIsNotNone(intent)
                self.assertEqual(intent.intent, expected)

    def test_a_writing_check_never_carries_a_candidate_answer(self) -> None:
        for text in (
            "check my writing",
            "check my paper, I wrote 15",
            "check my work, it's 15",
        ):
            with self.subTest(text=text):
                intent = parse_clear_intent(text, allow_choice=True)
                self.assertIsNotNone(intent)
                self.assertEqual(intent.intent, "CHECK_WRITING")
                # A spoken number is never paper evidence or a spoken check.
                self.assertIsNone(intent.candidate_answer)
                self.assertIsNone(intent.exercise_id)
                self.assertIsNone(intent.section)
                self.assertIsNone(intent.number)


class ExerciseChoiceTests(unittest.TestCase):
    def test_every_id_form_for_the_full_fixed_worksheet(self) -> None:
        for section in "AB":
            for number in range(1, 7):
                exercise_id = f"{section}{number}"
                for text in exercise_id_forms(exercise_id):
                    with self.subTest(text=text):
                        intent = parse_clear_intent(
                            text, allow_choice=True
                        )
                        self.assertIsNotNone(intent)
                        self.assertEqual(intent.intent, "CHOOSE_EXERCISE")
                        self.assertEqual(intent.exercise_id, exercise_id)
                        self.assertEqual(intent.section, section)
                        self.assertEqual(intent.number, number)
                        self.assertIsNone(intent.candidate_answer)

    def test_choice_is_refused_when_choice_is_not_allowed(self) -> None:
        for text in ("A2", "a 2", "section A number two"):
            with self.subTest(text=text):
                self.assertIsNone(
                    parse_clear_intent(text, allow_choice=False)
                )

    def test_commands_still_match_when_choice_is_not_allowed(self) -> None:
        for text, expected in ACCEPTED_COMMANDS:
            with self.subTest(text=text):
                intent = parse_clear_intent(text, allow_choice=False)
                self.assertIsNotNone(intent)
                self.assertEqual(intent.intent, expected)


class RejectionTests(unittest.TestCase):
    def test_unclear_or_context_dependent_text_falls_through(self) -> None:
        for text in REJECTED:
            with self.subTest(text=text):
                self.assertIsNone(parse_clear_intent(text, allow_choice=True))

    def test_non_string_input_falls_through(self) -> None:
        self.assertIsNone(parse_clear_intent(None, allow_choice=True))  # type: ignore[arg-type]

    def test_choice_ids_are_rejected_before_placement(self) -> None:
        for text in ("A1", "B6", "section a, number 2"):
            with self.subTest(text=text):
                self.assertIsNone(
                    parse_clear_intent(text, allow_choice=False)
                )


class CostTests(unittest.TestCase):
    def test_clear_command_set_cost_and_model_calls_avoided(self) -> None:
        phrases = [phrase for phrase, _ in ACCEPTED_COMMANDS]
        for phrase in phrases:
            self.assertIsNotNone(
                parse_clear_intent(phrase, allow_choice=True)
            )

        runs = 200
        hits = 0
        started = time.perf_counter()
        for _ in range(runs):
            for phrase in phrases:
                if parse_clear_intent(phrase, allow_choice=True) is not None:
                    hits += 1
        elapsed = time.perf_counter() - started

        self.assertEqual(hits, runs * len(phrases))
        average_us = elapsed / hits * 1_000_000
        print(
            f"\nintent.fast_path: {len(phrases)} clear turns per pass, "
            f"{len(phrases)} model calls avoided per pass, "
            f"{average_us:.1f} us average parser cost"
        )
        # A pure string match should stay far below a model round trip.
        self.assertLess(average_us, 1000)


if __name__ == "__main__":
    unittest.main()
