import json
import unittest

import httpx

from agent.config import Settings
from agent.llm import (
    VALID_INTENTS,
    FallbackIntentClient,
    IntentError,
    OllamaClient,
    OpenAIIntentClient,
    TutorIntent,
    build_intent_client,
)


class FakeResponse:
    def __init__(self, content: dict) -> None:
        self.content = content

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"message": {"content": json.dumps(self.content)}}


class FakeHttp:
    def __init__(self, content: dict) -> None:
        self.response = FakeResponse(content)

    def post(self, *args, **kwargs) -> FakeResponse:
        return self.response


class RawResponse:
    def __init__(self, body: object) -> None:
        self.body = body

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self.body


class RawHttp:
    def __init__(self, *responses) -> None:
        self.responses = list(responses)

    def post(self, *args, **kwargs):
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class OpenAIResponse:
    """OpenAI-compatible body; dict content is serialized, text is verbatim."""

    def __init__(self, content: object) -> None:
        self.content = (
            content if isinstance(content, str) else json.dumps(content)
        )

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"choices": [{"message": {"content": self.content}}]}


class RecordingHttp:
    def __init__(self, *responses) -> None:
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def opencode_settings(**overrides) -> Settings:
    values = {
        "ollama_model": "local-model",
        "intent_provider": "opencode",
        "intent_model": "claude-haiku-5-5",
        "intent_base_url": "https://opencode.ai/inference/go/openai/v1",
        "intent_api_key": "go-key",
    }
    values.update(overrides)
    return Settings(**values)


OLLAMA_URL = "http://localhost:11434/api/chat"


def ollama_status_error(status_code: int, text: str = "") -> httpx.HTTPStatusError:
    request = httpx.Request("POST", OLLAMA_URL)
    return httpx.HTTPStatusError(
        f"{status_code} provider failure",
        request=request,
        response=httpx.Response(status_code, request=request, text=text),
    )


class LlmFailureTests(unittest.TestCase):
    def settings(self) -> Settings:
        return Settings(
            ollama_model="model",
        )

    def test_ollama_http_error_is_intent_error(self) -> None:
        http = RawHttp(ollama_status_error(401, "unauthorized at " + OLLAMA_URL))
        client = OllamaClient(self.settings(), http)

        with self.assertRaises(IntentError) as raised:
            client.interpret("check", {}, {"steps": []})

        self.assertEqual(str(raised.exception), "Ollama request failed")
        self.assertNotIn(OLLAMA_URL, str(raised.exception))

    def test_ollama_connect_error_is_intent_error(self) -> None:
        client = OllamaClient(
            self.settings(), RawHttp(httpx.ConnectError("connection refused"))
        )

        with self.assertRaises(IntentError):
            client.interpret("check", {}, {"steps": []})

    def test_ollama_malformed_body_is_intent_error(self) -> None:
        bodies = (
            {"unexpected": "shape"},
            {"message": {"content": "not json"}},
            {"message": {"content": json.dumps(["not", "an", "object"])}},
        )
        for body in bodies:
            with self.subTest(body=body):
                client = OllamaClient(self.settings(), RawHttp(RawResponse(body)))
                with self.assertRaises(IntentError):
                    client.interpret("check", {}, {"steps": []})


class LlmTests(unittest.TestCase):
    def settings(self) -> Settings:
        return Settings(
            ollama_model="model",
        )

    def test_validates_intent_and_guidance_step(self) -> None:
        client = OllamaClient(
            self.settings(),
            FakeHttp({
                "intent": "CHECK_ANSWER", "exercise_id": "A1",
                "candidate_answer": "15", "guidance_step": 1,
            }),
        )
        intent = client.interpret(
            "check", {"state_block": "exercise=A1"}, {"steps": [{"index": 1}]}
        )
        self.assertEqual(intent.candidate_answer, "15")

    def test_rejects_unknown_exercise_and_step(self) -> None:
        for data in (
            {"intent": "CHECK_ANSWER", "exercise_id": "C1"},
            {"intent": "CHECK_ANSWER", "guidance_step": 9},
        ):
            with self.subTest(data=data):
                client = OllamaClient(self.settings(), FakeHttp(data))
                with self.assertRaises(IntentError):
                    client.interpret("check", {}, {"steps": [{"index": 1}]})

    def test_llm_accepts_done_and_list_intents(self) -> None:
        for name in ("DONE", "LIST_WORKSHEET"):
            with self.subTest(intent=name):
                client = OllamaClient(self.settings(), FakeHttp({"intent": name}))
                intent = client.interpret(
                    "which exercises are there",
                    {"state_block": "exercise=A1"},
                    {"steps": [{"index": 1}]},
                )
                self.assertEqual(intent.intent, name)

    def test_llm_accepts_help_and_ask_answer_intents(self) -> None:
        cases = (
            ("HELP", "I don't understand this step", None, None),
            ("ASK_ANSWER", "just tell me the answer", None, None),
            ("ASK_ANSWER", "tell me", "15", None),
        )
        for name, transcript, candidate, step in cases:
            with self.subTest(intent=name, transcript=transcript):
                data = {"intent": name, "candidate_answer": candidate}
                if step is not None:
                    data["guidance_step"] = step
                client = OllamaClient(self.settings(), FakeHttp(data))
                intent = client.interpret(
                    transcript, {}, {"steps": [{"index": 1}]}
                )
                self.assertEqual(intent.intent, name)

    def test_help_and_ask_answer_keep_slot_validation(self) -> None:
        for data in (
            {"intent": "HELP", "exercise_id": "C1"},
            {"intent": "ASK_ANSWER", "guidance_step": 9},
        ):
            with self.subTest(data=data):
                client = OllamaClient(self.settings(), FakeHttp(data))
                with self.assertRaises(IntentError):
                    client.interpret(
                        "help", {}, {"steps": [{"index": 1}]}
                    )

    def test_rejects_unknown_intent(self) -> None:
        client = OllamaClient(self.settings(), FakeHttp({"intent": "HINT"}))
        with self.assertRaises(IntentError):
            client.interpret("hint", {}, {"steps": [{"index": 1}]})

    def test_legacy_aliases_normalize(self) -> None:
        cases = [
            ({"intent": "CHOOSE", "exercise_id": "A2"}, "CHOOSE_EXERCISE"),
            (
                {"intent": "CHECK_ANSWER", "candidate_answer": "15"},
                "CHECK_SPOKEN_ANSWER",
            ),
            ({"intent": "CHECK_ANSWER"}, "CHECK_WRITING"),
        ]
        for data, expected in cases:
            with self.subTest(data=data):
                client = OllamaClient(self.settings(), FakeHttp(data))
                intent = client.interpret("check", {}, {"steps": []})
                self.assertEqual(intent.intent, expected)

    def test_section_and_number_slots(self) -> None:
        client = OllamaClient(
            self.settings(),
            FakeHttp({"intent": "CHOOSE_EXERCISE", "number": 2}),
        )
        bare = client.interpret("number two", {}, {"steps": []})
        self.assertIsNone(bare.exercise_id)
        self.assertIsNone(bare.section)
        self.assertEqual(bare.number, 2)

        client = OllamaClient(
            self.settings(),
            FakeHttp(
                {"intent": "CHOOSE_EXERCISE", "section": "a", "number": "2"}
            ),
        )
        chosen = client.interpret("section A, number two", {}, {"steps": []})
        self.assertEqual(chosen.section, "A")
        self.assertEqual(chosen.number, 2)

    def test_rejects_bad_section_number_or_disagreement(self) -> None:
        for data in (
            {"intent": "CHOOSE_EXERCISE", "section": "C"},
            {"intent": "CHOOSE_EXERCISE", "number": 7},
            {"intent": "CHOOSE_EXERCISE", "number": "two"},
            {
                "intent": "CHOOSE_EXERCISE",
                "exercise_id": "A2",
                "section": "B",
                "number": 2,
            },
        ):
            with self.subTest(data=data):
                client = OllamaClient(self.settings(), FakeHttp(data))
                with self.assertRaises(IntentError):
                    client.interpret("choice", {}, {"steps": []})

    def test_system_prompt_lists_the_canonical_vocabulary(self) -> None:
        from agent.llm import VALID_INTENTS

        captured = {}

        class CapturingHttp:
            def post(self, *args, **kwargs):
                captured.update(kwargs["json"])
                return FakeResponse({"intent": "UNCLEAR"})

        OllamaClient(self.settings(), CapturingHttp()).interpret(
            "hello", {}, {"steps": []}
        )
        system = captured["messages"][0]["content"]
        for name in VALID_INTENTS:
            with self.subTest(intent=name):
                self.assertIn(name, system)
        self.assertIn("section", system)
        self.assertIn("number", system)
        self.assertIn("Never state an unverified number", system)

    def test_system_prompt_teaches_the_new_conversation_intents(self) -> None:
        captured = {}

        class CapturingHttp:
            def post(self, *args, **kwargs):
                captured.update(kwargs["json"])
                return FakeResponse({"intent": "UNCLEAR"})

        OllamaClient(self.settings(), CapturingHttp()).interpret(
            "hello", {}, {"steps": []}
        )
        system = captured["messages"][0]["content"]
        self.assertIn("HELP", system)
        self.assertIn("ASK_ANSWER", system)
        self.assertIn("never reveal the answer", system.lower())
        self.assertIn("I don't understand", system)

    def test_system_prompt_treats_a_bare_number_as_a_spoken_answer(self) -> None:
        captured = {}

        class CapturingHttp:
            def post(self, *args, **kwargs):
                captured.update(kwargs["json"])
                return FakeResponse({"intent": "UNCLEAR"})

        OllamaClient(self.settings(), CapturingHttp()).interpret(
            "hello", {}, {"steps": []}
        )
        system = " ".join(captured["messages"][0]["content"].split())
        self.assertIn(
            "When an exercise is already active and the student says only a "
            "number, that is a spoken answer",
            system,
        )
        self.assertIn("candidate_answer", system)
        self.assertIn(
            "CHOOSE_EXERCISE only when the student is choosing", system
        )


class OpenAIIntentClientTests(unittest.TestCase):
    def test_posts_json_mode_with_stable_opencode_headers(self) -> None:
        http = RecordingHttp(
            OpenAIResponse({"intent": "OFF_TOPIC"}),
            OpenAIResponse({"intent": "UNCLEAR"}),
        )
        client = OpenAIIntentClient(
            opencode_settings(), http, session_id="session-1"
        )

        first = client.interpret(
            "can you help", {"state_block": "state"}, {"id": "A1"}
        )
        second = client.interpret("hmm", {}, {})

        self.assertEqual(first.intent, "OFF_TOPIC")
        self.assertEqual(second.intent, "UNCLEAR")
        url, request = http.calls[0]
        self.assertEqual(
            url,
            "https://opencode.ai/inference/go/openai/v1/chat/completions",
        )
        self.assertEqual(request["json"]["model"], "claude-haiku-5-5")
        self.assertEqual(
            request["json"]["response_format"], {"type": "json_object"}
        )
        self.assertFalse(request["json"]["stream"])
        self.assertEqual(request["headers"]["Authorization"], "Bearer go-key")
        self.assertEqual(
            request["headers"]["User-Agent"], "ai-math-tutor-demo/0.1"
        )
        self.assertEqual(request["headers"]["x-opencode-session"], "session-1")
        self.assertEqual(request["timeout"], 10.0)
        # The same client keeps one stable session header across calls.
        self.assertEqual(
            http.calls[1][1]["headers"]["x-opencode-session"], "session-1"
        )
        system = request["json"]["messages"][0]["content"]
        for name in VALID_INTENTS:
            with self.subTest(intent=name):
                self.assertIn(name, system)
        sent = json.loads(request["json"]["messages"][1]["content"])
        self.assertEqual(sent["transcript"], "can you help")
        self.assertEqual(sent["exercise"], {"id": "A1"})
        self.assertNotIn("answer", sent["exercise"])

    def test_reuses_the_vision_key_when_intent_key_is_empty(self) -> None:
        settings = opencode_settings(
            intent_api_key="", vision_api_key="vision-key"
        )
        http = RecordingHttp(OpenAIResponse({"intent": "READY"}))

        OpenAIIntentClient(settings, http).interpret("hi", {}, {})

        self.assertEqual(
            http.calls[0][1]["headers"]["Authorization"], "Bearer vision-key"
        )

    def test_other_openai_hosts_get_no_opencode_headers(self) -> None:
        settings = opencode_settings(
            intent_base_url="https://example.test/v1"
        )
        http = RecordingHttp(OpenAIResponse({"intent": "READY"}))

        OpenAIIntentClient(settings, http, session_id="s").interpret(
            "hi", {}, {}
        )

        headers = http.calls[0][1]["headers"]
        self.assertNotIn("User-Agent", headers)
        self.assertNotIn("x-opencode-session", headers)
        self.assertEqual(headers["Authorization"], "Bearer go-key")

    def test_http_error_is_a_redacted_intent_error(self) -> None:
        endpoint = (
            "https://opencode.ai/inference/go/openai/v1/chat/completions"
        )
        request = httpx.Request("POST", endpoint)
        error = httpx.HTTPStatusError(
            "401 with go-key",
            request=request,
            response=httpx.Response(
                401, request=request, text="bad key go-key"
            ),
        )
        client = OpenAIIntentClient(opencode_settings(), RawHttp(error))

        with self.assertRaises(IntentError) as raised:
            client.interpret("check", {}, {"steps": []})

        self.assertEqual(str(raised.exception), "Intent request failed")
        self.assertNotIn("go-key", str(raised.exception))
        self.assertNotIn(endpoint, str(raised.exception))

    def test_timeout_is_not_retried(self) -> None:
        http = RawHttp(httpx.ReadTimeout("slow hosted call"))
        client = OpenAIIntentClient(opencode_settings(), http)

        with self.assertRaises(IntentError):
            client.interpret("check", {}, {"steps": []})

        self.assertEqual(http.responses, [])

    def test_malformed_bodies_are_intent_errors(self) -> None:
        bodies = (
            {"unexpected": "shape"},
            {"choices": []},
            {"choices": [{"message": {"content": "not json"}}]},
            {
                "choices": [
                    {"message": {"content": json.dumps(["not", "an", "object"])}}
                ]
            },
        )
        for body in bodies:
            with self.subTest(body=body):
                client = OpenAIIntentClient(
                    opencode_settings(), RawHttp(RawResponse(body))
                )
                with self.assertRaises(IntentError):
                    client.interpret("check", {}, {"steps": []})

    def test_markdown_fenced_json_is_accepted(self) -> None:
        fenced = "```json\n" + json.dumps({"intent": "DONE"}) + "\n```"
        client = OpenAIIntentClient(
            opencode_settings(), RawHttp(OpenAIResponse(fenced))
        )

        self.assertEqual(
            client.interpret("we are done", {}, {}).intent, "DONE"
        )

    def test_missing_hosted_configuration_is_an_intent_error(self) -> None:
        clients = (
            OpenAIIntentClient(
                opencode_settings(intent_model=""), RawHttp()
            ),
            OpenAIIntentClient(
                opencode_settings(intent_base_url=""), RawHttp()
            ),
        )
        for client in clients:
            with self.subTest(client=client):
                with self.assertRaises(IntentError) as raised:
                    client.interpret("check", {}, {"steps": []})
                self.assertEqual(
                    str(raised.exception), "Intent provider is not configured"
                )


class StubIntentClient:
    def __init__(self, provider, intent=None, error=None) -> None:
        self.provider = provider
        self.intent = intent or TutorIntent("UNCLEAR", None, None, None)
        self.error = error
        self.calls = 0

    def interpret(self, transcript, state, exercise):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.intent


class FallbackIntentClientTests(unittest.TestCase):
    def test_primary_success_does_not_call_the_fallback(self) -> None:
        primary = StubIntentClient(
            "opencode", TutorIntent("READY", None, None, None)
        )
        fallback = StubIntentClient("ollama")
        client = FallbackIntentClient(primary, fallback)

        intent = client.interpret("hi", {}, {})

        self.assertEqual(intent.intent, "READY")
        self.assertEqual(client.provider, "opencode")
        self.assertEqual(fallback.calls, 0)

    def test_intent_error_falls_back_to_local_once(self) -> None:
        primary = StubIntentClient("opencode", error=IntentError("host down"))
        fallback = StubIntentClient(
            "ollama", TutorIntent("OFF_TOPIC", None, None, None)
        )
        client = FallbackIntentClient(primary, fallback)

        intent = client.interpret("hello", {}, {})

        self.assertEqual(intent.intent, "OFF_TOPIC")
        self.assertEqual(client.provider, "ollama")
        self.assertEqual(primary.calls, 1)
        self.assertEqual(fallback.calls, 1)

    def test_transport_error_falls_back_to_local(self) -> None:
        primary = StubIntentClient(
            "opencode", error=httpx.ConnectError("connection refused")
        )
        fallback = StubIntentClient(
            "ollama", TutorIntent("REPEAT", None, None, None)
        )
        client = FallbackIntentClient(primary, fallback)

        self.assertEqual(client.interpret("again", {}, {}).intent, "REPEAT")
        self.assertEqual(client.provider, "ollama")

    def test_both_fail_raises_the_primary_error(self) -> None:
        primary = StubIntentClient(
            "opencode", error=IntentError("hosted unavailable")
        )
        fallback = StubIntentClient(
            "ollama", error=IntentError("local unavailable")
        )
        client = FallbackIntentClient(primary, fallback)

        with self.assertRaises(IntentError) as raised:
            client.interpret("hello", {}, {})

        self.assertEqual(str(raised.exception), "hosted unavailable")
        self.assertEqual(fallback.calls, 1)

    def test_non_provider_error_is_not_swallowed(self) -> None:
        primary = StubIntentClient("opencode", error=KeyError("bug"))
        fallback = StubIntentClient("ollama")
        client = FallbackIntentClient(primary, fallback)

        with self.assertRaises(KeyError):
            client.interpret("hello", {}, {})

        self.assertEqual(fallback.calls, 0)


class IntentClientSelectionTests(unittest.TestCase):
    def test_local_settings_select_the_ollama_client(self) -> None:
        client = build_intent_client(Settings(ollama_model="model"), http=None)

        self.assertIsInstance(client, OllamaClient)
        self.assertEqual(client.provider, "ollama")

    def test_opencode_settings_select_hosted_with_local_fallback(self) -> None:
        client = build_intent_client(
            opencode_settings(), http=None, session_id="session-9"
        )

        self.assertIsInstance(client, FallbackIntentClient)
        self.assertIsInstance(client.primary, OpenAIIntentClient)
        self.assertIsInstance(client.fallback, OllamaClient)
        self.assertEqual(client.provider, "opencode")
        self.assertEqual(client.primary.session_id, "session-9")
        self.assertEqual(
            client.primary.settings.intent_model, "claude-haiku-5-5"
        )


if __name__ == "__main__":
    unittest.main()
