"""Deterministic fast path for unambiguous spoken commands.

Only whole commands, the documented safe prefixes, and a complete fixed
exercise id match here. Everything else returns ``None`` so the controller
falls through to the local Ollama classifier. A bare number, a conversational
sentence, or a mixed request is never guessed.
"""

from __future__ import annotations

import re

from agent.llm import TutorIntent

VALID_EXERCISE_IDS = frozenset(
    f"{section}{number}" for section in "AB" for number in range(1, 7)
)

_ITEM_PATTERN = "one|two|three|four|five|six|1|2|3|4|5|6"
_ITEM_NUMBERS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
}

# Whole utterances only: an extra word falls through to the model.
_WHOLE_COMMANDS = {
    "REPEAT": (
        "repeat",
        "say that again",
        "say it again",
        "repeat that please",
    ),
    "READY": ("ready", "im ready", "i am ready", "ready now"),
    "NEXT": ("next", "next one", "next exercise"),
    "DONE": ("done", "im done", "i am done", "finish"),
    "ASK_STEP": (
        "first step",
        "whats the first step",
        "what is the first step",
        "whats the next step",
        "what is the next step",
    ),
}
_COMMAND_BY_PHRASE = {
    phrase: name
    for name, phrases in _WHOLE_COMMANDS.items()
    for phrase in phrases
}

_REVIEW_PREFIXES = (
    "review my worksheet",
    "review the worksheet",
    "look at my worksheet",
)
_REVIEW_TRAILING_WORDS = frozenset(
    {"please", "now", "thanks", "thank", "you", "for", "me"}
)

# A writing check may carry extra words (for example a spoken number), but the
# caller still always asks for a fresh image instead of grading the words.
_CHECK_WRITING_PREFIXES = (
    "check my writing",
    "check my paper",
    "check my work",
)

_ALL_COMMAND_PHRASES = (
    tuple(_COMMAND_BY_PHRASE)
    + _REVIEW_PREFIXES
    + _CHECK_WRITING_PREFIXES
)

_EXERCISE_CHOICE = re.compile(
    rf"^(?:section\s+)?([ab])\s*(?:number\s+)?({_ITEM_PATTERN})$"
)

_APOSTROPHES = ("\u2019", "\u2018", "\u02bc", "`")


def parse_clear_intent(text: str, *, allow_choice: bool) -> TutorIntent | None:
    """Return the canonical intent for an unambiguous command, else ``None``.

    ``allow_choice`` gates only the exercise-id form: a choice still requires a
    confirmed worksheet, exactly like the model path.
    """
    normalized = _normalize(text)
    if not normalized:
        return None
    name = _COMMAND_BY_PHRASE.get(normalized)
    if name is not None:
        return _command_intent(name)
    if _is_prefix_command(
        normalized, _REVIEW_PREFIXES, _REVIEW_TRAILING_WORDS
    ):
        return _command_intent("REVIEW")
    if _is_prefix_command(normalized, _CHECK_WRITING_PREFIXES, None):
        return _command_intent("CHECK_WRITING")
    if allow_choice:
        return _parse_exercise_choice(normalized)
    return None


def _normalize(text: str) -> str:
    """Lowercase, drop punctuation and apostrophes, collapse whitespace."""
    if not isinstance(text, str):
        return ""
    lowered = text.casefold()
    for mark in _APOSTROPHES:
        lowered = lowered.replace(mark, "")
    lowered = lowered.replace("'", "")
    # Apostrophes are removed above so "I'm" becomes "im", not "i m".
    cleaned = re.sub(r"[^a-z0-9 ]+", " ", lowered)
    return re.sub(r"\s+", " ", cleaned).strip()


def _command_intent(name: str) -> TutorIntent:
    """No candidate answer: a clear command never carries a spoken number."""
    return TutorIntent(name, None, None, None)


def _is_prefix_command(
    normalized: str,
    prefixes: tuple[str, ...],
    trailing_words: frozenset[str] | None,
) -> bool:
    for prefix in prefixes:
        if normalized != prefix and not normalized.startswith(prefix + " "):
            continue
        remainder = normalized[len(prefix):].strip()
        if trailing_words is not None:
            if all(word in trailing_words for word in remainder.split()):
                return True
            continue
        if not _contains_command(remainder):
            return True
    return False


def _contains_command(text: str) -> bool:
    """True when ``text`` embeds another accepted command (a mixed request)."""
    tokens = text.split()
    for phrase in _ALL_COMMAND_PHRASES:
        words = phrase.split()
        width = len(words)
        for start in range(len(tokens) - width + 1):
            if tokens[start:start + width] == words:
                return True
    return False


def _parse_exercise_choice(normalized: str) -> TutorIntent | None:
    match = _EXERCISE_CHOICE.match(normalized)
    if match is None:
        return None
    section = match.group(1).upper()
    number = _item_number(match.group(2))
    exercise_id = f"{section}{number}"
    if exercise_id not in VALID_EXERCISE_IDS:
        return None
    return TutorIntent(
        intent="CHOOSE_EXERCISE",
        exercise_id=exercise_id,
        candidate_answer=None,
        guidance_step=None,
        section=section,
        number=number,
    )


def _item_number(value: str) -> int:
    return _ITEM_NUMBERS.get(value, int(value) if value.isdigit() else 0)
