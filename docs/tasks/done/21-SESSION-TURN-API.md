# Task 21: Session, Speech-Turn, and Snapshot API

## Goal

Replace the room-token entrypoint with an HTTPS API that owns a short-lived
tutor session and accepts one audio turn or still image at a time.

## Evidence

`server/token_server.py` creates LiveKit rooms and tokens. There is no
session creation, audio upload, image upload, or explicit session end endpoint.
`agent/main.py` drives a LiveKit job rather than an HTTP request.

## Work

- Add the endpoints from Task 20 with generated opaque session ids. Never
  accept an expected answer from the browser.
- Decode a bounded audio upload to the sample format expected by
  `agent/stt.py`, transcribe it, and route the transcript to a provider-neutral
  tutor controller. Return one typed response. Do not save the audio file.
- Route a bounded JPEG upload with `purpose=review` or `purpose=check`.
  Enforce the current session state and selected exercise before processing.
  Process bytes transiently; do not write images to SQLite or disk.
- Serialize requests per session so overlapping speech and image requests
  cannot advance the state out of order. Return a clear retryable error on
  timeout or provider failure.
- End and expire sessions, including turns and tool logs. A short reconnect
  can use the same session id until expiry.
- Keep the lesson, calculator, memory, and vision components reusable. Remove
  the LiveKit worker from the new request path.

## Files

`server/` API module, `agent/main.py` or a new provider-neutral controller,
`agent/stt.py`, `agent/memory.py`, `requirements.txt`, and API tests.

## Acceptance

- An API test can create a session, submit a fake audio turn, submit a fake
  JPEG, receive typed tutor responses, and end the session.
- A second concurrent request cannot corrupt the selected exercise or step.
- Invalid session, wrong purpose, oversize media, and provider failure have
  explicit non-secret responses.
- No LiveKit server or credential is needed for the new API tests.

## Dependencies

Task 20.

## Estimate

1.25 days.

## Controller Rulings (2026-11-09)

- **Ruling: file set.** Create `server/session_api.py`, `agent/controller.py`,
  and `tests/test_session_api.py`. Add `agent/responses.py`,
  `tests/test_responses.py`, `tests/test_memory.py`, and
  `server/contract.py` to the touched set. Do not edit `agent/main.py`; the
  legacy LiveKit worker stays until Task 26. Do not edit `agent/llm.py`; Task
  24 owns the intent schema.
- **Ruling: contract is fixed by Task 20.** Import `SessionResponse`,
  `EndResponse`, status/capture constants, media limits, and validators from
  `server/contract.py`. Do not redefine them or add a second response shape.
- **Ruling: app factory.** `server/session_api.py` exposes
  `create_app(*, settings=None, store=None, lesson=None,
  controller_factory=None)` and a module-level `app = create_app()`. Do not
  read `.env` or construct models at import time; do it on first use/lifespan.
  Tests pass fakes so no provider, service, or credential is needed.
- **Ruling: controller.** `agent/controller.py` defines `TutorController`
  with `create_response()`, `handle_audio()`, `handle_snapshot()`,
  `handle_transcript()`, and `end()`. It composes the existing lesson, memory,
  tutor, vision, intent, and STT modules and imports no LiveKit code. Record
  STT/intent/vision tool calls through `SessionStore`.
- **Ruling: audio path.** Validate with the Task 20 contract, decode with
  `agent.stt.decode_pcm16le`, transcribe with the injected `Transcriber`, then
  interpret. Empty or low-confidence transcripts return `UNCLEAR` without
  advancing state. `STTError` / `IntentError` return non-secret service text in
  a normal `SessionResponse`; the session stays usable. Never save audio.
- **Ruling: snapshot path.** Validate with the Task 20 contract. `review`
  calls `vision.parse_worksheet`; if the parse is not a valid fixed sheet, do
  not call `tutor.start()` — return `status="adjust_sheet"` with a placement
  retry message and leave the tutor ready to retry. `check` requires a selected
  exercise, calls `vision.read_handwriting`, then `tutor.check_handwriting`.
  `VisionError` returns service text and keeps the exercise retryable. Never
  save images.
- **Ruling: new response keys.** Add `review_prompt` ("Ask me to review your
  worksheet."), `review_request` ("Let me look at your worksheet."), and
  `placement_retry` ("Please place the whole sheet in the camera view. Say
  ready when it is there.") to the catalog. Task 23 extends the catalog; do not
  duplicate its keys here.
- **Ruling: state and memory.** Add `placement_confirmed` to the SQLite
  sessions table and `SessionState`; create the connection with
  `check_same_thread=False` and guard mutating calls with a re-entrant lock.
  Persist it only when a valid review parse reaches choice. Update
  `tests/test_memory.py` for the new field.
- **Ruling: dependency.** Add `python-multipart>=0.0.9,<1` to
  `requirements.txt`; FastAPI needs it for the multipart upload endpoints.
- **Ruling: serialization.** Put one `asyncio.Lock` per session in a registry
  and run each turn/snapshot inside it. Expose the registry's `run()` so a test
  can prove two concurrent operations execute one at a time.
- **Ruling: API tests.** Use `create_app` with an in-memory store and fakes.
  Cover: create -> audio turn (`REVIEW`) -> review snapshot -> choice turn ->
  check-writing turn -> check snapshot -> delete; invalid session; wrong
  purpose; oversized audio/image; unsupported MIME; provider failure with
  non-secret text; no LiveKit import or credential; no media rows/files.
- **Ruling: no pytest.** Run only `python -m py_compile` on touched Python
  files. Return status, files, compile results, acceptance status, and
  concerns. The manager verifies with
  `python -m pytest tests/test_session_api.py tests/test_memory.py -q` and
  installs `python-multipart` if the environment lacks it.

## Completion Evidence (2026-11-09)

- Files: `agent/controller.py` (new), `server/session_api.py` (new),
  `tests/test_session_api.py` (new), `agent/memory.py`,
  `agent/responses.py`, `requirements.txt`, `tests/test_memory.py`,
  `tests/test_responses.py`.
- Verified: `python -m pytest tests/test_session_api.py tests/test_memory.py
  tests/test_responses.py -q -p no:cacheprovider` -> **47 passed, 161
  subtests passed**. Whole suite `python -m pytest tests -q` -> **187 passed,
  381 subtests passed**, with one pre-existing environment failure
  (`tests/test_token_server.py`, `ssl.SSLError` while importing `livekit.api`
  on Python 3.14) unrelated to this card. `python -m py_compile` on every
  touched Python file -> **exit 0**.
- Manager corrections during review:
  - `CHOOSE_EXERCISE` and the rebuilt-controller `create_response()` path now
    return `status="speaking"` with no `capture_request`; `reading_work` is
    reserved for a fresh written-work read (UI brief: exercise chosen shows
    listening or speaking, not "reading an answer").
  - Added `test_rebuilt_controller_resumes_a_selected_exercise` so the
    reconnect branch is covered.
- Written but not run: none; the API, memory, and response suites were run.
- Deferred/manual: real faster-whisper, Ollama, and hosted-vision calls; the
  Safari browser flow (Task 22); a real `.env`.
- Concerns:
  - Controller methods are synchronous and run on the event loop inside the
    async endpoints. Fine for one demo client; a slow provider stalls other
    sessions.
  - `_PROVIDER_ERRORS` includes bare `RuntimeError`/`ValueError`, so a genuine
    programming bug would be reported as retryable service text instead of a
    500.
  - The exercise payload passed to intent and vision includes the expected
    `answer`. Task 24 must stop the intent model from inventing
    `candidate_answer` from it, and Task 25 must remove the answer from the
    handwriting prompt.
  - `SessionStore.prune()` only runs when a runtime starts; a long-lived
    process does not expire idle sessions between starts.
  - `LIST_WORKSHEET` still reaches `tutor.list_worksheet()` without a
    placement gate; Task 23/24 own that gate.
  - `CHECK_ANSWER` with a `candidate_answer` calls `tutor.check()` without a
    fresh snapshot; Task 25 owns the written-work requirement.
  - Request-size limits are enforced after FastAPI parses the multipart body,
    so the cap bounds retained media, not bytes received.
