"""Shared request/response contract for the snapshot tutor API.

Target transport (Task 21 implements the endpoints):

* ``POST /sessions`` -- JSON body (currently empty). Returns a
  :class:`SessionResponse` payload.
* ``POST /sessions/{session_id}/turn`` -- ``multipart/form-data`` with one
  ``audio`` file part: raw PCM16LE, no container, see the audio constants.
  Returns a :class:`SessionResponse` payload.
* ``POST /sessions/{session_id}/snapshot`` -- ``multipart/form-data`` with an
  ``image`` file part (JPEG), a ``purpose`` text field (``review`` or
  ``check``), and an optional ``exercise_id`` text field. Returns a
  :class:`SessionResponse` payload.
* ``DELETE /sessions/{session_id}`` -- no body. Returns
  ``{contract_version, session_id, ended}``.

Only the create request uses JSON. Audio and image uploads are multipart form
data so the browser can stream one file part per request. The contract module
carries no provider text, credentials, or raw media.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


CONTRACT_VERSION = 1

STATUS_READY = "ready"
STATUS_LISTENING = "listening"
STATUS_CHECKING_SHEET = "checking_sheet"
STATUS_ADJUST_SHEET = "adjust_sheet"
STATUS_READING_WORK = "reading_work"
STATUS_SPEAKING = "speaking"

STATUSES: tuple[str, ...] = (
    STATUS_READY,
    STATUS_LISTENING,
    STATUS_CHECKING_SHEET,
    STATUS_ADJUST_SHEET,
    STATUS_READING_WORK,
    STATUS_SPEAKING,
)

CAPTURE_REVIEW = "review"
CAPTURE_CHECK = "check"
CAPTURE_REQUESTS: tuple[str, ...] = (CAPTURE_REVIEW, CAPTURE_CHECK)

# Raw PCM16LE. Browsers may label the same bytes with any of these types.
AUDIO_SAMPLE_RATE = 16000
AUDIO_CHANNELS = 1
AUDIO_SAMPLE_WIDTH = 2
MAX_AUDIO_SECONDS = 15
MAX_AUDIO_BYTES = (
    AUDIO_SAMPLE_RATE * AUDIO_CHANNELS * AUDIO_SAMPLE_WIDTH * MAX_AUDIO_SECONDS
)
AUDIO_CONTENT_TYPES: tuple[str, ...] = ("audio/l16", "audio/pcm", "audio/x-pcm")

MAX_IMAGE_BYTES = 4 * 1024 * 1024
IMAGE_CONTENT_TYPES: tuple[str, ...] = ("image/jpeg", "image/jpg")
JPEG_MAGIC = b"\xff\xd8\xff"

ERROR_CODES: tuple[str, ...] = (
    "invalid_session",
    "invalid_request",
    "unsupported_audio_format",
    "unsupported_image_format",
    "payload_too_large",
    "audio_too_long",
    "empty_audio",
    "wrong_purpose",
    "not_allowed_in_state",
    "provider_unavailable",
)

SESSION_CREATE_PATH = "/sessions"
SESSION_TURN_PATH = "/sessions/{session_id}/turn"
SESSION_SNAPSHOT_PATH = "/sessions/{session_id}/snapshot"
SESSION_END_PATH = "/sessions/{session_id}"

AUDIO_FORM_FIELD = "audio"
IMAGE_FORM_FIELD = "image"
PURPOSE_FORM_FIELD = "purpose"
EXERCISE_ID_FORM_FIELD = "exercise_id"


class ContractError(Exception):
    """A client-facing failure with a stable code and safe message."""

    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def error_payload(error: ContractError) -> dict[str, dict[str, str]]:
    """Serialize an error without provider text, keys, or media."""
    return {"error": {"code": error.code, "message": error.message}}


@dataclass(frozen=True)
class SessionResponse:
    """One versioned tutor response; ``to_payload`` adds the contract version."""

    session_id: str
    tutor_text: str
    status: str
    capture_request: str | None = None
    exercise_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.session_id, str) or not self.session_id:
            raise ValueError("session_id must be a non-empty string")
        if not isinstance(self.tutor_text, str):
            raise ValueError("tutor_text must be a string")
        if self.status not in STATUSES:
            raise ValueError("status is not part of the shared contract")
        if self.capture_request is not None and (
            self.capture_request not in CAPTURE_REQUESTS
        ):
            raise ValueError("capture_request is not part of the shared contract")
        if self.exercise_id is not None and (
            not isinstance(self.exercise_id, str) or not self.exercise_id
        ):
            raise ValueError("exercise_id must be a non-empty string or null")

    def to_payload(self) -> dict[str, Any]:
        return {
            "contract_version": CONTRACT_VERSION,
            "session_id": self.session_id,
            "tutor_text": self.tutor_text,
            "status": self.status,
            "capture_request": self.capture_request,
            "exercise_id": self.exercise_id,
        }


def ended_payload(session_id: str) -> dict[str, Any]:
    """Payload for ``DELETE /sessions/{session_id}``."""
    if not isinstance(session_id, str) or not session_id:
        raise ValueError("session_id must be a non-empty string")
    return {
        "contract_version": CONTRACT_VERSION,
        "session_id": session_id,
        "ended": True,
    }


def _base_content_type(content_type: str | None) -> str:
    if not isinstance(content_type, str):
        return ""
    return content_type.split(";", 1)[0].strip().lower()


def validate_purpose(purpose: str | None) -> str:
    """Accept exactly ``review`` or ``check``."""
    if purpose not in CAPTURE_REQUESTS:
        raise ContractError(
            "wrong_purpose",
            "purpose must be review or check",
            400,
        )
    return purpose


def validate_audio(data: bytes, content_type: str | None) -> bytes:
    """Validate one raw PCM16LE utterance and return the same bytes."""
    if _base_content_type(content_type) not in AUDIO_CONTENT_TYPES:
        raise ContractError(
            "unsupported_audio_format",
            "audio must be raw PCM16LE (audio/l16, audio/pcm, or audio/x-pcm)",
            415,
        )
    if not data:
        raise ContractError("empty_audio", "audio payload is empty", 400)
    if len(data) % AUDIO_SAMPLE_WIDTH:
        raise ContractError(
            "invalid_request",
            "audio must contain whole 16-bit samples",
            400,
        )
    if len(data) > MAX_AUDIO_BYTES:
        raise ContractError(
            "audio_too_long",
            f"audio must be at most {MAX_AUDIO_SECONDS} seconds",
            413,
        )
    return data


def validate_image(
    data: bytes, content_type: str | None, purpose: str | None
) -> bytes:
    """Validate one still image for the requested capture purpose."""
    validate_purpose(purpose)
    if _base_content_type(content_type) not in IMAGE_CONTENT_TYPES:
        raise ContractError(
            "unsupported_image_format",
            "image must be JPEG (image/jpeg or image/jpg)",
            415,
        )
    if not data:
        raise ContractError("invalid_request", "image payload is empty", 400)
    if len(data) > MAX_IMAGE_BYTES:
        raise ContractError(
            "payload_too_large",
            f"image must be at most {MAX_IMAGE_BYTES} bytes",
            413,
        )
    if not data.startswith(JPEG_MAGIC):
        raise ContractError(
            "unsupported_image_format",
            "image is not a valid JPEG",
            415,
        )
    return data
