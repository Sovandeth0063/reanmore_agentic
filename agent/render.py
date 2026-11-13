"""Deterministic template wording with an optional hosted rephrasing pass.

The lesson, calculator, and tutor state machine decide what to teach; this
module only chooses the words. Every hosted reply is checked against the
turn's allowed numbers and falls back to the deterministic template on any
failure, so a slow or wrong model can never change the math.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlparse

import httpx

from agent.config import Settings
from agent.lesson import Exercise, Step
from agent.responses import numbers_in


# Inside the 3.5 s warm-turn budget; a fallback must be faster than a stall.
RENDER_TIMEOUT_SECONDS = 3.0
MAX_RENDER_CHARACTERS = 240
MAX_RENDER_SENTENCES = 4

_SYSTEM_PROMPT = (
    "You are a warm Grade 3 math tutor. Rewrite the given tutor line in two "
    "to four very short, child-friendly sentences. Keep the same teaching "
    "move. Use only numbers from the allowed list. Never state the final "
    'answer or invent a number. Return JSON {"text": "..."}.'
)

# A sentence ends at terminal punctuation followed by whitespace; a decimal
# such as "4.5" has no space and stays inside one sentence.
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class RenderRequest:
    mode: str
    exercise: Exercise
    step: Step | None
    child_answer: str | None
    template_text: str
    allowed_numbers: frozenset[int]


@dataclass(frozen=True)
class RenderResult:
    text: str
    provider: str
    fallback: bool


class Renderer(Protocol):
    def render(self, request: RenderRequest) -> RenderResult: ...


class TemplateRenderer:
    """Offline renderer: the deterministic line is already the answer."""

    provider = "template"

    def render(self, request: RenderRequest) -> RenderResult:
        return RenderResult(request.template_text, self.provider, False)


class HostedRenderer:
    """Rephrase one tutor line through the configured Haiku route."""

    provider = "opencode"

    def __init__(
        self,
        settings: Settings,
        http=None,
        *,
        session_id: str | None = None,
    ) -> None:
        self.settings = settings
        self.http = http
        self.session_id = session_id or uuid.uuid4().hex

    def render(self, request: RenderRequest) -> RenderResult:
        settings = self.settings
        api_key = settings.intent_api_key or settings.vision_api_key
        if (
            self.http is None
            or not settings.intent_model
            or not settings.intent_base_url
            or not api_key
        ):
            return _fallback(request)
        # The demo's stable attribution header belongs only to the OpenCode
        # inference host; another OpenAI-compatible host must not receive it.
        headers = {"Authorization": "Bearer " + api_key}
        if _is_opencode_host(settings.intent_base_url):
            headers["x-opencode-session"] = self.session_id
        payload = {
            "model": settings.intent_model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": _user_payload(request)},
            ],
            "response_format": {"type": "json_object"},
            "stream": False,
        }
        try:
            response = self.http.post(
                settings.intent_base_url.rstrip("/") + "/chat/completions",
                headers=headers,
                json=payload,
                timeout=RENDER_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
        except (
            httpx.HTTPError,
            httpx.InvalidURL,
            OSError,
            KeyError,
            IndexError,
            TypeError,
            AttributeError,
            ValueError,
        ):
            # Never log the reply or the child's answer; fall back silently.
            return _fallback(request)
        text = _text_from_content(content)
        if text is None or not _is_valid(text, request):
            return _fallback(request)
        return RenderResult(text, self.provider, False)


def build_renderer(
    settings: Settings, http=None, *, session_id: str | None = None
) -> Renderer:
    """Select the configured renderer; the safe default is the template."""
    if getattr(settings, "tutor_renderer", "template") == "llm":
        return HostedRenderer(settings, http, session_id=session_id)
    return TemplateRenderer()


def _user_payload(request: RenderRequest) -> str:
    """The user message: mode, problem, step, answer, and the fallback line."""
    return json.dumps(
        {
            "mode": request.mode,
            "problem": request.exercise.problem,
            "step_prompt": request.step.prompt if request.step else None,
            "child_answer": request.child_answer,
            "allowed_numbers": sorted(request.allowed_numbers),
            "template_text": request.template_text,
        }
    )


def _text_from_content(content: object) -> str | None:
    """Decode one JSON reply, tolerating a Markdown fence; None when invalid."""
    if not isinstance(content, str):
        return None
    try:
        data = json.loads(_strip_markdown_fence(content))
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    text = data.get("text")
    if not isinstance(text, str):
        return None
    stripped = text.strip()
    return stripped or None


def _is_valid(text: str, request: RenderRequest) -> bool:
    """One to four short sentences that never speak an unearned number.

    Every number in the reply, as a digit or an English word, must already be
    in the turn's allowed set. This is the strict rule the template path
    applies through ``guard_numbers``; an opt-in hosted rephrasing may not
    speak a math number the lesson did not verify.
    """
    if not text or len(text) > MAX_RENDER_CHARACTERS:
        return False
    if _sentence_count(text) > MAX_RENDER_SENTENCES:
        return False
    return numbers_in(text) <= set(request.allowed_numbers)


def _sentence_count(text: str) -> int:
    return len(
        [part for part in _SENTENCE_BREAK.split(text.strip()) if part.strip()]
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


def _fallback(request: RenderRequest) -> RenderResult:
    return RenderResult(request.template_text, "template", True)
