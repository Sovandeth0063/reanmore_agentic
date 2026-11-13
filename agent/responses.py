"""Fixed, approved response catalog."""

from __future__ import annotations

import re

from agent.calculator import CheckResult, parse_number, steps_for, verified_numbers
from agent.lesson import Exercise


class UnknownResponse(KeyError):
    """Raised when a response key is not approved."""


_NUMBER_SPAN = re.compile(r"\d+|[a-z]+")


def numbers_in(text: str) -> set[int]:
    """Every integer spoken in ``text``, as digits or English number words.

    Number words cover 0-100, including hyphenated and space-separated tens
    and ones (``eighty-seven``, ``twenty one``) and ``one hundred``. Words
    that are not numbers are ignored.
    """
    tokens = _NUMBER_SPAN.findall(text.lower())
    values: set[int] = set()
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.isdigit():
            values.add(int(token))
            index += 1
            continue
        if index + 1 < len(tokens):
            pair = parse_number(f"{token} {tokens[index + 1]}")
            if pair is not None:
                values.add(pair)
                index += 2
                continue
        value = parse_number(token)
        if value is not None:
            values.add(value)
        index += 1
    return values


def guard_numbers(text: str, allowed: set[int]) -> bool:
    """True when every integer in ``text`` is verified."""
    return numbers_in(text) <= set(allowed)


def guidance_for(
    exercise: Exercise,
    check: CheckResult,
    step_index: int | None = None,
) -> str:
    """Step-anchored guidance that never speaks an unverified number."""
    steps = steps_for(exercise)
    step = _select_guidance_step(steps, check, step_index)
    if step is not None and guard_numbers(step.prompt, verified_numbers(exercise, check)):
        return step.prompt
    return check.focus


def _select_guidance_step(steps, check: CheckResult, step_index: int | None):
    """Requested step, else the first step not yet reached, else step 1."""
    if step_index is not None:
        for step in steps:
            if step.index == step_index:
                return step
    reached = [
        step
        for step in steps
        if check.student_answer is not None
        and step.expected_intermediate == check.student_answer
    ]
    if reached:
        last_index = max(step.index for step in reached)
        for step in steps:
            if step.index > last_index:
                return step
    return steps[0] if steps else None


_RESPONSES = {
    "greeting": "Hi! We will solve some math together.",
    "review_prompt": "Ask me to review your worksheet.",
    "review_request": "Let me look at your worksheet.",
    "placement_retry": (
        "Please place the whole sheet in the camera view. "
        "Say ready when it is there."
    ),
    "placement_missing": (
        "I cannot see the worksheet. Please place the whole sheet in the "
        "camera view. Say ready when it is there."
    ),
    "placement_partial": (
        "I can only see part of the worksheet. Please move the camera so the "
        "whole sheet fits. Say ready when it is there."
    ),
    "placement_unreadable": (
        "I cannot read the worksheet clearly. Please move it closer and keep "
        "it steady. Say ready when it is there."
    ),
    "placement_different": (
        "This does not look like our practice worksheet. Please show the grade "
        "three practice sheet. Say ready when it is there."
    ),
    "worksheet_summary": (
        "I can see the worksheet. Section A is addition and subtraction. "
        "Section B is multiplication and division."
    ),
    "ask_choice": "Which section and number would you like to start with?",
    "ask_section": "Which section is that, A or B?",
    "ask_step": "What do you think the first step is?",
    "ready_with_exercise": "Tell me your next step when you are ready.",
    "check_request": "I am looking at your answer now.",
    "unclear": "I could not read that clearly. Can you say or write it again?",
    "reading_blank": (
        "I cannot see an answer yet. Please write your answer and say ready."
    ),
    "reading_obscured": (
        "I cannot see the answer clearly. Please move your hand or shadow away "
        "and say ready."
    ),
    "reading_overwritten": (
        "That answer is hard to read. Please rewrite it clearly and say ready."
    ),
    "reading_multiple": (
        "I can see more than one answer. Please show just the answer you want "
        "me to check."
    ),
    "reading_wrong_item": (
        "I cannot find the answer for this item. Please show the answer space "
        "for this exercise."
    ),
    "spoken_only_fallback": (
        "I can check what you said, but I cannot read your writing yet."
    ),
    "repeat": "I will say that again. {text}",
    "off_topic": "Let's stay with our math worksheet.",
    "wrap_up": "You worked hard today. Great job!",
    "service_error": "I need a moment to check the worksheet. Please try again.",
}
for _exercise in [f"{section}{number}" for section in "AB" for number in range(1, 7)]:
    _RESPONSES[f"present.{_exercise}"] = "Let's work on {problem}."
    _RESPONSES[f"correct.{_exercise}"] = "That answer is correct. {praise}"
    _RESPONSES[f"incorrect.{_exercise}"] = "Let's check the next step: {focus}"


def select_response(key: str, **values: object) -> str:
    try:
        template = _RESPONSES[key]
    except KeyError as error:
        raise UnknownResponse(key) from error
    return template.replace("{items}", str(values.get("items", ""))).replace(
        "{text}", str(values.get("text", ""))
    ).replace("{problem}", str(values.get("problem", ""))).replace(
        "{praise}", str(values.get("praise", ""))
    ).replace("{focus}", str(values.get("focus", "")))


def response_keys() -> tuple[str, ...]:
    return tuple(_RESPONSES)


_PLACEMENT_PROMPTS = {
    "missing": "placement_missing",
    "partial": "placement_partial",
    "unreadable": "placement_unreadable",
    "different_sheet": "placement_different",
}


def placement_prompt(status: str) -> str:
    """Ask for a specific adjustment; anything unknown uses the retry line."""
    return select_response(_PLACEMENT_PROMPTS.get(status, "placement_retry"))


_UNCERTAIN_PROMPTS = {
    "blank": "reading_blank",
    "obscured": "reading_obscured",
    "overwritten": "reading_overwritten",
    "multiple_answer": "reading_multiple",
    "wrong_item": "reading_wrong_item",
}


def uncertain_prompt(visibility: str) -> str:
    """Ask for a clearer answer; never mark an uncertain read wrong."""
    return select_response(_UNCERTAIN_PROMPTS.get(visibility, "unclear"))
