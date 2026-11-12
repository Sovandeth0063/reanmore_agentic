# Task 16: Provider Failure Handling And Session Retention

## Goal

Turn every provider failure into a controlled, non-secret response, and stop
session rows from accumulating indefinitely.

## Findings Addressed

Review 2026-11-08, Required 8 and 10:

- `raise_for_status()` raises `httpx.HTTPStatusError`, which is not
  `OSError`/`ValueError`/`RuntimeError`. It escapes `agent/main.py:54` and
  `agent/snapshots.py:36,58`, so a 401/500 crashes the turn.
- Response-shape errors (`KeyError`, `IndexError`) also escape.
- `SessionStore.delete()` exists and is tested but no production path calls
  it, and there is no retention sweep.

## Specification

### Vision (`agent/vision.py`)

- Wrap the HTTP call: `except httpx.HTTPError as error: raise
  VisionUnavailableError("Vision request failed") from error`.
- Wrap response decoding: `except (KeyError, IndexError, TypeError) as error:
  raise VisionError("Vision returned an invalid response") from error`.
- Keep the existing `VisionUnavailableError` for missing configuration or HTTP
  client.
- Error strings must never contain `settings.vision_api_key`, the request URL,
  or the raw provider body.

### Intent (`agent/llm.py`)

- Same wrapping: `httpx.HTTPError` -> `IntentError("Ollama request failed")`;
  shape errors -> `IntentError("Ollama returned an invalid response")`.
- `IntentError` remains a `ValueError`, so `agent/main.py` already converts it
  to `service_error`.

### Pipeline and worker

- `agent/snapshots.py` already catches `VisionError`; no new catch type is
  needed once Task 16's wrapping is in place. Do not add a bare
  `except Exception`.
- Add `STTError(RuntimeError)` in `agent/stt.py` and raise it from model load
  and transcription failures. The worker (Task 11) catches `STTError` and
  publishes `select_response("service_error")`.

### Retention

- `SessionStore.prune(max_age_hours: float = 24) -> int` deletes sessions whose
  `updated_at` is older than `now - max_age_hours`, plus their `turns` and
  `tool_calls` rows. Returns the number of sessions deleted.
- `build_runtime()` calls `prune()` once at startup; failures are logged, not
  fatal.
- Session-end deletion stays in Task 11's disconnect handler; `prune()` is the
  backstop.

## Files

- Modify: `agent/vision.py`
- Modify: `agent/llm.py`
- Modify: `agent/stt.py`
- Modify: `agent/memory.py`
- Modify: `agent/main.py` (call `prune()` in `build_runtime`)
- Test: `tests/test_vision.py` (new), `tests/test_llm.py`,
  `tests/test_memory.py`

## Tests To Write

- `test_vision_http_error_is_domain_error`: fake HTTP client raising
  `httpx.HTTPStatusError` -> `VisionUnavailableError`; assert the API key and
  URL are absent from `str(error)`.
- `test_vision_malformed_body_is_domain_error`: missing `choices` ->
  `VisionError`.
- `test_vision_requires_configuration`: hosted without key, local without
  model -> `VisionUnavailableError`.
- `test_ollama_http_error_is_intent_error`.
- `test_prune_removes_only_old_sessions`: insert two sessions, backdate one via
  `update`/direct SQL, assert one deleted with its turns and tool calls.
- `test_prune_returns_zero_when_empty`.

## Acceptance Criteria

- A 401/500 from the vision provider or Ollama produces `service_error`, not a
  traceback.
- No exception message contains a secret or a provider URL.
- `prune()` is called once per `build_runtime()`.
- `python -m py_compile` succeeds for every touched file.

## Dependencies

- Task 14 (pipeline constructor and test harness).
- Task 19 (the configurable vision endpoint; do not re-add a hardcoded host).

## Controller Rulings (2026-11-08)

- **Ruling: extend `tests/test_vision.py`; do not recreate it.** Card 19 already
  added that suite (`FakeHttp`, endpoint, fence, 400-retry). Keep those tests and
  add the HTTP/body error cases alongside them.
- **Ruling: preserve the card-19 retry.** `_request` retries exactly once without
  `response_format` when a 400 body mentions it. Wrap the domain error only
  after that decision: a non-retriable `httpx.HTTPStatusError` and a failed retry
  both become `VisionUnavailableError`; local never retries. Do not turn the
  retry into a generic `except Exception`.
- **Ruling: `STTError` lives in `agent/stt.py`** (the repo's audio boundary; the
  architecture calls the module `audio.py`). Do not add a parallel `audio.py`.
- **Ruling: prune failures are logged, not fatal**, and `prune()` must delete
  the session's `turns` and `tool_calls` rows in the same operation.
- **Ruling: report in the final message, no report file.** No pytest or services;
  `python -m py_compile` only.

## Verification Note

Implementer writes tests, runs only `py_compile`. Manager runs
`python -m pytest tests/test_vision.py tests/test_llm.py tests/test_memory.py
-q`.

## Estimate

0.5 day.

## Completion Evidence (2026-11-08)

- Files: `agent/vision.py`, `agent/llm.py`, `agent/stt.py`, `agent/memory.py`,
  `agent/main.py`, `tests/test_vision.py`, `tests/test_llm.py`,
  `tests/test_memory.py`.
- Verified: `python -m pytest tests/test_vision.py tests/test_llm.py
  tests/test_memory.py -q` -> **23 passed, 11 subtests passed**. Whole suite
  minus the environment-blocked token server: **88 passed, 347 subtests**.
- Written but not run: none.
- Concerns / accepted rulings:
  - Vision HTTP errors become `VisionUnavailableError("Vision request failed")`;
    malformed bodies become `VisionError("Vision returned an invalid response")`.
    The card-19 `response_format` 400 retry is preserved and wraps a failed
    retry too. Messages contain no key, URL, or provider body.
  - `IntentError` is still a `ValueError`, so `TutorRuntime` returns
    `service_error` for every Ollama HTTP/shape failure.
  - `STTError(RuntimeError)` is added and raised from model load/transcribe.
    Nothing in the repo catches it yet; card 11's worker publishes
    `service_error`.
  - `SessionStore.prune(max_age_hours=24)` deletes expired sessions plus their
    `turns`/`tool_calls` in one commit. `build_runtime()` calls it once and logs
    `sqlite3.Error`/`OSError` without failing startup.
  - `test_does_not_retry_on_non_400_status` now expects
    `VisionUnavailableError` instead of a leaked `HTTPStatusError`; the
    "exactly one HTTP call" assertion is intact.
  - The start-path vision failure still falls back to `tutor.start()` (card 04
    contract), not `service_error`; only `check()` recovers to `service_error`.
