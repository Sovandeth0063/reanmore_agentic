"""Structured intent classification with a hosted route and local fallback.

Clear commands never reach this module: ``agent/intent_parser.py`` answers them
deterministically. The ambiguous remainder goes to the configured classifier
(Haiku through the OpenCode Go OpenAI-compatible route by default in `.env`) and
falls back once to local Ollama when the hosted call fails. Both paths share one
JSON parser and one validation table, so the tutor sees the same vocabulary and
the same worksheet bounds.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from agent.config import Settings

VALID_INTENTS = {
    "REVIEW",
    "READY",
    "CHOOSE_EXERCISE",
    "ASK_STEP",
    "HELP",
    "ASK_ANSWER",
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

# The hosted classifier is not retried; a transport failure falls back once.
_INTENT_TIMEOUT_SECONDS = 10.0

_SYSTEM_PROMPT = (
    "Return JSON only. Fields: intent, exercise_id, candidate_answer, "
    "guidance_step, section, number. "
    "intent is exactly one of REVIEW, READY, CHOOSE_EXERCISE, ASK_STEP, HELP, "
    "ASK_ANSWER, REPEAT, CHECK_WRITING, CHECK_SPOKEN_ANSWER, NEXT, DONE, "
    "LIST_WORKSHEET, OFF_TOPIC, UNCLEAR. "
    "'I don't understand', 'help me', or a request for an explanation is "
    "HELP. 'Just tell me the answer' is ASK_ANSWER; encourage another try and "
    "never reveal the answer. "
    "section is A or B and number is 1 to 6. A bare number such as "
    "'number two' has exercise_id null and section null; never guess a "
    "section. When an exercise is already active and the student says only a "
    "number, that is a spoken answer: use CHECK_SPOKEN_ANSWER with "
    "candidate_answer set to the number. Use CHOOSE_EXERCISE only when the "
    "student is choosing an exercise or names a section, such as 'let's do "
    "B2' or 'section B number 2'. When the student is working on paper, "
    "'check my answer' means CHECK_WRITING. Use CHECK_SPOKEN_ANSWER for a "
    "clearly spoken number with no paper reference. Use only the supplied "
    "exercise and state. Never state an unverified number."
)


class IntentError(ValueError):
    """Raised when a classifier returns an invalid intent or cannot be used."""


@dataclass(frozen=True)
class TutorIntent:
    intent: str
    exercise_id: str | None
    candidate_answer: str | None
    guidance_step: int | None
    section: str | None = None
    number: int | None = None


class OllamaClient:
    """Local JSON-mode classifier; also the fallback for the hosted route."""

    provider = "ollama"

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
                    "content": _user_payload(transcript, state, exercise),
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
            content = response.json()["message"]["content"]
        except (
            KeyError,
            IndexError,
            TypeError,
            AttributeError,
            ValueError,
        ) as error:
            raise IntentError("Ollama returned an invalid response") from error
        return _intent_from_content(content, exercise, "Ollama")


class OpenAIIntentClient:
    """Hosted OpenAI-compatible JSON classifier (OpenCode Go route)."""

    provider = "opencode"

    def __init__(
        self, settings: Settings, http=None, *, session_id: str | None = None
    ) -> None:
        self.settings = settings
        self.http = http
        self.session_id = session_id or uuid.uuid4().hex

    def interpret(self, transcript: str, state: dict, exercise: dict) -> TutorIntent:
        if self.http is None:
            raise IntentError("No intent HTTP client configured")
        settings = self.settings
        api_key = settings.intent_api_key or settings.vision_api_key
        if not settings.intent_model or not settings.intent_base_url:
            raise IntentError("Intent provider is not configured")
        if not api_key:
            raise IntentError("Intent provider is not configured")
        # The demo's stable attribution headers belong only to the OpenCode
        # inference host; another OpenAI-compatible host must not receive them.
        headers = {"Authorization": "Bearer " + api_key}
        if _is_opencode_host(settings.intent_base_url):
            headers["User-Agent"] = "ai-math-tutor-demo/0.1"
            headers["x-opencode-session"] = self.session_id
        payload = {
            "model": settings.intent_model,
            "messages": [
                {
                    "role": "system",
                    "content": _SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": _user_payload(transcript, state, exercise),
                },
            ],
            "response_format": {"type": "json_object"},
            "stream": False,
        }
        try:
            response = self.http.post(
                settings.intent_base_url.rstrip("/") + "/chat/completions",
                headers=headers,
                json=payload,
                timeout=_INTENT_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise IntentError("Intent request failed") from error
        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (
            KeyError,
            IndexError,
            TypeError,
            AttributeError,
            ValueError,
        ) as error:
            raise IntentError("Intent returned an invalid response") from error
        return _intent_from_content(content, exercise, "Intent")


class FallbackIntentClient:
    """Try the primary classifier once, then the local model once.

    ``provider`` names the client that served the last successful call, so the
    controller's single ``intent.interpret`` row shows the real provider. If
    both calls fail, the primary error is raised so the caller keeps returning
    the existing retryable service response.
    """

    def __init__(self, primary, fallback) -> None:
        self.primary = primary
        self.fallback = fallback
        self.provider = getattr(primary, "provider", "opencode")

    def interpret(self, transcript: str, state: dict, exercise: dict) -> TutorIntent:
        try:
            intent = self.primary.interpret(transcript, state, exercise)
        except (IntentError, httpx.HTTPError, OSError) as primary_error:
            try:
                intent = self.fallback.interpret(transcript, state, exercise)
            except (IntentError, httpx.HTTPError, OSError):
                if isinstance(primary_error, IntentError):
                    raise primary_error
                raise IntentError("Intent request failed") from primary_error
            self.provider = getattr(self.fallback, "provider", "ollama")
            return intent
        self.provider = getattr(self.primary, "provider", "opencode")
        return intent


def build_intent_client(
    settings: Settings, http=None, *, session_id: str | None = None
):
    """Select the configured classifier, with the local fallback when hosted.

    The runtime and the provider checker share this selection so the live check
    exercises the same route the session will use.
    """
    if getattr(settings, "intent_provider", "ollama") == "opencode":
        return FallbackIntentClient(
            OpenAIIntentClient(settings, http=http, session_id=session_id),
            OllamaClient(settings, http=http),
        )
    return OllamaClient(settings, http=http)


def _user_payload(transcript: str, state: dict, exercise: dict) -> str:
    """The user message: transcript, compact state, and answer-free exercise."""
    return json.dumps(
        {
            "transcript": transcript,
            "state": state,
            "state_block": state.get("state_block"),
            "exercise": exercise,
        }
    )


def _intent_from_content(content: object, exercise: dict, label: str) -> TutorIntent:
    """Decode one classifier reply, tolerating a Markdown fence."""
    if not isinstance(content, str):
        raise IntentError(f"{label} returned an invalid response")
    try:
        data = json.loads(_strip_markdown_fence(content))
    except (TypeError, ValueError) as error:
        raise IntentError(f"{label} returned an invalid response") from error
    return _intent_from_data(data, exercise, label)


def _intent_from_data(data: object, exercise: dict, label: str) -> TutorIntent:
    """Shared vocabulary, worksheet, and slot validation for every client."""
    if not isinstance(data, dict):
        raise IntentError(f"{label} returned an invalid response")
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


def _is_opencode_host(base_url: str) -> bool:
    """True only for the opencode.ai inference host, never a lookalike."""
    return (urlparse(base_url).hostname or "") == "opencode.ai"


def _strip_markdown_fence(text: str) -> str:
    """Remove a leading/trailing Markdown code fence some gateways add."""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    body = stripped[3:]
    first_newline = body.find("\n")
    if first_newline == -1:
        return stripped
    body = body[first_newline + 1 :]
    trimmed = body.rstrip()
    if trimmed.endswith("```"):
        body = trimmed[:-3]
    return body.strip()
