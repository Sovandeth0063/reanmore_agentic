# Task 33: Haiku Intent Classification with Local Fallback

## Goal

Use `claude-haiku-5-5` through the OpenCode Go OpenAI-compatible route for
ambiguous/conversational intent classification, while keeping the deterministic
fast path and falling back to local `qwen3.5:4b` if the hosted call fails.

## Evidence

`agent/llm.py` only has `OllamaClient` (`/api/chat`, `format: json`). The Go
route, model, and headers are already proven for vision: `claude-haiku-5-5`
accepts text and images on
`https://opencode.ai/inference/go/openai/v1`, with `billing_source=go`; a
text-only request took about 1.4 s. Clear commands already bypass the model via
`agent/intent_parser.py`; Haiku only handles the ambiguous remainder.

## Work

- **Config.** Add `intent_provider` (`ollama` default for compatibility,
  `opencode` in `.env`), `intent_model` (`claude-haiku-5-5`), `intent_base_url`
  (`https://opencode.ai/inference/go/openai/v1`), and optional
  `intent_api_key` falling back to `vision_api_key` when empty. Validate the
  provider, URL, and model only when `opencode` is selected. `OLLAMA_MODEL`
  stays required for the fallback.
- **Client.** Refactor the JSON parsing and validation in `agent/llm.py` into a
  shared helper. Add `OpenAIIntentClient` that posts to
  `{intent_base_url}/chat/completions` with the same system prompt and user
  payload (transcript, state, state_block, answer-free exercise), Bearer key,
  `User-Agent: ai-math-tutor-demo/0.1`, and a stable
  `x-opencode-session` header. Use `response_format: json_object`, a 10-second
  timeout, and the existing alias/validation rules. Add `FallbackIntentClient`
  that tries the primary and then the Ollama client on `IntentError` or a
  provider transport failure; if both fail, raise the primary error.
- **Wiring.** The runtime/controller factory selects the client from settings
  and passes the tutoring session id. The fast path stays before the model.
  Record one `intent.interpret` tool call with the provider name
  (`opencode`/`ollama`) as details on success and the exception type on failure;
  never log transcripts, prompts, or keys. Update tests that expect
  `ollama.interpret`.
- **Checks/docs.** `scripts/check_providers.py` reports the configured intent
  provider/model and, with `--live`, sends one short text-only intent request
  and prints the recognized intent (no transcript). Update `.env.example`,
  `README`/runbook provider notes, and the task register.
- No changes to vision, STT, the contract, the tutor state machine, or the web
  UI.

## Files

`agent/config.py`, `agent/llm.py`, `server/session_api.py` (factory only),
`scripts/check_providers.py`, `tests/test_config.py`, `tests/test_llm.py`,
`tests/test_session_api.py`, `.env.example`, `docs/DEMO-RUNBOOK.md`,
`docs/tasks/TASK-REPORT.md`.

## Acceptance

- With `INTENT_PROVIDER=opencode`, an ambiguous/conversational turn uses
  `claude-haiku-5-5` and the tool log shows the provider; clear commands still
  skip both models.
- A Haiku transport/HTTP failure falls back to the local model and the session
  remains usable; if both fail, the existing retryable service text is returned.
- The intent payload never includes the expected answer; the session header is
  stable; no transcript, prompt, or key appears in logs or `--live` output.
- Config validation and redaction tests pass; the live check reports the
  intent result without printing the transcript.
- Existing tests remain green; the manager runs the suites.

## Dependencies

Task 31 (Go route/model) and the existing local Ollama model. Task 32 is not
required for the backend work but is the demo UI it feeds.

## Estimate

0.5-0.75 day.

## Controller Rulings (2026-11-12)

- **Provider split.** Clear commands remain deterministic. Haiku is the primary
  classifier for the ambiguous remainder; local qwen is the fallback, not the
  default.
- **Config default.** Code defaults to `ollama` so existing deployments do not
  break; `.env` sets `INTENT_PROVIDER=opencode`,
  `INTENT_MODEL=claude-haiku-5-5`, and
  `INTENT_BASE_URL=https://opencode.ai/inference/go/openai/v1`.
- **Key reuse.** `INTENT_API_KEY` falls back to `VISION_API_KEY`; do not
  duplicate the Go key in `.env`.
- **Timeout/fallback.** 10-second timeout; fall back to Ollama on any hosted
  failure. Do not retry Haiku in a loop.
- **Logging.** One `intent.interpret` row per model call, details only the
  provider/error type. No prompts or transcripts.
- **No pytest.** Implementer runs `python -m py_compile` only; the manager runs
  the suites.

## Completion Evidence (2026-11-12)

- Files: `agent/config.py`, `agent/llm.py`, `agent/controller.py`,
  `server/session_api.py`, `scripts/check_providers.py`, `.env.example`,
  `README.md`, `docs/DEMO-RUNBOOK.md`, `tests/test_config.py`,
  `tests/test_llm.py`, `tests/test_session_api.py`,
  `tests/test_conversation.py`.
- Verified: `py -3.10 -m pytest tests -q -p no:cacheprovider` -> **356 passed,
  785 subtests passed**. `py -3.10 -m py_compile` on every touched Python file
  -> **exit 0**. `py -3.10 scripts/check_providers.py --live` ->
  `Intent API: opencode (claude-haiku-5-5)`, `Intent configuration: PASS`,
  `Intent live check: PASS (UNCLEAR via opencode)`, alongside
  `Vision live check: PASS (12 items parsed)`.
- `.env`: `INTENT_PROVIDER=opencode`, `INTENT_MODEL=claude-haiku-5-5`,
  `INTENT_BASE_URL=https://opencode.ai/inference/go/openai/v1`; the key is
  reused from `VISION_API_KEY`.
- Written but not run: none; the suite and live checks were run.
- Deferred/manual: a live forced-failure fallback (the fallback path is covered
  by fake HTTP tests, not by breaking the real provider).
- Concerns:
  - One `intent.interpret` row is recorded per turn that reaches a classifier;
    when the fallback serves, the details report `ollama`.
  - `scripts/benchmark_turn.py` still builds `OllamaClient` directly, so its
    intent stage measures local qwen rather than the Haiku route; benchmark
    intent timing needs a follow-up.
  - `agent/intent_parser.py`'s docstring still says "local Ollama classifier";
    the behavior is unchanged but the wording is stale.
  - A hosted failure falls back to local qwen once; if both fail, the existing
    retryable service text is returned.
