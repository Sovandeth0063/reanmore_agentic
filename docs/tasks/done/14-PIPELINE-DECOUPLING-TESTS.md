# Task 14: Pipeline Decoupling And Test Hygiene

## Goal

Remove the media pipeline's reach-through into `TutorSession` internals, make
the configuration tests hermetic, and restore a green suite.

## Findings Addressed

Review 2026-11-08, Critical 3 and optional test findings:

- All three `tests/test_pipeline.py` tests raise
  `AttributeError: 'FakeTutor' object has no attribute 'memory'` because
  `agent/snapshots.py:38,46,60,67` uses `tutor.memory` and
  `tutor.session_id`.
- `tests/test_config.py` is not hermetic: `Settings.from_environment()` calls
  `_load_dotenv()`, which reads the developer's real `.env` even inside
  `patch.dict(..., clear=True)`.
- Fixed response-key selection is untested; `agent/responses.py:39
  response_keys()` has no caller.

## Specification

### Pipeline constructor

`MediaPipeline(vision, tutor, store)`:

- `vision: VisionClient`-shaped (duck typed; tests pass `FakeVision`).
- `tutor: TutorSession`-shaped.
- `store: SessionStore` required; `agent/main.py:build_runtime` passes the
  same store it gives the tutor.
- All logging goes through `self.store.append_tool_call(self.tutor.session_id,
  name, details=..., duration_ms=..., success=...)`. The pipeline must not
  touch `tutor.memory`.
- Keep the failure behaviour: `SnapshotError`, `VisionError`, `OSError` ->
  `self.tutor.start()` / `self.tutor.recover()` and a failed tool call.
- Do not catch `InvalidTransition`; that is Task 12's job to prevent.

### Configuration tests

- In `tests/test_config.py`, patch `agent.config._load_dotenv` to a no-op in
  `setUp` (or add `load_dotenv: bool = True` to `from_environment` and pass
  `False` in tests). Whichever is chosen, no test may read the working
  directory's `.env`.
- Add a test proving it: write a temp `.env` with `VISION_PROVIDER=bogus`
  in `cwd`, load with dotenv disabled, and assert no error.

### Response catalog tests

- New `tests/test_responses.py`:
  - every key from `response_keys()` formats without raising, given benign
    values;
  - `select_response("not-a-key")` raises `UnknownResponse`;
  - every `present.*`, `correct.*`, `incorrect.*` key exists for all 12 ids;
  - formatting the same key twice returns the same string (determinism).

## Files

- Modify: `agent/snapshots.py`
- Modify: `agent/main.py` (pass the store into `MediaPipeline`)
- Modify: `tests/test_pipeline.py`
- Modify: `tests/test_config.py`
- Create: `tests/test_responses.py`

## Tests To Write

- Update the three pipeline tests to construct
  `MediaPipeline(FakeVision(), FakeTutor(), SessionStore("sqlite:///:memory:"))`
  and assert one `tool_calls` row per path (success and failure).
- `test_pipeline_does_not_read_tutor_internals`: a fake tutor with no `memory`
  attribute still works.
- The `.env` hermeticity test above.
- The four catalog tests above.

## Acceptance Criteria

- `python -m pytest tests/test_pipeline.py tests/test_config.py
  tests/test_responses.py -q` reports 0 failures (manager run).
- `MediaPipeline` references no `tutor.memory`.
- No test reads the developer's `.env`.
- `python -m py_compile agent\snapshots.py agent\main.py` succeeds.

## Dependencies

- Task 12 (tutor signatures used by the fake and by `resume()`).

## Verification Note

Implementer writes tests, runs only `py_compile`. Manager runs the three-file
pytest command above.

## Estimate

0.5 day.

## Completion Evidence (2026-11-08)

- Files: `agent/snapshots.py`, `agent/main.py`, `tests/test_pipeline.py`,
  `tests/test_config.py`, `tests/test_responses.py` (new).
- Verified: `python -m pytest tests/test_pipeline.py tests/test_config.py
  tests/test_responses.py -q` -> **17 passed, 126 subtests passed**. Full suite
  minus the environment-blocked token server: **53 passed, 314 subtests**.
- Written but not run: none.
- Concerns:
  - `TutorSession.start(worksheet)` and `check_handwriting(reading)` still append
    their own bare `vision.*` tool-call rows, so a real successful call logs two
    rows (one from the tutor, one from the pipeline). Cards 12/14 own different
    files; the de-duplication ruling is recorded in card 15, which owns
    `agent/tutor.py`.
  - `MediaPipeline.start()` failure still calls `tutor.start()` with no
    worksheet, assuming the initial `GREETING` state. `InvalidTransition` is
    deliberately not caught.
  - The config test patches `_load_dotenv` in `setUp` and proves hermeticity
    with a temp cwd, so a developer's `.env` is never read or written.
  - A fourth pipeline test (`check` failure) was added to exercise `recover()`
    and the failed tool-call row; the card named three but required one row per
    path.
