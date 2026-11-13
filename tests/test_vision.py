"""Tests for the configurable OpenAI-compatible vision provider."""

import base64
import json
import unittest
from pathlib import Path

import httpx

from agent.config import Settings
from agent.vision import (
    LOCATE_INSTRUCTION,
    PLACEMENT_DIFFERENT_SHEET,
    PLACEMENT_MISSING,
    PLACEMENT_PARTIAL,
    PLACEMENT_READY,
    PLACEMENT_UNKNOWN,
    PLACEMENT_UNREADABLE,
    VISIBILITY_CLEAR,
    VISIBILITY_OBSCURED,
    VISIBILITY_UNCLEAR,
    VisionClient,
    VisionError,
    VisionUnavailableError,
    WorksheetParse,
)

VISION_FILE = Path(__file__).resolve().parents[1] / "agent" / "vision.py"
OPENCODE_BASE_URL = "https://opencode.ai/inference/openai/v1"
ENDPOINT = OPENCODE_BASE_URL + "/chat/completions"
GEMINI_BASE_URL = "https://opencode.ai/inference/go/google/v1beta"
GEMINI_ENDPOINT = (
    GEMINI_BASE_URL + "/models/gemini-4-argon:generateContent"
)
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"png-body"
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"jpeg-body"
# Task 35: without an explicit type the hosted model sometimes answered
# "confidence": "high". Every read instruction must spell out the requirement.
NUMERIC_CONFIDENCE_REQUIREMENT = "confidence must be a number from 0 to 1"


class FakeResponse:
    def __init__(self, body: dict) -> None:
        self.body = body

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.body


class FakeHttp:
    def __init__(self, *responses) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []

    def post(self, url: str, headers=None, **kwargs):
        self.calls.append(
            {
                "method": "POST",
                "url": url,
                "headers": headers,
                "json": kwargs.get("json"),
            }
        )
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def hosted_body(content: str) -> dict:
    return {"choices": [{"message": {"content": content}}]}


def worksheet_items() -> list[dict]:
    """The sheet's twelve parseable items, without asserting the lesson."""
    return [
        {
            "item": f"A{index}",
            "section": "A",
            "problem": "4 + 5 + 6",
            "expression": "4 + 5 + 6",
        }
        for index in range(1, 7)
    ] + [
        {
            "item": f"B{index}",
            "section": "B",
            "problem": "6 x 4",
            "expression": "6 x 4",
        }
        for index in range(1, 7)
    ]


def gemini_body(content: str) -> dict:
    return {"candidates": [{"content": {"parts": [{"text": content}]}}]}


def make_settings(**overrides) -> Settings:
    values = {
        "ollama_model": "model",
        "vision_provider": "hosted",
        "vision_base_url": OPENCODE_BASE_URL,
        "vision_model": "vision-model",
        "vision_api_key": "vision-key",
    }
    values.update(overrides)
    return Settings(**values)


def gemini_settings(**overrides) -> Settings:
    return make_settings(
        vision_api="gemini",
        vision_base_url=GEMINI_BASE_URL,
        vision_model="gemini-4-argon",
        **overrides,
    )


class VisionEndpointTests(unittest.TestCase):
    def test_vision_posts_to_configured_endpoint(self) -> None:
        http = FakeHttp(
            FakeResponse(hosted_body(json.dumps({"items": [], "confidence": 0.9})))
        )
        client = VisionClient(make_settings(), http)

        parsed = client.parse_worksheet(b"image-bytes")

        self.assertEqual(len(http.calls), 1)
        self.assertEqual(http.calls[0]["url"], ENDPOINT)
        self.assertEqual(http.calls[0]["headers"]["Authorization"], "Bearer vision-key")
        self.assertEqual(parsed.confidence, 0.9)

    def test_client_defaults_to_a_generated_stable_session_id(self) -> None:
        client = VisionClient(make_settings(), FakeHttp())

        self.assertEqual(len(client.session_id), 32)
        int(client.session_id, 16)
        self.assertEqual(client.session_id, client.session_id)
        self.assertNotEqual(
            client.session_id,
            VisionClient(make_settings(), FakeHttp()).session_id,
        )

    def test_go_route_sends_demo_headers_with_session_id(self) -> None:
        go_base = "https://opencode.ai/inference/go/openai/v1"
        http = FakeHttp(
            FakeResponse(hosted_body(json.dumps({"items": [], "confidence": 0.9})))
        )
        client = VisionClient(
            make_settings(vision_base_url=go_base),
            http,
            session_id="session-123",
        )

        client.parse_worksheet(b"image-bytes")

        headers = http.calls[0]["headers"]
        self.assertEqual(headers["User-Agent"], "ai-math-tutor-demo/0.1")
        self.assertEqual(headers["x-opencode-session"], "session-123")
        self.assertEqual(headers["Authorization"], "Bearer vision-key")
        self.assertEqual(http.calls[0]["url"], go_base + "/chat/completions")

    def test_gemini_route_sends_demo_headers_on_opencode_host(self) -> None:
        http = FakeHttp(
            FakeResponse(gemini_body(json.dumps({"items": [], "confidence": 0.9})))
        )
        client = VisionClient(
            gemini_settings(), http, session_id="gemini-session"
        )

        client.parse_worksheet(PNG_BYTES)

        headers = http.calls[0]["headers"]
        self.assertEqual(headers["User-Agent"], "ai-math-tutor-demo/0.1")
        self.assertEqual(headers["x-opencode-session"], "gemini-session")

    def test_non_opencode_host_gets_no_demo_headers(self) -> None:
        other_base = "https://vision.example.com/v1"
        http = FakeHttp(
            FakeResponse(hosted_body(json.dumps({"items": [], "confidence": 0.9})))
        )
        client = VisionClient(
            make_settings(vision_base_url=other_base),
            http,
            session_id="session-123",
        )

        client.parse_worksheet(b"image-bytes")

        headers = http.calls[0]["headers"]
        self.assertNotIn("User-Agent", headers)
        self.assertNotIn("x-opencode-session", headers)
        self.assertEqual(headers, {"Authorization": "Bearer vision-key"})

    def test_no_hardcoded_openai_url(self) -> None:
        source = VISION_FILE.read_text(encoding="utf-8")

        self.assertNotIn("api.openai.com", source)

    def test_strips_markdown_json_fence(self) -> None:
        fenced = '```json\n{"items": [], "confidence": 0.9}\n```'
        http = FakeHttp(FakeResponse(hosted_body(fenced)))
        client = VisionClient(make_settings(), http)

        parsed = client.parse_worksheet(b"image-bytes")

        self.assertEqual(parsed.items, [])
        self.assertEqual(parsed.confidence, 0.9)

    def test_retries_without_response_format_on_400(self) -> None:
        request = httpx.Request("POST", ENDPOINT)
        error = httpx.HTTPStatusError(
            "400 Bad Request",
            request=request,
            response=httpx.Response(
                400,
                request=request,
                text="unsupported parameter: response_format",
            ),
        )
        http = FakeHttp(
            error,
            FakeResponse(hosted_body(json.dumps({"items": [], "confidence": 0.5}))),
        )
        client = VisionClient(make_settings(), http)

        parsed = client.parse_worksheet(b"image-bytes")

        self.assertEqual(len(http.calls), 2)
        self.assertIn("response_format", http.calls[0]["json"])
        self.assertNotIn("response_format", http.calls[1]["json"])
        self.assertEqual(http.calls[1]["url"], ENDPOINT)
        self.assertEqual(parsed.confidence, 0.5)

    def test_does_not_retry_on_non_400_status(self) -> None:
        request = httpx.Request("POST", ENDPOINT)
        error = httpx.HTTPStatusError(
            "500 Server Error",
            request=request,
            response=httpx.Response(
                500,
                request=request,
                text="response_format could not be processed",
            ),
        )
        http = FakeHttp(
            error,
            FakeResponse(hosted_body(json.dumps({"items": [], "confidence": 0.5}))),
        )
        client = VisionClient(make_settings(), http)

        with self.assertRaises(VisionUnavailableError):
            client.parse_worksheet(b"image-bytes")

        self.assertEqual(len(http.calls), 1)

    def test_local_vision_ignores_base_url(self) -> None:
        local_body = {
            "message": {
                "content": json.dumps(
                    {
                        "raw_text": "15",
                        "value": "15",
                        "confidence": 0.8,
                        "visible_work": "",
                    }
                )
            }
        }
        http = FakeHttp(FakeResponse(local_body))
        client = VisionClient(
            make_settings(vision_provider="local", vision_base_url=""), http
        )

        read = client.read_handwriting(b"image-bytes", {"id": "A1"})

        self.assertEqual(read.value, "15")
        self.assertEqual(
            http.calls[0]["url"], "http://localhost:11434/api/chat"
        )
        self.assertEqual(http.calls[0]["headers"], {})


class GeminiVisionRequestTests(unittest.TestCase):
    def test_gemini_posts_to_generate_content(self) -> None:
        http = FakeHttp(
            FakeResponse(gemini_body(json.dumps({"items": [], "confidence": 0.9})))
        )
        client = VisionClient(gemini_settings(), http)

        parsed = client.parse_worksheet(PNG_BYTES)

        self.assertEqual(len(http.calls), 1)
        call = http.calls[0]
        self.assertEqual(call["method"], "POST")
        self.assertEqual(call["url"], GEMINI_ENDPOINT)
        self.assertEqual(call["headers"]["Authorization"], "Bearer vision-key")
        body = call["json"]
        self.assertNotIn("messages", body)
        self.assertNotIn("response_format", body)
        self.assertEqual(
            body["generationConfig"], {"responseMimeType": "application/json"}
        )
        content = body["contents"][0]
        self.assertEqual(content["role"], "user")
        text_part, image_part = content["parts"]
        instruction = json.loads(text_part["text"])["instruction"]
        self.assertIn("placement", instruction)
        self.assertEqual(
            image_part,
            {
                "inline_data": {
                    "mime_type": "image/png",
                    "data": base64.b64encode(PNG_BYTES).decode("ascii"),
                }
            },
        )
        self.assertEqual(parsed.items, [])
        self.assertEqual(parsed.confidence, 0.9)

    def test_gemini_strips_markdown_json_fence(self) -> None:
        fenced = '```json\n{"items": [], "confidence": 0.7}\n```'
        http = FakeHttp(FakeResponse(gemini_body(fenced)))
        client = VisionClient(gemini_settings(), http)

        parsed = client.parse_worksheet(PNG_BYTES)

        self.assertEqual(parsed.items, [])
        self.assertEqual(parsed.confidence, 0.7)

    def test_gemini_joins_multiple_text_parts(self) -> None:
        body = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": '{"items": [],'},
                            {"text": ' "confidence": 0.6}'},
                        ]
                    }
                }
            ]
        }
        http = FakeHttp(FakeResponse(body))
        client = VisionClient(gemini_settings(), http)

        parsed = client.parse_worksheet(PNG_BYTES)

        self.assertEqual(parsed.confidence, 0.6)

    def test_gemini_malformed_body_is_domain_error(self) -> None:
        for body in (
            {"unexpected": "shape"},
            {"candidates": []},
            {"candidates": [{"content": {"parts": []}}]},
        ):
            with self.subTest(body=body):
                http = FakeHttp(FakeResponse(body))
                client = VisionClient(gemini_settings(), http)
                with self.assertRaises(VisionError):
                    client.parse_worksheet(PNG_BYTES)

    def test_gemini_invalid_json_text_is_domain_error(self) -> None:
        http = FakeHttp(FakeResponse(gemini_body("not json at all")))
        client = VisionClient(gemini_settings(), http)

        with self.assertRaises(VisionError):
            client.read_handwriting(PNG_BYTES, {"id": "A2"})

    def test_gemini_http_error_is_redacted(self) -> None:
        http = FakeHttp(
            status_error(
                401, "invalid api key vision-key for " + GEMINI_ENDPOINT
            )
        )
        client = VisionClient(gemini_settings(), http)

        with self.assertRaises(VisionUnavailableError) as raised:
            client.parse_worksheet(PNG_BYTES)

        message = str(raised.exception)
        self.assertNotIn("vision-key", message)
        self.assertNotIn(GEMINI_BASE_URL, message)
        self.assertNotIn(GEMINI_ENDPOINT, message)
        self.assertNotIn("401", message)

    def test_gemini_connect_error_is_domain_error(self) -> None:
        http = FakeHttp(httpx.ConnectError("connection refused"))
        client = VisionClient(gemini_settings(), http)

        with self.assertRaises(VisionUnavailableError):
            client.parse_worksheet(PNG_BYTES)

    def test_gemini_does_not_retry_on_400(self) -> None:
        http = FakeHttp(
            status_error(400, "unsupported parameter: response_format"),
            FakeResponse(gemini_body(json.dumps({"items": [], "confidence": 0.5}))),
        )
        client = VisionClient(gemini_settings(), http)

        with self.assertRaises(VisionUnavailableError):
            client.parse_worksheet(PNG_BYTES)

        self.assertEqual(len(http.calls), 1)


class ImageMimeTests(unittest.TestCase):
    def _openai_image_url(self, image: bytes) -> str:
        http = FakeHttp(
            FakeResponse(hosted_body(json.dumps({"items": [], "confidence": 0.9})))
        )
        VisionClient(make_settings(), http).parse_worksheet(image)
        return http.calls[0]["json"]["messages"][0]["content"][1]["image_url"][
            "url"
        ]

    def _gemini_mime_type(self, image: bytes) -> str:
        http = FakeHttp(
            FakeResponse(gemini_body(json.dumps({"items": [], "confidence": 0.9})))
        )
        VisionClient(gemini_settings(), http).parse_worksheet(image)
        return http.calls[0]["json"]["contents"][0]["parts"][1]["inline_data"][
            "mime_type"
        ]

    def test_openai_data_url_labels_png_and_jpeg(self) -> None:
        self.assertTrue(
            self._openai_image_url(PNG_BYTES).startswith("data:image/png;base64,")
        )
        self.assertTrue(
            self._openai_image_url(JPEG_BYTES).startswith("data:image/jpeg;base64,")
        )

    def test_gemini_inline_data_labels_png_and_jpeg(self) -> None:
        self.assertEqual(self._gemini_mime_type(PNG_BYTES), "image/png")
        self.assertEqual(self._gemini_mime_type(JPEG_BYTES), "image/jpeg")

    def test_unknown_bytes_fall_back_to_jpeg(self) -> None:
        self.assertTrue(
            self._openai_image_url(b"image-bytes").startswith(
                "data:image/jpeg;base64,"
            )
        )
        self.assertEqual(self._gemini_mime_type(b"image-bytes"), "image/jpeg")


class WorksheetPlacementParseTests(unittest.TestCase):
    def _parse(self, body: dict):
        http = FakeHttp(FakeResponse(hosted_body(json.dumps(body))))
        client = VisionClient(make_settings(), http)
        return client.parse_worksheet(b"image-bytes"), http

    def test_every_placement_status_round_trips(self) -> None:
        for placement in (
            PLACEMENT_READY,
            PLACEMENT_MISSING,
            PLACEMENT_PARTIAL,
            PLACEMENT_UNREADABLE,
            PLACEMENT_DIFFERENT_SHEET,
        ):
            with self.subTest(placement=placement):
                parsed, _ = self._parse(
                    {
                        "placement": placement,
                        "reason": "shifted left",
                        "items": [],
                        "confidence": 0.9,
                    }
                )
                self.assertEqual(parsed.placement, placement)
                self.assertEqual(parsed.reason, "shifted left")

    def test_missing_placement_defaults_to_ready(self) -> None:
        parsed, _ = self._parse({"items": [], "confidence": 0.9})

        self.assertEqual(parsed.placement, PLACEMENT_READY)
        self.assertEqual(parsed.reason, "")

    def test_observed_position_description_with_twelve_items_is_unknown(
        self,
    ) -> None:
        parsed, _ = self._parse(
            {
                "placement": "Center and Bottom",
                "reason": "sheet centered and low",
                "items": worksheet_items(),
                "confidence": 0.99,
            }
        )

        self.assertEqual(len(parsed.items), 12)
        self.assertEqual(parsed.placement, PLACEMENT_UNKNOWN)
        self.assertEqual(parsed.confidence, 0.99)

    def test_unrecognized_placement_becomes_unknown_without_raising(
        self,
    ) -> None:
        for placement in ("blurry", "", "READY"):
            with self.subTest(placement=placement):
                parsed, _ = self._parse(
                    {
                        "placement": placement,
                        "items": worksheet_items(),
                        "confidence": 0.9,
                    }
                )
                self.assertEqual(parsed.placement, PLACEMENT_UNKNOWN)

    def test_non_string_placement_becomes_unknown(self) -> None:
        for placement in (1, ["ready"], True):
            with self.subTest(placement=placement):
                parsed, _ = self._parse(
                    {
                        "placement": placement,
                        "items": [],
                        "confidence": 0.9,
                    }
                )
                self.assertEqual(parsed.placement, PLACEMENT_UNKNOWN)

    def test_placement_instruction_lists_exact_allowed_statuses(self) -> None:
        _, http = self._parse({"items": [], "confidence": 0.9})
        content = http.calls[0]["json"]["messages"][0]["content"][0]["text"]
        instruction = json.loads(content)["instruction"]

        self.assertIn(
            "ready, missing, partial, unreadable, different_sheet",
            instruction,
        )
        self.assertIn("do not describe the sheet's position", instruction)

    def test_instruction_specifies_bare_item_expression(self) -> None:
        _, http = self._parse({"items": [], "confidence": 0.9})
        content = http.calls[0]["json"]["messages"][0]["content"][0]["text"]
        instruction = json.loads(content)["instruction"]

        self.assertIn('item: "A1".."B6"', instruction)
        self.assertIn('section: "A" or "B"', instruction)
        self.assertIn(
            'expression: the bare arithmetic expression without "=" or '
            "the answer blank",
            instruction,
        )

    def test_instruction_requires_a_numeric_confidence(self) -> None:
        _, http = self._parse({"items": [], "confidence": 0.9})
        content = http.calls[0]["json"]["messages"][0]["content"][0]["text"]
        instruction = json.loads(content)["instruction"]

        self.assertIn(NUMERIC_CONFIDENCE_REQUIREMENT, instruction)
        self.assertIn("for example 0.9", instruction)
        self.assertIn("never a word", instruction)

    def test_item_expression_drops_trailing_equals_and_answer_blank(
        self,
    ) -> None:
        cases = [
            ("63 + 24 = ____", "63 + 24"),
            (" 6 × 4 ____ ", "6 × 4"),
            ("20 ÷ 4=_____", "20 ÷ 4"),
        ]
        for expression, expected in cases:
            with self.subTest(expression=expression):
                parsed, _ = self._parse(
                    {
                        "items": [
                            {
                                "item": "A2",
                                "section": "A",
                                "problem": "63 + 24 = ____",
                                "expression": expression,
                            }
                        ],
                        "confidence": 0.99,
                    }
                )
                self.assertEqual(parsed.items[0].expression, expected)

    def test_invalid_confidence_still_raises(self) -> None:
        for body in (
            {"items": [], "confidence": "high"},
            {"items": []},
        ):
            with self.subTest(body=body):
                http = FakeHttp(
                    FakeResponse(hosted_body(json.dumps(body)))
                )
                client = VisionClient(make_settings(), http)
                with self.assertRaises(VisionError):
                    client.parse_worksheet(b"image-bytes")

    def test_reason_is_capped_at_160_characters(self) -> None:
        parsed, _ = self._parse(
            {"items": [], "confidence": 0.9, "reason": "x" * 200}
        )

        self.assertEqual(parsed.reason, "x" * 160)

    def test_reason_missing_or_empty_is_an_empty_string(self) -> None:
        for body in (
            {"items": [], "confidence": 0.9},
            {"items": [], "confidence": 0.9, "reason": None},
            {"items": [], "confidence": 0.9, "reason": ""},
        ):
            with self.subTest(body=body):
                parsed, _ = self._parse(body)
                self.assertEqual(parsed.reason, "")

    def test_instruction_requests_placement_reason_items_and_confidence(
        self,
    ) -> None:
        _, http = self._parse({"items": [], "confidence": 0.9})
        content = http.calls[0]["json"]["messages"][0]["content"][0]["text"]
        instruction = json.loads(content)["instruction"]

        for field in ("placement", "reason", "items", "confidence"):
            with self.subTest(field=field):
                self.assertIn(field, instruction)

    def test_existing_constructor_defaults_still_work(self) -> None:
        parsed = WorksheetParse([], 0.9)

        self.assertEqual(parsed.placement, PLACEMENT_READY)
        self.assertEqual(parsed.reason, "")


class HandwritingReadTests(unittest.TestCase):
    def _read(self, body: dict):
        http = FakeHttp(FakeResponse(hosted_body(json.dumps(body))))
        client = VisionClient(make_settings(), http)
        return client.read_handwriting(b"image-bytes", {"id": "A2"}), http

    def test_read_returns_visibility_location_and_reasons(self) -> None:
        read, _ = self._read(
            {
                "raw_text": "87",
                "value": "87",
                "confidence": 0.97,
                "visible_work": "63 + 24",
                "visibility": VISIBILITY_OBSCURED,
                "location": "x" * 200,
                "reasons": ["hand", "shadow", "blur", "tilt", "glare", "extra"],
            }
        )

        self.assertEqual(read.visibility, VISIBILITY_OBSCURED)
        self.assertEqual(read.location, "x" * 160)
        self.assertEqual(read.reasons, ("hand", "shadow", "blur", "tilt", "glare"))

    def test_missing_visibility_defaults_to_clear(self) -> None:
        read, _ = self._read(
            {
                "raw_text": "87",
                "value": "87",
                "confidence": 0.97,
                "visible_work": "",
            }
        )

        self.assertEqual(read.visibility, VISIBILITY_CLEAR)
        self.assertEqual(read.location, "")
        self.assertEqual(read.reasons, ())

    def test_unrecognized_visibility_becomes_unclear(self) -> None:
        for visibility in ("sideways", "", "CLEAR"):
            with self.subTest(visibility=visibility):
                read, _ = self._read(
                    {
                        "raw_text": "87",
                        "value": "87",
                        "confidence": 0.97,
                        "visible_work": "",
                        "visibility": visibility,
                    }
                )
                self.assertEqual(read.visibility, VISIBILITY_UNCLEAR)
                self.assertNotEqual(read.visibility, VISIBILITY_CLEAR)

    def test_non_string_visibility_becomes_unclear(self) -> None:
        for visibility in (1, ["clear"], True):
            with self.subTest(visibility=visibility):
                read, _ = self._read(
                    {
                        "raw_text": "87",
                        "value": "87",
                        "confidence": 0.97,
                        "visible_work": "",
                        "visibility": visibility,
                    }
                )
                self.assertEqual(read.visibility, VISIBILITY_UNCLEAR)

    def test_visibility_instruction_lists_exact_allowed_values(self) -> None:
        _, http = self._read(
            {
                "raw_text": "87",
                "value": "87",
                "confidence": 0.97,
                "visible_work": "",
            }
        )
        content = http.calls[0]["json"]["messages"][0]["content"][0]["text"]
        instruction = json.loads(content)["instruction"]

        self.assertIn(
            "clear, blank, obscured, overwritten, multiple_answer, wrong_item",
            instruction,
        )

    def test_instruction_requires_a_numeric_confidence(self) -> None:
        _, http = self._read(
            {
                "raw_text": "87",
                "value": "87",
                "confidence": 0.97,
                "visible_work": "",
            }
        )
        content = http.calls[0]["json"]["messages"][0]["content"][0]["text"]
        instruction = json.loads(content)["instruction"]

        self.assertIn(NUMERIC_CONFIDENCE_REQUIREMENT, instruction)
        self.assertIn("for example 0.9", instruction)
        self.assertIn("never a word", instruction)

    def test_locator_instruction_uses_the_same_numeric_confidence(self) -> None:
        self.assertIn(NUMERIC_CONFIDENCE_REQUIREMENT, LOCATE_INSTRUCTION)
        self.assertIn("never a word", LOCATE_INSTRUCTION)

    def test_invalid_handwriting_confidence_still_raises(self) -> None:
        for body in (
            {
                "raw_text": "87",
                "value": "87",
                "confidence": "high",
                "visible_work": "",
            },
            {"raw_text": "87", "value": "87", "visible_work": ""},
        ):
            with self.subTest(body=body):
                http = FakeHttp(
                    FakeResponse(hosted_body(json.dumps(body)))
                )
                client = VisionClient(make_settings(), http)
                with self.assertRaises(VisionError):
                    client.read_handwriting(b"image-bytes", {"id": "A2"})

    def test_non_object_json_payload_raises_in_both_reads(self) -> None:
        for method in ("parse_worksheet", "read_handwriting"):
            with self.subTest(method=method):
                http = FakeHttp(
                    FakeResponse(hosted_body(json.dumps([1, 2, 3])))
                )
                client = VisionClient(make_settings(), http)
                with self.assertRaises(VisionError):
                    if method == "parse_worksheet":
                        client.parse_worksheet(b"image-bytes")
                    else:
                        client.read_handwriting(
                            b"image-bytes", {"id": "A2"}
                        )


def status_error(status_code: int, text: str = "") -> httpx.HTTPStatusError:
    request = httpx.Request("POST", ENDPOINT)
    return httpx.HTTPStatusError(
        f"{status_code} provider failure",
        request=request,
        response=httpx.Response(status_code, request=request, text=text),
    )


class VisionFailureTests(unittest.TestCase):
    def test_vision_http_error_is_domain_error(self) -> None:
        http = FakeHttp(
            status_error(401, "invalid api key vision-key for " + ENDPOINT)
        )
        client = VisionClient(make_settings(), http)

        with self.assertRaises(VisionUnavailableError) as raised:
            client.parse_worksheet(b"image-bytes")

        message = str(raised.exception)
        self.assertNotIn("vision-key", message)
        self.assertNotIn(OPENCODE_BASE_URL, message)
        self.assertNotIn(ENDPOINT, message)
        self.assertNotIn("401 provider failure", message)

    def test_vision_connect_error_is_domain_error(self) -> None:
        http = FakeHttp(httpx.ConnectError("connection refused"))
        client = VisionClient(make_settings(), http)

        with self.assertRaises(VisionUnavailableError):
            client.parse_worksheet(b"image-bytes")

    def test_vision_failed_retry_is_domain_error(self) -> None:
        http = FakeHttp(
            status_error(400, "unsupported parameter: response_format"),
            status_error(500, "internal error at " + ENDPOINT),
        )
        client = VisionClient(make_settings(), http)

        with self.assertRaises(VisionUnavailableError) as raised:
            client.parse_worksheet(b"image-bytes")

        self.assertEqual(len(http.calls), 2)
        self.assertNotIn(OPENCODE_BASE_URL, str(raised.exception))

    def test_vision_malformed_body_is_domain_error(self) -> None:
        http = FakeHttp(FakeResponse({"unexpected": "shape"}))
        client = VisionClient(make_settings(), http)

        with self.assertRaises(VisionError):
            client.parse_worksheet(b"image-bytes")

    def test_vision_invalid_json_body_is_domain_error(self) -> None:
        http = FakeHttp(FakeResponse(hosted_body("not json at all")))
        client = VisionClient(make_settings(), http)

        with self.assertRaises(VisionError):
            client.read_handwriting(b"image-bytes", {"id": "A1"})

    def test_vision_requires_configuration(self) -> None:
        for settings in (
            make_settings(vision_api_key=""),
            make_settings(vision_provider="local", vision_model=""),
        ):
            with self.subTest(provider=settings.vision_provider):
                client = VisionClient(settings, FakeHttp())
                with self.assertRaises(VisionUnavailableError) as raised:
                    client.parse_worksheet(b"image-bytes")
                self.assertNotIn(OPENCODE_BASE_URL, str(raised.exception))
                self.assertEqual(client.http.calls, [])


if __name__ == "__main__":
    unittest.main()
