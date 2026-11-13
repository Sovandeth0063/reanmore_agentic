"""Tests for the template and hosted tutor renderers; no network is used."""

import json
import unittest

import httpx

from agent.config import Settings
from agent.lesson import Exercise, Step
from agent.render import (
    HostedRenderer,
    RenderRequest,
    TemplateRenderer,
    build_renderer,
)


EXERCISE = Exercise(
    id="A1",
    section="A",
    item=1,
    problem="4 + 5 + 6",
    answer=15,
    verification_expression="4 + 5 + 6",
    steps=(
        Step(index=1, prompt="Add the ones", expected_intermediate=9),
        Step(index=2, prompt="Add the tens", expected_intermediate=15),
    ),
    praise="Great adding!",
)

STEP = EXERCISE.steps[0]

SYSTEM_PROMPT = (
    "You are a warm Grade 3 math tutor. Rewrite the given tutor line in two "
    "to four very short, child-friendly sentences. Keep the same teaching "
    "move. Use only numbers from the allowed list. Never state the final "
    'answer or invent a number. Return JSON {"text": "..."}.'
)


def request(
    *,
    template_text: str = "Add 4 and 5.",
    allowed=None,
    mode: str = "hint",
    step: Step | None = STEP,
    child_answer: str | None = None,
) -> RenderRequest:
    """A hint turn for A1 with only the printed operands allowed."""
    return RenderRequest(
        mode=mode,
        exercise=EXERCISE,
        step=step,
        child_answer=child_answer,
        template_text=template_text,
        allowed_numbers=frozenset({4, 5} if allowed is None else allowed),
    )


def settings(**overrides) -> Settings:
    values = {
        "ollama_model": "local-model",
        "intent_provider": "opencode",
        "intent_model": "claude-haiku-5-5",
        "intent_base_url": "https://opencode.ai/inference/go/openai/v1",
        "intent_api_key": "go-key",
    }
    values.update(overrides)
    return Settings(**values)


class FakeResponse:
    def __init__(self, body: object) -> None:
        self.body = body

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self.body


class FakeHttp:
    """One canned reply and the requests it received.

    A string is wrapped as the OpenAI-compatible ``content`` field; a mapping
    is returned as the whole response body; an exception is raised.
    """

    def __init__(self, content: object) -> None:
        self.content = content
        self.calls: list[tuple[str, dict]] = []

    def post(self, url: str, **kwargs):
        self.calls.append((url, kwargs))
        if isinstance(self.content, Exception):
            raise self.content
        body = (
            {"choices": [{"message": {"content": self.content}}]}
            if isinstance(self.content, str)
            else self.content
        )
        return FakeResponse(body)


def status_error() -> httpx.HTTPStatusError:
    request_ = httpx.Request(
        "POST",
        "https://opencode.ai/inference/go/openai/v1/chat/completions",
    )
    return httpx.HTTPStatusError(
        "429 rate limited",
        request=request_,
        response=httpx.Response(429, request=request_, text="rate limited"),
    )


class TemplateRendererTests(unittest.TestCase):
    def test_template_renderer_returns_the_template(self) -> None:
        result = TemplateRenderer().render(request(template_text="Add 4 and 5."))

        self.assertEqual(result.text, "Add 4 and 5.")
        self.assertEqual(result.provider, "template")
        self.assertFalse(result.fallback)

    def test_template_renderer_never_falls_back(self) -> None:
        renderer = TemplateRenderer()

        result = renderer.render(
            request(
                template_text="What is the first step?",
                allowed=set(),
                mode="explain",
                step=None,
                child_answer="banana",
            )
        )

        self.assertEqual(result.text, "What is the first step?")
        self.assertFalse(result.fallback)


class HostedRendererTests(unittest.TestCase):
    def test_hosted_renderer_returns_validated_text(self) -> None:
        http = FakeHttp('{"text": "First, what is 4 plus 5?"}')

        result = HostedRenderer(settings(), http).render(request(allowed={4, 5}))

        self.assertEqual(result.text, "First, what is 4 plus 5?")
        self.assertEqual(result.provider, "opencode")
        self.assertFalse(result.fallback)

    def test_hosted_renderer_rejects_a_forbidden_word_number(self) -> None:
        http = FakeHttp('{"text": "The answer is fifteen."}')

        result = HostedRenderer(settings(), http).render(
            request(allowed={4, 5}, template_text="Add 4 and 5.")
        )

        self.assertEqual(result.text, "Add 4 and 5.")
        self.assertEqual(result.provider, "template")
        self.assertTrue(result.fallback)

    def test_hosted_renderer_rejects_a_forbidden_digit(self) -> None:
        http = FakeHttp('{"text": "Add 4 and 7."}')

        result = HostedRenderer(settings(), http).render(
            request(allowed={4, 5}, template_text="Add 4 and 5.")
        )

        self.assertTrue(result.fallback)
        self.assertEqual(result.text, "Add 4 and 5.")

    def test_hosted_renderer_rejects_the_answer_as_a_word(self) -> None:
        text = "The answer is fifteen."
        http = FakeHttp(json.dumps({"text": text}))

        result = HostedRenderer(settings(), http).render(
            request(allowed={4, 5}, template_text="Add 4 and 5.")
        )

        self.assertTrue(result.fallback)
        self.assertEqual(result.text, "Add 4 and 5.")

    def test_hosted_renderer_rejects_the_answer_as_digits(self) -> None:
        text = "The answer is 15."
        http = FakeHttp(json.dumps({"text": text}))

        result = HostedRenderer(settings(), http).render(
            request(allowed={4, 5}, template_text="Add 4 and 5.")
        )

        self.assertTrue(result.fallback)
        self.assertEqual(result.text, "Add 4 and 5.")

    def test_hosted_renderer_accepts_the_answer_once_it_is_allowed(self) -> None:
        text = "That's right, 15."
        http = FakeHttp(json.dumps({"text": text}))

        result = HostedRenderer(settings(), http).render(
            request(allowed={4, 5, 15}, template_text="Add 4 and 5.")
        )

        self.assertFalse(result.fallback)
        self.assertEqual(result.text, text)
        self.assertEqual(result.provider, "opencode")

    def test_hosted_renderer_rejects_an_unlisted_number_word(self) -> None:
        # Four sentences and under the character cap, so the only failure is
        # "two": the strict guard covers number words, not just the answer.
        texts = (
            (
                "Nice work trying! Let's add the last two numbers first. "
                "What is 6 plus 9? Then tell me the total."
            ),
            (
                "Nice start! Count on one more. "
                "What is 6 plus 9?"
            ),
        )
        for text in texts:
            with self.subTest(text=text):
                self.assertLessEqual(len(text), 240)
                http = FakeHttp(json.dumps({"text": text}))

                result = HostedRenderer(settings(), http).render(
                    request(allowed={6, 9}, template_text="What is 6 plus 9?")
                )

                self.assertTrue(result.fallback)
                self.assertEqual(result.text, "What is 6 plus 9?")
                self.assertEqual(result.provider, "template")

    def test_hosted_renderer_falls_back_on_timeout_or_bad_json(self) -> None:
        cases = (
            ("timeout", FakeHttp(httpx.TimeoutException("slow"))),
            ("bad json", FakeHttp("not json")),
        )
        for label, http in cases:
            with self.subTest(case=label):
                result = HostedRenderer(settings(), http).render(
                    request(template_text="Add 4 and 5.")
                )

                self.assertEqual(result.text, "Add 4 and 5.")
                self.assertEqual(result.provider, "template")
                self.assertTrue(result.fallback)

    def test_hosted_renderer_falls_back_on_an_http_error(self) -> None:
        http = FakeHttp(status_error())

        result = HostedRenderer(settings(), http).render(
            request(template_text="Add 4 and 5.")
        )

        self.assertTrue(result.fallback)
        self.assertEqual(result.text, "Add 4 and 5.")

    def test_hosted_renderer_falls_back_on_a_malformed_body(self) -> None:
        bodies = (
            {"unexpected": "shape"},
            {"choices": []},
            {"choices": [{"message": {}}]},
            {"choices": [{"message": {"content": None}}]},
        )
        for body in bodies:
            with self.subTest(body=body):
                result = HostedRenderer(settings(), FakeHttp(body)).render(
                    request(template_text="Add 4 and 5.")
                )

                self.assertTrue(result.fallback)
                self.assertEqual(result.text, "Add 4 and 5.")

    def test_hosted_renderer_falls_back_on_a_long_response(self) -> None:
        long_text = "Add " + "4 " * 120 + "and 5."
        self.assertGreater(len(long_text), 240)
        http = FakeHttp(json.dumps({"text": long_text}))

        result = HostedRenderer(settings(), http).render(
            request(template_text="Add 4 and 5.")
        )

        self.assertTrue(result.fallback)
        self.assertEqual(result.text, "Add 4 and 5.")

    def test_hosted_renderer_falls_back_on_more_than_four_sentences(self) -> None:
        http = FakeHttp(
            '{"text": "Add 4. Add 5. Add 4 and 5. Then check. Then smile."}'
        )

        result = HostedRenderer(settings(), http).render(
            request(template_text="Add 4 and 5.")
        )

        self.assertTrue(result.fallback)
        self.assertEqual(result.text, "Add 4 and 5.")

    def test_hosted_renderer_accepts_two_sentences(self) -> None:
        http = FakeHttp('{"text": "First add 4 and 5. Then check your work."}')

        result = HostedRenderer(settings(), http).render(request(allowed={4, 5}))

        self.assertFalse(result.fallback)
        self.assertEqual(result.text, "First add 4 and 5. Then check your work.")

    def test_hosted_renderer_accepts_three_sentences(self) -> None:
        text = "Nice try! Start at 4 and count up 5 more. You can do it!"
        http = FakeHttp(json.dumps({"text": text}))

        result = HostedRenderer(settings(), http).render(
            request(allowed={4, 5}, template_text="Add 4 and 5.")
        )

        self.assertFalse(result.fallback)
        self.assertEqual(result.text, text)
        self.assertEqual(result.provider, "opencode")

    def test_hosted_renderer_accepts_four_sentences(self) -> None:
        text = (
            "Nice try! Start at 4 and count up 5 more. "
            "Say it out loud. You can do it!"
        )
        http = FakeHttp(json.dumps({"text": text}))

        result = HostedRenderer(settings(), http).render(
            request(allowed={4, 5}, template_text="Add 4 and 5.")
        )

        self.assertFalse(result.fallback)
        self.assertEqual(result.text, text)
        self.assertEqual(result.provider, "opencode")
        self.assertLessEqual(len(text), 240)

    def test_hosted_renderer_rejects_three_sentences_with_a_forbidden_number(
        self,
    ) -> None:
        http = FakeHttp('{"text": "Add 4 and 5. Then try 7. You can do it."}')

        result = HostedRenderer(settings(), http).render(
            request(allowed={4, 5}, template_text="Add 4 and 5.")
        )

        self.assertTrue(result.fallback)
        self.assertEqual(result.text, "Add 4 and 5.")

    def test_hosted_renderer_rejects_empty_or_non_text_json(self) -> None:
        contents = (
            '{"text": "   "}',
            '{"text": 5}',
            '{"other": "Add 4 and 5."}',
            "[]",
        )
        for content in contents:
            with self.subTest(content=content):
                result = HostedRenderer(
                    settings(), FakeHttp(content)
                ).render(request(template_text="Add 4 and 5."))

                self.assertTrue(result.fallback)
                self.assertEqual(result.text, "Add 4 and 5.")

    def test_hosted_renderer_tolerates_a_markdown_fence(self) -> None:
        http = FakeHttp('```json\n{"text": "Add 4 and 5."}\n```')

        result = HostedRenderer(settings(), http).render(request(allowed={4, 5}))

        self.assertFalse(result.fallback)
        self.assertEqual(result.text, "Add 4 and 5.")

    def test_hosted_renderer_falls_back_without_provider_configuration(self) -> None:
        http = FakeHttp('{"text": "Add 4 and 5."}')

        result = HostedRenderer(Settings(), http).render(
            request(template_text="Add 4 and 5.")
        )

        self.assertTrue(result.fallback)
        self.assertEqual(result.text, "Add 4 and 5.")
        self.assertEqual(http.calls, [])

    def test_hosted_renderer_falls_back_without_an_http_client(self) -> None:
        result = HostedRenderer(settings(), None).render(
            request(template_text="Add 4 and 5.")
        )

        self.assertTrue(result.fallback)
        self.assertEqual(result.text, "Add 4 and 5.")

    def test_hosted_renderer_posts_the_expected_request(self) -> None:
        http = FakeHttp('{"text": "Add 4 and 5, then check your work."}')
        renderer = HostedRenderer(settings(), http, session_id="session-1")

        result = renderer.render(
            request(
                mode="hint",
                template_text="Add 4 and 5.",
                allowed={4, 5},
                child_answer="9",
            )
        )

        self.assertFalse(result.fallback)
        url, sent = http.calls[0]
        self.assertEqual(
            url,
            "https://opencode.ai/inference/go/openai/v1/chat/completions",
        )
        self.assertEqual(sent["timeout"], 3.0)
        self.assertFalse(sent["json"]["stream"])
        self.assertEqual(
            sent["json"]["response_format"], {"type": "json_object"}
        )
        self.assertEqual(sent["json"]["model"], "claude-haiku-5-5")
        self.assertEqual(sent["headers"]["Authorization"], "Bearer go-key")
        self.assertEqual(sent["headers"]["x-opencode-session"], "session-1")
        self.assertEqual(
            sent["json"]["messages"][0]["content"], SYSTEM_PROMPT
        )
        payload = json.loads(sent["json"]["messages"][1]["content"])
        self.assertEqual(payload["mode"], "hint")
        self.assertEqual(payload["problem"], "4 + 5 + 6")
        self.assertEqual(payload["step_prompt"], "Add the ones")
        self.assertEqual(payload["child_answer"], "9")
        self.assertEqual(payload["allowed_numbers"], [4, 5])
        self.assertEqual(payload["template_text"], "Add 4 and 5.")

    def test_hosted_renderer_reuses_the_vision_key(self) -> None:
        http = FakeHttp('{"text": "Add 4 and 5."}')

        HostedRenderer(
            settings(intent_api_key="", vision_api_key="vision-key"), http
        ).render(request())

        self.assertEqual(
            http.calls[0][1]["headers"]["Authorization"], "Bearer vision-key"
        )

    def test_session_header_is_only_sent_to_opencode(self) -> None:
        cases = (
            ("https://opencode.ai/inference/go/openai/v1", True),
            ("https://opencode.ai.evil.test/v1", False),
            ("https://example.test/v1", False),
        )
        for base_url, expected in cases:
            with self.subTest(base_url=base_url):
                http = FakeHttp('{"text": "Add 4 and 5."}')
                HostedRenderer(
                    settings(intent_base_url=base_url), http, session_id="s"
                ).render(request())

                headers = http.calls[0][1]["headers"]
                self.assertEqual("x-opencode-session" in headers, expected)
                self.assertEqual(
                    headers["Authorization"], "Bearer go-key"
                )


class BuildRendererTests(unittest.TestCase):
    def test_build_renderer_selects_the_template(self) -> None:
        self.assertIsInstance(build_renderer(Settings()), TemplateRenderer)
        self.assertIsInstance(
            build_renderer(Settings(tutor_renderer="template")),
            TemplateRenderer,
        )

    def test_build_renderer_selects_the_hosted_renderer_for_llm(self) -> None:
        renderer = build_renderer(
            settings(tutor_renderer="llm"), http=FakeHttp("{}")
        )

        self.assertIsInstance(renderer, HostedRenderer)

    def test_build_renderer_passes_the_session_id(self) -> None:
        http = FakeHttp('{"text": "Add 4 and 5."}')
        renderer = build_renderer(
            settings(tutor_renderer="llm"), http=http, session_id="session-9"
        )

        renderer.render(request())

        self.assertEqual(
            http.calls[0][1]["headers"]["x-opencode-session"], "session-9"
        )


if __name__ == "__main__":
    unittest.main()
