import json
import unittest

import httpx

from agent.config import Settings
from agent.llm import IntentError, OllamaClient


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


if __name__ == "__main__":
    unittest.main()
