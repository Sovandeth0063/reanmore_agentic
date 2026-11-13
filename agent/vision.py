"""Structured worksheet and handwriting reads with a hosted vision provider."""

from __future__ import annotations

import base64
import json
import math
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

from agent.config import Settings
from agent.sheet_layout import ITEM_IDS


class VisionError(RuntimeError):
    """Base class for vision failures."""


class VisionUnavailableError(VisionError):
    """Raised when the configured vision provider cannot be used."""


PLACEMENT_READY = "ready"
PLACEMENT_MISSING = "missing"
PLACEMENT_PARTIAL = "partial"
PLACEMENT_UNREADABLE = "unreadable"
PLACEMENT_DIFFERENT_SHEET = "different_sheet"
# A model answer we could not recognize. It is deliberately not a status the
# model may return: content checks decide the real placement instead.
PLACEMENT_UNKNOWN = "unknown"
PLACEMENT_STATUSES = frozenset(
    {
        PLACEMENT_READY,
        PLACEMENT_MISSING,
        PLACEMENT_PARTIAL,
        PLACEMENT_UNREADABLE,
        PLACEMENT_DIFFERENT_SHEET,
    }
)

VISIBILITY_CLEAR = "clear"
VISIBILITY_BLANK = "blank"
VISIBILITY_OBSCURED = "obscured"
VISIBILITY_OVERWRITTEN = "overwritten"
VISIBILITY_MULTIPLE_ANSWER = "multiple_answer"
VISIBILITY_WRONG_ITEM = "wrong_item"
# An unrecognized visibility is treated as uncertain, never as clear.
VISIBILITY_UNCLEAR = "unclear"
VISIBILITY_STATUSES = frozenset(
    {
        VISIBILITY_CLEAR,
        VISIBILITY_BLANK,
        VISIBILITY_OBSCURED,
        VISIBILITY_OVERWRITTEN,
        VISIBILITY_MULTIPLE_ANSWER,
        VISIBILITY_WRONG_ITEM,
    }
)


@dataclass(frozen=True)
class ParsedItem:
    item: str
    section: str
    problem: str
    expression: str


@dataclass(frozen=True)
class WorksheetParse:
    items: list[ParsedItem]
    confidence: float
    placement: str = PLACEMENT_READY
    reason: str = ""


@dataclass(frozen=True)
class HandwritingRead:
    raw_text: str
    value: str | None
    confidence: float
    visible_work: str
    visibility: str = VISIBILITY_CLEAR
    location: str = ""
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class AnswerArea:
    """The selected item's area and the sheet corners in the full photo."""

    item_id: str
    box: tuple[float, float, float, float]
    corners: tuple[tuple[float, float], ...]
    confidence: float
    reason: str = ""


LOCATE_INSTRUCTION = (
    "Locate the selected item's answer area in this full worksheet photo. "
    "Return JSON with item_id, box, corners, confidence, and reason. box is "
    "[x0, y0, x1, y1] normalized to the full photo for the selected item's "
    "answer area; it is used to confirm which item the answer belongs to, not "
    "to bound the later crop. corners are the sheet's outer corners as four "
    "[x, y] points in top-left, top-right, bottom-right, bottom-left order, "
    "normalized to the full photo. confidence must be a number from 0 to 1, "
    "for example 0.9, never a word. reason is a short explanation."
)


class VisionClient:
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

    def parse_worksheet(self, image_bytes: bytes) -> WorksheetParse:
        payload = self._request(
            image_bytes,
            "Return JSON with placement, reason, items "
            "[{item: \"A1\"..\"B6\", section: \"A\" or \"B\", problem: the "
            "printed expression, expression: the bare arithmetic expression "
            "without \"=\" or the answer blank}], and confidence. confidence "
            "must be a number from 0 to 1, for example 0.9, never a word. "
            "placement must be exactly one of ready, missing, partial, "
            "unreadable, different_sheet; do not describe the sheet's "
            "position.",
        )
        if not isinstance(payload, dict):
            raise VisionError("Vision returned an invalid response")
        placement = payload.get("placement")
        if placement is None:
            placement = PLACEMENT_READY
        elif not isinstance(placement, str) or placement not in PLACEMENT_STATUSES:
            placement = PLACEMENT_UNKNOWN
        reason = str(payload.get("reason") or "")[:160]
        items = payload.get("items")
        confidence = payload.get("confidence")
        if not isinstance(items, list) or not isinstance(confidence, (int, float)):
            raise VisionError("Vision returned an invalid worksheet shape")
        parsed = [
            ParsedItem(
                item=str(entry["item"]),
                section=str(entry["section"]),
                problem=str(entry["problem"]),
                expression=_clean_expression(entry["expression"]),
            )
            for entry in items
            if isinstance(entry, dict)
            and {"item", "section", "problem", "expression"} <= entry.keys()
        ]
        if len(parsed) != len(items):
            raise VisionError("Vision returned an invalid worksheet item")
        return WorksheetParse(parsed, float(confidence), placement, reason)

    def locate_answer_area(self, image_bytes: bytes, exercise: dict) -> AnswerArea:
        """Locate the selected item's printed box and the sheet's corners."""
        payload = self._request(image_bytes, LOCATE_INSTRUCTION, exercise)
        if not isinstance(payload, dict):
            raise VisionError("Vision returned an invalid response")
        item_id = payload.get("item_id")
        if not isinstance(item_id, str) or item_id.strip().upper() not in ITEM_IDS:
            raise VisionError("Vision returned an invalid item id")
        box = _normalized_box(payload.get("box"))
        if box is None:
            raise VisionError("Vision returned an invalid answer area")
        corners = _normalized_corners(payload.get("corners"))
        if corners is None:
            raise VisionError("Vision returned invalid sheet corners")
        confidence = payload.get("confidence")
        if not _finite_number(confidence):
            raise VisionError("Vision returned an invalid answer area confidence")
        return AnswerArea(
            item_id=item_id.strip().upper(),
            box=box,
            corners=corners,
            confidence=float(confidence),
            reason=str(payload.get("reason") or "")[:160],
        )

    def read_handwriting(self, image_bytes: bytes, exercise: dict) -> HandwritingRead:
        payload = self._request(
            image_bytes,
            "Read only the answer area for the given item. Return JSON with "
            "raw_text, value, confidence, visible_work, visibility, location, "
            "and reasons. confidence must be a number from 0 to 1, for "
            "example 0.9, never a word. visibility must be exactly one of "
            "clear, blank, obscured, overwritten, multiple_answer, wrong_item.",
            exercise,
        )
        if not isinstance(payload, dict):
            raise VisionError("Vision returned an invalid response")
        visibility = payload.get("visibility")
        if visibility is None:
            visibility = VISIBILITY_CLEAR
        elif (
            not isinstance(visibility, str)
            or visibility not in VISIBILITY_STATUSES
        ):
            visibility = VISIBILITY_UNCLEAR
        value = payload.get("value")
        if value is not None and not isinstance(value, str):
            value = str(value)
        confidence = payload.get("confidence")
        if not isinstance(confidence, (int, float)):
            raise VisionError("Vision returned an invalid handwriting confidence")
        return HandwritingRead(
            raw_text=str(payload.get("raw_text", "")),
            value=value,
            confidence=float(confidence),
            visible_work=str(payload.get("visible_work", "")),
            visibility=visibility,
            location=str(payload.get("location") or "")[:160],
            reasons=_reason_strings(payload.get("reasons")),
        )

    def _request(
        self, image_bytes: bytes, instruction: str, exercise: dict | None = None
    ) -> dict[str, Any]:
        local = self.settings.vision_provider == "local"
        gemini = False
        if local:
            if not self.settings.vision_model:
                raise VisionUnavailableError("Local vision model is not configured")
            endpoint = self.settings.ollama_base_url.rstrip("/") + "/api/chat"
            headers = {}
        else:
            if not self.settings.vision_model or not self.settings.vision_api_key:
                raise VisionUnavailableError("Hosted vision is not configured")
            if not self.settings.vision_base_url:
                raise VisionUnavailableError("Hosted vision base URL is not configured")
            gemini = self.settings.vision_api == "gemini"
            if gemini:
                endpoint = (
                    self.settings.vision_base_url.rstrip("/")
                    + f"/models/{self.settings.vision_model}:generateContent"
                )
            else:
                endpoint = (
                    self.settings.vision_base_url.rstrip("/") + "/chat/completions"
                )
            headers = {"Authorization": "Bearer " + self.settings.vision_api_key}
            # The Go inference route attributes traffic to a stable demo
            # session. Only opencode.ai owns these headers; other hosted
            # providers and local Ollama must not receive them.
            if _is_opencode_host(self.settings.vision_base_url):
                headers.update(
                    {
                        "User-Agent": "ai-math-tutor-demo/0.1",
                        "x-opencode-session": self.session_id,
                    }
                )
        if self.http is None:
            raise VisionUnavailableError("No vision HTTP client configured")
        image = base64.b64encode(image_bytes).decode("ascii")
        mime_type = _detect_image_mime(image_bytes)
        prompt = json.dumps({"instruction": instruction, "exercise": exercise})
        if gemini:
            request = {
                "contents": [
                    {
                        "role": "user",
                        "parts": [
                            {"text": prompt},
                            {
                                "inline_data": {
                                    "mime_type": mime_type,
                                    "data": image,
                                }
                            },
                        ],
                    }
                ],
                "generationConfig": {"responseMimeType": "application/json"},
            }
        else:
            request = {
                "model": self.settings.vision_model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": prompt,
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{mime_type};base64,{image}"
                                },
                            },
                        ],
                    }
                ],
                "response_format": {"type": "json_object"},
                "stream": False,
            }
            if local:
                request["messages"][0]["content"] = prompt
                request["messages"][0]["images"] = [image]
        try:
            response = self.http.post(endpoint, headers=headers, json=request)
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            if local or gemini or not _is_response_format_rejection(error):
                raise VisionUnavailableError("Vision request failed") from error
            retry_request = {
                key: value
                for key, value in request.items()
                if key != "response_format"
            }
            try:
                response = self.http.post(
                    endpoint, headers=headers, json=retry_request
                )
                response.raise_for_status()
            except httpx.HTTPError as retry_error:
                raise VisionUnavailableError("Vision request failed") from retry_error
        except httpx.HTTPError as error:
            raise VisionUnavailableError("Vision request failed") from error
        try:
            body = response.json()
            if gemini:
                message = _gemini_text(body)
            else:
                message = (
                    body["choices"][0]["message"]["content"]
                    if "choices" in body
                    else body["message"]["content"]
                )
            return json.loads(_strip_markdown_fence(message))
        except (
            KeyError,
            IndexError,
            TypeError,
            AttributeError,
            json.JSONDecodeError,
        ) as error:
            raise VisionError("Vision returned an invalid response") from error


def _is_opencode_host(base_url: str) -> bool:
    """True only for the opencode.ai inference host, never a lookalike."""
    return (urlparse(base_url).hostname or "") == "opencode.ai"


def _clean_expression(value: object) -> str:
    """Drop a printed answer blank such as ``= ____`` from an expression."""
    text = str(value).partition("=")[0]
    return text.replace("_", "").strip()


def _detect_image_mime(image_bytes: bytes) -> str:
    """Label the payload from its magic bytes: PNG, otherwise JPEG."""
    return "image/png" if image_bytes.startswith(b"\x89PNG") else "image/jpeg"


def _gemini_text(body: dict) -> str:
    """Concatenate the candidate's text parts; missing parts fail the parse."""
    parts = body["candidates"][0]["content"]["parts"]
    return "".join(
        part["text"]
        for part in parts
        if isinstance(part, dict) and isinstance(part.get("text"), str)
    )


def _is_response_format_rejection(error: httpx.HTTPStatusError) -> bool:
    """Return True when a 400 body blames the optional response_format field."""
    if error.response.status_code != 400:
        return False
    try:
        body = error.response.text
    except (AttributeError, RuntimeError, ValueError):
        body = ""
    return "response_format" in body


def _finite_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _normalized_box(value: object) -> tuple[float, float, float, float] | None:
    """Four ordered normalized coordinates, or None for a malformed area."""
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
        return None
    if len(value) != 4 or not all(_finite_number(entry) for entry in value):
        return None
    x0, y0, x1, y1 = (float(entry) for entry in value)
    if not (0.0 <= x0 < x1 <= 1.0 and 0.0 <= y0 < y1 <= 1.0):
        return None
    return (x0, y0, x1, y1)


def _normalized_corners(
    value: object,
) -> tuple[tuple[float, float], ...] | None:
    """Four ordered, in-range points forming a non-degenerate convex quad."""
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
        return None
    if len(value) != 4:
        return None
    points = []
    for point in value:
        if isinstance(point, (str, bytes)) or not isinstance(point, (list, tuple)):
            return None
        if len(point) != 2 or not all(_finite_number(entry) for entry in point):
            return None
        x, y = float(point[0]), float(point[1])
        if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
            return None
        points.append((x, y))
    if _quad_area(points) <= 1e-9:
        return None
    for index in range(4):
        ax, ay = points[index]
        bx, by = points[(index + 1) % 4]
        cx, cy = points[(index + 2) % 4]
        if (bx - ax) * (cy - by) - (by - ay) * (cx - bx) <= 1e-9:
            return None
    return tuple(points)


def _quad_area(points: list[tuple[float, float]]) -> float:
    return abs(
        sum(
            points[index][0] * points[(index + 1) % 4][1]
            - points[(index + 1) % 4][0] * points[index][1]
            for index in range(4)
        )
    )


def _reason_strings(reasons: object) -> tuple[str, ...]:
    """Keep at most five uncertainty reasons, each capped at 160 characters."""
    if isinstance(reasons, str):
        reasons = [reasons]
    if not isinstance(reasons, (list, tuple)):
        return ()
    values = []
    for reason in reasons[:5]:
        text = str(reason)[:160]
        if text:
            values.append(text)
    return tuple(values)


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
