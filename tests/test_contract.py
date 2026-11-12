"""Contract tests for the snapshot session API and its TypeScript mirror."""

import json
import unittest
from pathlib import Path

from server.contract import (
    AUDIO_CHANNELS,
    AUDIO_CONTENT_TYPES,
    AUDIO_FORM_FIELD,
    AUDIO_SAMPLE_RATE,
    AUDIO_SAMPLE_WIDTH,
    CAPTURE_REQUESTS,
    CONTRACT_VERSION,
    ERROR_CODES,
    EXERCISE_ID_FORM_FIELD,
    IMAGE_CONTENT_TYPES,
    IMAGE_FORM_FIELD,
    JPEG_MAGIC,
    MAX_AUDIO_BYTES,
    MAX_AUDIO_SECONDS,
    MAX_IMAGE_BYTES,
    PURPOSE_FORM_FIELD,
    SESSION_CREATE_PATH,
    SESSION_END_PATH,
    SESSION_SNAPSHOT_PATH,
    SESSION_TURN_PATH,
    STATUSES,
    ContractError,
    SessionResponse,
    ended_payload,
    error_payload,
    validate_audio,
    validate_image,
    validate_purpose,
)

TS_CONTRACT = Path(__file__).resolve().parents[1] / "web" / "src" / "contract.ts"
VALID_JPEG = JPEG_MAGIC + b"\xe0" + b"contract-test-image"


class ContractVocabularyTests(unittest.TestCase):
    def test_contract_version_is_one(self) -> None:
        self.assertEqual(CONTRACT_VERSION, 1)

    def test_status_vocabulary_is_exact(self) -> None:
        self.assertEqual(
            STATUSES,
            (
                "ready",
                "listening",
                "checking_sheet",
                "adjust_sheet",
                "reading_work",
                "speaking",
            ),
        )

    def test_capture_vocabulary_is_exact(self) -> None:
        self.assertEqual(CAPTURE_REQUESTS, ("review", "check"))

    def test_error_codes_are_stable(self) -> None:
        self.assertEqual(
            ERROR_CODES,
            (
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
            ),
        )

    def test_typescript_contract_declares_python_vocabulary(self) -> None:
        source = TS_CONTRACT.read_text(encoding="utf-8")

        self.assertIn("CONTRACT_VERSION = 1", source)
        for status in STATUSES:
            self.assertIn(f'"{status}"', source)
        for capture in CAPTURE_REQUESTS:
            self.assertIn(f'"{capture}"', source)
        for code in ERROR_CODES:
            self.assertIn(f'"{code}"', source)

    def test_target_routes_and_form_fields(self) -> None:
        self.assertEqual(SESSION_CREATE_PATH, "/sessions")
        self.assertEqual(SESSION_TURN_PATH, "/sessions/{session_id}/turn")
        self.assertEqual(SESSION_SNAPSHOT_PATH, "/sessions/{session_id}/snapshot")
        self.assertEqual(SESSION_END_PATH, "/sessions/{session_id}")
        self.assertEqual(AUDIO_FORM_FIELD, "audio")
        self.assertEqual(IMAGE_FORM_FIELD, "image")
        self.assertEqual(PURPOSE_FORM_FIELD, "purpose")
        self.assertEqual(EXERCISE_ID_FORM_FIELD, "exercise_id")


class SessionResponseTests(unittest.TestCase):
    def test_valid_response_serializes_contract_version(self) -> None:
        response = SessionResponse(
            session_id="session-1",
            tutor_text="Which section and number?",
            status="listening",
            capture_request=None,
            exercise_id=None,
        )
        payload = response.to_payload()

        self.assertEqual(
            payload,
            {
                "contract_version": 1,
                "session_id": "session-1",
                "tutor_text": "Which section and number?",
                "status": "listening",
                "capture_request": None,
                "exercise_id": None,
            },
        )

    def test_capture_request_and_exercise_are_optional(self) -> None:
        response = SessionResponse(
            session_id="session-1",
            tutor_text="Show me A2.",
            status="checking_sheet",
            capture_request="check",
            exercise_id="A2",
        )
        payload = response.to_payload()

        self.assertEqual(payload["capture_request"], "check")
        self.assertEqual(payload["exercise_id"], "A2")

    def test_invalid_status_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            SessionResponse(
                session_id="session-1",
                tutor_text="hello",
                status="thinking",
            )

    def test_invalid_capture_request_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            SessionResponse(
                session_id="session-1",
                tutor_text="hello",
                status="listening",
                capture_request="snapshot",
            )

    def test_empty_session_id_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            SessionResponse(session_id="", tutor_text="hello", status="ready")

    def test_end_payload_has_contract_version(self) -> None:
        self.assertEqual(
            ended_payload("session-1"),
            {
                "contract_version": 1,
                "session_id": "session-1",
                "ended": True,
            },
        )


class AudioContractTests(unittest.TestCase):
    def test_constants_match_raw_pcm16le(self) -> None:
        self.assertEqual(AUDIO_SAMPLE_RATE, 16000)
        self.assertEqual(AUDIO_CHANNELS, 1)
        self.assertEqual(AUDIO_SAMPLE_WIDTH, 2)
        self.assertEqual(MAX_AUDIO_SECONDS, 15)
        self.assertEqual(MAX_AUDIO_BYTES, 480000)
        self.assertEqual(
            MAX_AUDIO_BYTES,
            AUDIO_SAMPLE_RATE
            * AUDIO_CHANNELS
            * AUDIO_SAMPLE_WIDTH
            * MAX_AUDIO_SECONDS,
        )

    def test_accepts_supported_content_types_with_parameters(self) -> None:
        data = b"\x01\x02" * 160
        for content_type in AUDIO_CONTENT_TYPES:
            with self.subTest(content_type=content_type):
                self.assertIs(
                    validate_audio(data, f"{content_type}; rate=16000; channels=1"),
                    data,
                )

    def test_accepts_exactly_the_size_limit(self) -> None:
        data = b"\x00" * MAX_AUDIO_BYTES

        self.assertIs(validate_audio(data, "audio/l16"), data)

    def test_rejects_unsupported_audio_format(self) -> None:
        with self.assertRaises(ContractError) as error:
            validate_audio(b"\x00\x00", "audio/mpeg")

        self.assertEqual(error.exception.code, "unsupported_audio_format")
        self.assertEqual(error.exception.status_code, 415)

    def test_rejects_missing_audio_format(self) -> None:
        with self.assertRaises(ContractError) as error:
            validate_audio(b"\x00\x00", None)

        self.assertEqual(error.exception.code, "unsupported_audio_format")

    def test_rejects_empty_audio(self) -> None:
        with self.assertRaises(ContractError) as error:
            validate_audio(b"", "audio/l16")

        self.assertEqual(error.exception.code, "empty_audio")
        self.assertEqual(error.exception.status_code, 400)

    def test_rejects_odd_length_audio(self) -> None:
        with self.assertRaises(ContractError) as error:
            validate_audio(b"\x00\x00\x00", "audio/pcm")

        self.assertEqual(error.exception.code, "invalid_request")
        self.assertEqual(error.exception.status_code, 400)

    def test_rejects_over_limit_audio(self) -> None:
        with self.assertRaises(ContractError) as error:
            validate_audio(b"\x00" * (MAX_AUDIO_BYTES + 2), "audio/x-pcm")

        self.assertEqual(error.exception.code, "audio_too_long")
        self.assertEqual(error.exception.status_code, 413)


class ImageContractTests(unittest.TestCase):
    def test_accepts_jpeg_for_both_purposes(self) -> None:
        for content_type in IMAGE_CONTENT_TYPES:
            for purpose in CAPTURE_REQUESTS:
                with self.subTest(content_type=content_type, purpose=purpose):
                    self.assertIs(
                        validate_image(VALID_JPEG, content_type, purpose),
                        VALID_JPEG,
                    )

    def test_accepts_content_type_parameters(self) -> None:
        self.assertIs(
            validate_image(
                VALID_JPEG, "image/jpeg; charset=binary", "review"
            ),
            VALID_JPEG,
        )

    def test_rejects_unsupported_image_type(self) -> None:
        with self.assertRaises(ContractError) as error:
            validate_image(VALID_JPEG, "image/png", "review")

        self.assertEqual(error.exception.code, "unsupported_image_format")
        self.assertEqual(error.exception.status_code, 415)

    def test_rejects_missing_image_type(self) -> None:
        with self.assertRaises(ContractError) as error:
            validate_image(VALID_JPEG, None, "review")

        self.assertEqual(error.exception.code, "unsupported_image_format")

    def test_rejects_non_jpeg_magic_bytes(self) -> None:
        with self.assertRaises(ContractError) as error:
            validate_image(b"\x89PNG\r\n\x1a\n", "image/jpeg", "review")

        self.assertEqual(error.exception.code, "unsupported_image_format")
        self.assertEqual(error.exception.status_code, 415)

    def test_rejects_empty_image(self) -> None:
        with self.assertRaises(ContractError) as error:
            validate_image(b"", "image/jpeg", "check")

        self.assertEqual(error.exception.code, "invalid_request")
        self.assertEqual(error.exception.status_code, 400)

    def test_rejects_over_limit_image(self) -> None:
        oversized = VALID_JPEG + b"\x00" * MAX_IMAGE_BYTES
        with self.assertRaises(ContractError) as error:
            validate_image(oversized, "image/jpeg", "check")

        self.assertEqual(error.exception.code, "payload_too_large")
        self.assertEqual(error.exception.status_code, 413)

    def test_rejects_wrong_purpose(self) -> None:
        for purpose in ("snapshot", "review ", "", None):
            with self.subTest(purpose=purpose):
                with self.assertRaises(ContractError) as error:
                    validate_image(VALID_JPEG, "image/jpeg", purpose)

                self.assertEqual(error.exception.code, "wrong_purpose")
                self.assertEqual(error.exception.status_code, 400)

    def test_validate_purpose_accepts_exact_values(self) -> None:
        for purpose in CAPTURE_REQUESTS:
            with self.subTest(purpose=purpose):
                self.assertEqual(validate_purpose(purpose), purpose)


class ErrorPayloadTests(unittest.TestCase):
    def test_error_payload_has_only_code_and_message(self) -> None:
        error = ContractError(
            "provider_unavailable", "Vision provider is unavailable", 503
        )
        payload = error_payload(error)

        self.assertEqual(
            payload,
            {
                "error": {
                    "code": "provider_unavailable",
                    "message": "Vision provider is unavailable",
                }
            },
        )
        self.assertEqual(set(payload), {"error"})
        self.assertEqual(set(payload["error"]), {"code", "message"})

    def test_validation_error_does_not_echo_secret_or_media(self) -> None:
        secret = "vision-key-value"
        with self.assertRaises(ContractError) as error:
            validate_audio(b"\x00\x00", f"audio/mpeg; key={secret}")

        rendered = json.dumps(error_payload(error.exception))
        self.assertNotIn(secret, rendered)
        self.assertNotIn("\x00", rendered)

    def test_error_payload_serializes_to_json(self) -> None:
        rendered = json.dumps(
            error_payload(ContractError("invalid_session", "Session not found", 404))
        )

        self.assertEqual(
            json.loads(rendered),
            {"error": {"code": "invalid_session", "message": "Session not found"}},
        )


if __name__ == "__main__":
    unittest.main()
