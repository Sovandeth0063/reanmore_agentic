"""Load and resolve the fixed twelve-exercise worksheet."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml


class UnknownExercise(ValueError):
    """Raised for an exercise outside the fixed worksheet."""


@dataclass(frozen=True)
class Step:
    index: int
    prompt: str
    expected_intermediate: int | None


@dataclass(frozen=True)
class Exercise:
    id: str
    section: str
    item: int
    problem: str
    answer: int
    verification_expression: str
    steps: tuple[Step, ...]
    praise: str


class Lesson:
    def __init__(self, exercises: tuple[Exercise, ...]) -> None:
        ids = [exercise.id for exercise in exercises]
        expected_ids = {f"{section}{number}" for section in "AB" for number in range(1, 7)}
        if len(exercises) != 12 or set(ids) != expected_ids:
            raise ValueError("The worksheet must contain the fixed twelve exercises")
        for exercise in exercises:
            from agent.calculator import evaluate

            result = evaluate(exercise.verification_expression)
            if not result.ok or result.value != exercise.answer:
                raise ValueError(f"Invalid answer for exercise {exercise.id}")
        self._by_id = {exercise.id: exercise for exercise in exercises}
        self._exercises = exercises

    def get(self, exercise_id: str) -> Exercise:
        try:
            return self._by_id[exercise_id.upper()]
        except KeyError as error:
            raise UnknownExercise(exercise_id) from error

    def choice_candidates(self, text: str) -> tuple[str, ...]:
        """Every exercise a spoken choice could mean.

        A section plus number (``A2``, ``section A, number two``) is
        unambiguous. A bare number (``number two``) matches the item in both
        sections, so the caller must ask which section.
        """
        normalized = re.sub(r"[^a-z0-9 ]", " ", text.lower())
        normalized = re.sub(r"\s+", " ", normalized).strip()
        match = re.search(
            r"\b([ab])\s*(?:number\s*)?(one|two|three|four|five|six|[1-6])\b",
            normalized,
        )
        if match:
            number = _number(match.group(2))
            return (f"{match.group(1).upper()}{number}",)
        match = re.search(
            r"\b(?:number|the)?\s*(one|two|three|four|five|six|[1-6])\s*(?:one)?\b",
            normalized,
        )
        if match and not re.search(r"\b[ab]\b", normalized):
            number = _number(match.group(1))
            return tuple(
                exercise.id
                for exercise in self._exercises
                if exercise.item == number
            )
        compact = normalized.replace(" ", "").upper()
        return (compact,) if compact in self._by_id else ()

    def resolve_choice(self, text: str) -> str | None:
        candidates = self.choice_candidates(text)
        return candidates[0] if len(candidates) == 1 else None

    @property
    def exercises(self) -> tuple[Exercise, ...]:
        return self._exercises


def _number(value: str) -> int:
    words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}
    return words[value] if value in words else int(value)


def load_lesson(path: str | Path) -> Lesson:
    with Path(path).open(encoding="utf-8") as file:
        data = yaml.safe_load(file)
    exercises = tuple(
        Exercise(
            id=str(item["id"]),
            section=str(item["section"]),
            item=int(item["item"]),
            problem=str(item["problem"]),
            answer=int(item["answer"]),
            verification_expression=str(item["verification_expression"]),
            steps=tuple(
                Step(
                    index=int(step["index"]),
                    prompt=str(step["prompt"]),
                    expected_intermediate=step.get("expected_intermediate"),
                )
                for step in item.get("steps", [])
            ),
            praise=str(item.get("praise", "Nice work!")),
        )
        for item in data["exercises"]
    )
    return Lesson(exercises)
