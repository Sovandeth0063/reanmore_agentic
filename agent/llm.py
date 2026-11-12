"""Structured intent classification through local Ollama."""

from __future__ import annotations

import json
from dataclasses import dataclass

import httpx

from agent.config import Settings

VALID_INTENTS = {
    "REVIEW",
    "READY",
    "CHOOSE_EXERCISE",
    "ASK_STEP",
    "REPEAT",
    "CHECK_WRITING",
    "CHECK_SPOKEN_ANSWER",
    "NEXT",
    "DONE",
    "LIST_WORKSHEET",
    "OFF_TOPIC",
    "UNCLEAR",
}
VALID_EXERCISES = {f"{section}{number}" for section in "AB" for number in range(1, 7)}
VALID_SECTIONS = {"A", "B"}
VALID_ITEMS = range(1, 7)

_ALIASED_INTENTS = {"CHOOSE": "CHOOSE_EXERCISE"}

_SYSTEM_PROMPT = (
    "Return JSON only. Fields: intent, exercise_id, candidate_answer, "
    "guidance_step, section, number. "
    "intent is exactly one of REVIEW, READY, CHOOSE_EXERCISE, ASK_STEP, "
    "REPEAT, CHECK_WRITING, CHECK_SPOKEN_ANSWER, NEXT, DONE, "
    "LIST_WORKSHEET, OFF_TOPIC, UNCLEAR. "
    "section is A or B and number is 1 to 6. A bare number such as "
    "'number two' has exercise_id null and section null; never guess a "
    "section. When the student is working on paper, 'check my answer' means "
    "CHECK_WRITING. Use CHECK_SPOKEN_ANSWER only for a clearly spoken number "
    "with no paper reference. Use only the supplied exercise and state. "
    "Never state an unverified number."
)


class IntentError(ValueError):
    """Raised when Ollama returns an invalid intent."""


@dataclass(frozen=True)
class TutorIntent:
    intent: str
    exercise_id: str | None
    candidate_answer: str | None
    guidance_step: int | None
    section: str | None = None
    number: int | None = None


class OllamaClient:
    def __init__(self, settings: Settings, http=None) -> None:
        self.settings = settings
        self.http = http

    def interpret(self, transcript: str, state: dict, exercise: dict) -> TutorIntent:
        if self.http is None:
            raise IntentError("No Ollama HTTP client configured")
        payload = {
            "model": self.settings.ollama_model,
            "format": "json",
            "stream": False,
            "messages": [
                {
                    "role": "system",
                    "content": _SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "transcript": transcript,
                            "state": state,
                            "state_block": state.get("state_block"),
                            "exercise": exercise,
                        }
                    ),
                },
            ],
        }
        try:
            response = self.http.post(
                self.settings.ollama_base_url.rstrip("/") + "/api/chat",
                json=payload,
            )
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise IntentError("Ollama request failed") from error
        try:
            data = json.loads(response.json()["message"]["content"])
        except (
            KeyError,
            IndexError,
            TypeError,
            AttributeError,
            json.JSONDecodeError,
        ) as error:
            raise IntentError("Ollama returned an invalid response") from error
        if not isinstance(data, dict):
            raise IntentError("Ollama returned an invalid response")
        candidate_answer = data.get("candidate_answer")
        if candidate_answer is not None:
            candidate_answer = str(candidate_answer)
            if not candidate_answer.strip():
                candidate_answer = None
        intent = data.get("intent")
        if not isinstance(intent, str):
            raise IntentError("Unknown tutor intent")
        # Legacy aliases normalize before the vocabulary check.
        if intent == "CHECK_ANSWER":
            intent = (
                "CHECK_SPOKEN_ANSWER"
                if candidate_answer is not None
                else "CHECK_WRITING"
            )
        else:
            intent = _ALIASED_INTENTS.get(intent, intent)
        if intent not in VALID_INTENTS:
            raise IntentError("Unknown tutor intent")
        exercise_id = data.get("exercise_id")
        if exercise_id is not None:
            exercise_id = str(exercise_id).strip().upper()
            if exercise_id not in VALID_EXERCISES:
                raise IntentError("Exercise is outside the fixed worksheet")
        section = data.get("section")
        if section is not None:
            if not isinstance(section, str):
                raise IntentError("Section is invalid")
            section = section.strip().upper()
            if section not in VALID_SECTIONS:
                raise IntentError("Section is outside the fixed worksheet")
        number = data.get("number")
        if number is not None:
            try:
                number = int(number)
            except (TypeError, ValueError) as error:
                raise IntentError("Number is invalid") from error
            if number not in VALID_ITEMS:
                raise IntentError("Number is outside the fixed worksheet")
        if (
            exercise_id is not None
            and section is not None
            and number is not None
            and f"{section}{number}" != exercise_id
        ):
            raise IntentError("Exercise fields disagree")
        guidance_step = data.get("guidance_step")
        if guidance_step is not None:
            try:
                guidance_step = int(guidance_step)
            except (TypeError, ValueError) as error:
                raise IntentError("Guidance step is invalid") from error
            valid_steps = {
                int(step.get("index", 0)) for step in exercise.get("steps", [])
            }
            if valid_steps and guidance_step not in valid_steps:
                raise IntentError("Guidance step is outside the current exercise")
        return TutorIntent(
            intent=intent,
            exercise_id=exercise_id,
            candidate_answer=candidate_answer,
            guidance_step=guidance_step,
            section=section,
            number=number,
        )
