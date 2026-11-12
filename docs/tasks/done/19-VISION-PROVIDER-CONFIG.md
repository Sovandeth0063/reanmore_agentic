# Task 19: Configurable Vision Provider Endpoint

## Goal

Remove the hardcoded OpenAI URL so the hosted vision provider can be any
OpenAI-compatible gateway, including OpenCode Console.

## Findings Addressed

Review addendum (2026-11-08, human correction):

- `agent/vision.py:102` hardcodes
  `https://api.openai.com/v1/chat/completions`. The demo owner uses OpenCode,
  not OpenAI, so the hosted path cannot be used at all.
- `agent/config.py` has no `VISION_BASE_URL`; hosted validation checks only
  `VISION_MODEL` and `VISION_API_KEY`.
- `.env.example` has no endpoint variable, so the provider choice is invisible
  from the repository.

## Specification

### Settings (`agent/config.py`)

- Add `vision_base_url: str = ""` and read `VISION_BASE_URL`.
- Hosted (`VISION_PROVIDER=hosted`) requires `VISION_BASE_URL`, `VISION_MODEL`,
  and `VISION_API_KEY`. Local still requires only `VISION_MODEL`.
- Validate the scheme with `urlparse(...).scheme in {"http", "https"}`; report
  the variable name only, never the value.

### Client (`agent/vision.py`)

- Hosted endpoint:
  `settings.vision_base_url.rstrip("/") + "/chat/completions"`.
  The base URL is everything before `/chat/completions`, so:
  - OpenCode Console: `https://opencode.ai/inference/openai/v1`
  - OpenAI: `https://api.openai.com/v1`
  - a self-hosted gateway: its own `/v1`
- Keep the OpenAI-compatible request body (`model`, `messages` with
  `image_url`, `stream: false`).
- Keep `response_format: {"type": "json_object"}`. If the endpoint returns
  HTTP 400 and the body mentions `response_format`, retry once without it and
  rely on the instruction text. Do not retry on other statuses (Task 16 owns
  those).
- Before `json.loads`, strip a leading/trailing Markdown fence
  (` ```json ... ``` `), because gateways vary.
- Local provider path is unchanged.

### Documentation and placeholders

- `.env.example`: add
  `VISION_BASE_URL=` with a comment naming OpenCode Console's base URL and
  stating that the value is a URL, not a secret. Keep `VISION_API_KEY=` empty.
- `README.md` environment list: add `VISION_BASE_URL`.
- Note in `docs/DEMO-RUNBOOK.md`: the chosen vision model must accept image
  input through `image_url` content.

### Ruling recorded here

OpenCode Console's free tier is documented as usable from the OpenCode client;
another client may need a paid Console model or OpenCode Go. The demo therefore
supports three configurations with the same code: OpenCode Console (free
vision model if the key allows it), a paid Console model, or local Ollama
vision with no key. The card must not hardcode any of them.

## Files

- Modify: `agent/config.py`
- Modify: `agent/vision.py`
- Modify: `.env.example`
- Modify: `README.md`, `docs/DEMO-RUNBOOK.md`
- Modify: `scripts/check_providers.py`
- Modify: `tests/test_config.py`, `tests/test_token_server.py`
- Test: `tests/test_vision.py`

## Tests To Write

- `test_hosted_vision_requires_base_url`: model + key without base URL ->
  `ConfigurationError` naming `VISION_BASE_URL`.
- `test_vision_posts_to_configured_endpoint`: settings with
  `https://opencode.ai/inference/openai/v1`; fake HTTP records the URL; assert
  it equals `.../v1/chat/completions` and the `Authorization` header is
  `Bearer <key>`.
- `test_no_hardcoded_openai_url`: `grep`-style assertion over `agent/vision.py`
  (read the file in the test) contains no `api.openai.com`.
- `test_strips_markdown_json_fence`: ` ```json\n{"items": [], "confidence":
  0.9}\n``` ` parses.
- `test_retries_without_response_format_on_400`: first call raises an
  HTTPStatusError with `response_format` in the body; second succeeds; assert
  the retry body has no `response_format`.
- `test_local_vision_ignores_base_url`: `VISION_PROVIDER=local` works with an
  empty base URL.

## Acceptance Criteria

- No provider hostname is hardcoded in `agent/`; the endpoint comes from
  `VISION_BASE_URL`.
- A hosted config with an OpenCode base URL validates and posts to
  `<base>/chat/completions`.
- The error message for a bad base URL names the variable, not the value.
- `.env.example` still contains no real key; `VISION_API_KEY` stays empty.
- `python -m py_compile` succeeds for every touched file.

## Dependencies

- None. Tasks 16 and 18 assume this is in place.

## Controller Rulings (2026-11-08)

- **Ruling: add `tests/test_token_server.py` to the file list.** `GET
  /get-token` calls `Settings.from_environment()`, so making `VISION_BASE_URL`
  required for hosted turns the two token tests into 503s unless their env
  fixtures include it. Add `VISION_BASE_URL=http://localhost:8080/v1` to both
  fixtures; do not weaken either assertion. Cost if wrong: the token tests go
  red.
- **Ruling: add `scripts/check_providers.py` to the file list.** The hosted
  vision health check must require `VISION_MODEL` and `VISION_BASE_URL`
  (local: `VISION_MODEL` only), so it cannot report PASS for a
  misconfigured hosted setup. Cost if wrong: a green check hides a broken
  provider.
- **Ruling: report in the final message, no report file.** Return status,
  files, compile command/result, acceptance status, and concerns. Do not run
  pytest or start any service. Cost if wrong: the manager re-reads the diff.

## Verification Note

Implementer writes tests, runs only `py_compile`. Manager runs
`python -m pytest tests/test_config.py tests/test_vision.py -q`.

## Estimate

0.25 day.

## Completion Evidence (2026-11-08)

- Files: `agent/config.py`, `agent/vision.py`, `scripts/check_providers.py`,
  `.env.example`, `README.md`, `docs/DEMO-RUNBOOK.md`, `tests/test_config.py`,
  `tests/test_vision.py`, `tests/test_token_server.py`.
- Verified: `python -m pytest tests/test_config.py tests/test_vision.py -q` ->
  **13 passed** (after the retry fix below). `python -m py_compile` on every
  touched file -> exit 0.
- Fix round: the first run failed
  `test_retries_without_response_format_on_400` because `_request` mutated the
  request dict with `pop("response_format")` before the retry. The retry now
  builds a separate dict; the first recorded POST still contains
  `response_format`.
- Written but not run: `tests/test_token_server.py` (fixtures updated with
  `VISION_BASE_URL`). The file cannot execute in this environment: `livekit` was
  installed, but `aiohttp` fails at import with
  `ssl.SSLError: [SSL] unknown error (0xa080024)` under Python 3.14 / OpenSSL
  3.5.7. This is an interpreter/dependency incompatibility, not a code defect.
- Deferred/manual: a real hosted vision request (no key configured).
- Concerns:
  - Scheme validation rejects a malformed leftover `VISION_BASE_URL` even when
    `VISION_PROVIDER=local`. Accepted: the card says "validate the scheme"
    without limiting it to hosted, and a malformed value is a configuration
    error either way. Cost if wrong: a local-only setup must clear the variable.
  - `_check_vision` requires model + base URL for hosted and model for local; it
    does not re-check the key because `from_environment()` already requires it
    for hosted before the check runs. Accepted.
  - The Markdown-fence stripper leaves a single-line ` ```json {...}``` ` blob
    unchanged; such a blob could not parse anyway. Accepted.
  - The free-tier NVIDIA vision endpoint logs requests. Before a real demo with
    a child's handwriting, use a paid/zero-retention model or local Ollama
    vision. Recorded in `docs/DEMO-RUNBOOK.md` scope notes only; no key or
    provider decision is committed.
