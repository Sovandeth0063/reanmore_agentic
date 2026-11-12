# Task 28: Reduce Backend Turn Latency

## Goal

Reduce avoidable delay in the snapshot API without changing the tutor's
lesson, calculator, or response rules.

## Evidence

`server/session_api.py` constructs a new `Transcriber` per session. The
faster-whisper model loads on that transcriber's first turn. The API's async
routes call synchronous transcription and HTTP provider operations through
`SessionRegistry.run`, so those operations can block the event loop. Task 27
has not yet measured their contribution on the demo laptop.

## Work

- Record cold-start and warm-turn times with local test audio before changing
  the runtime. Add real-device timings during Task 27 when hardware is ready.
- Load and warm a bounded, shared speech model at service startup or in a
  guarded lazy initializer. Check model thread safety before allowing
  concurrent transcription; limit concurrent work if necessary.
- Run blocking transcription and provider calls off the API event loop while
  preserving the per-session request order and response contract.
- Keep reusable provider connections and close them cleanly at shutdown.
- Record stage durations and failures without logging raw audio, images,
  transcripts, student names, or credentials.

## Files

`server/session_api.py`, `agent/stt.py`, provider construction, focused API
tests, and the runbook timing table.

## Acceptance

- A second session does not load a second copy of the same speech model.
- A slow provider request does not prevent an unrelated session's lightweight
  request from completing.
- A single session still processes requests in order; errors remain retryable.
- Before/after cold and warm stage timings are recorded on the demo laptop
  with local test audio. Task 27 later measures the full phone interaction.
- Python tests pass and no raw media or credentials appear in timing logs.

## Dependencies

Task 26 for the active snapshot runtime. No phone or Task 27 completion is
required for implementation or local acceptance. Task 27 later verifies the
full device experience.

## Estimate

0.75-1 day, plus a measured laptop run.

## Controller Rulings (2026-11-10)

- **Ruling: file set.** Edit `server/session_api.py`, `agent/stt.py`,
  `agent/controller.py` only if the close contract needs it, and
  `tests/test_session_api.py`, `tests/test_stt.py`. Add
  `scripts/benchmark_turn.py` and a timing section in
  `docs/DEMO-RUNBOOK.md`. Do not change the lesson, calculator, response
  catalog, contract, browser code, or the intent schema.
- **Ruling: one shared transcriber and HTTP client.** `_Runtime.ensure()` owns
  one `httpx.Client(timeout=10.0)` and one `Transcriber(settings.whisper_model)`
  for the process. Every controller receives those same instances. No session
  constructs a model or a client. The controller's `close` hook must not close
  the shared client; the runtime owns it and closes it on shutdown. Keep the
  lazy app factory: importing `server.session_api` must still build nothing.
- **Ruling: transcriber thread safety.** Guard `_get_model()` with a
  `threading.Lock` (double-checked) so concurrent first turns load one model.
  Also serialize each `transcribe()` call with a per-transcriber
  `threading.Lock`: faster-whisper's model is not documented here as reentrant,
  and serializing STT is acceptable for the demo. Model-load and transcription
  failures stay `STTError`.
- **Ruling: off the event loop.** `SessionRegistry.run` keeps the per-session
  `asyncio.Lock`, then runs a sync operation with `await
  asyncio.to_thread(operation, ...)`. Keep the existing support for an async
  callable so the registry tests still work. The lock stays held for the whole
  thread call, so one session remains ordered. `create_response()` and
  `_require_session` may stay on the loop; they do no provider work.
- **Ruling: shutdown.** Add `_Runtime.close()` that closes a runtime-owned
  HTTP client exactly once and clears the shared transcriber reference; do not
  close an injected store or an injected controller factory's resources.
  Register it with a FastAPI **lifespan** (`@asynccontextmanager`, `yield`,
  then `runtime.close()` in `finally`), because the installed Starlette no
  longer has `add_event_handler`. Calling `close()` twice is safe.
- **Ruling: timings.** Keep using `tool_calls.duration_ms` for STT, Ollama,
  vision, and calculator stages; never add raw audio, images, transcripts, or
  credentials to `details`. Add `scripts/benchmark_turn.py` with
  `--audio PATH` (raw PCM16LE mono 16 kHz), `--image PATH` (JPEG), `--turns N`
  (default 3), and `--label before|after`. It builds real settings and
  clients, times create, N warm turns, a review snapshot, and (after a place
  and choice) a check snapshot, and prints stage durations and totals as a
  table. It must fail with the configuration error when providers are not
  configured and must never print media or student text. Add a runbook timing
  section that names the command and keeps the measured numbers for Task 27;
  do not invent timings.
- **Ruling: tests.** Cover: two controllers share one transcriber and one HTTP
  client (factory call count); concurrent first `transcribe` calls load the
  model once; two concurrent `transcribe` calls do not overlap; `run()`
  executes a blocking sync operation off the event loop (a ticker advances
  while it sleeps); a blocked turn in session A does not prevent creating
  session B; the per-session order is preserved; shutdown closes a
  runtime-owned client once; an injected fake store is not closed.
- **Ruling: no pytest.** Run only `python -m py_compile` on touched Python
  files. Return status, files, compile results, acceptance status, and
  concerns. Do not install packages, run the benchmark, start services,
  commit, stage, or move files. The manager runs the suites.

## Completion Evidence (2026-11-10)

- Files: `agent/stt.py` (double-checked model lock and a per-transcriber
  transcription lock), `server/session_api.py` (shared `httpx.Client` and
  `Transcriber` in `_Runtime`, `asyncio.to_thread` in
  `SessionRegistry.run`, idempotent `close()` in a lifespan),
  `scripts/benchmark_turn.py` (new), `docs/DEMO-RUNBOOK.md`,
  `tests/test_stt.py`, `tests/test_session_api.py`.
- Verified: `python -m pytest tests -q -p no:cacheprovider` -> **249 passed,
  538 subtests passed**. `python -m py_compile` on every touched Python file
  -> **exit 0**. `python scripts/benchmark_turn.py --help` -> usage renders
  with `--audio`, `--image`, `--turns`, and `--label`.
- Manager fix during review: the installed Starlette no longer has
  `add_event_handler`, which broke app import; the shutdown hook is now a
  FastAPI lifespan (`@asynccontextmanager` with `runtime.close()` in
  `finally`).
- Written but not run: none of the Python tests were left unrun; the
  benchmark itself needs a configured `.env`, a raw PCM utterance, and a
  worksheet JPEG.
- Deferred/manual: the before/after cold and warm timings on the demo laptop.
  The script and the runbook table are ready; Task 27 fills the numbers.
- Concerns:
  - STT is serialized process-wide by the ruling; a second audio turn waits,
    but lightweight create/end requests do not.
  - The shared `httpx.Client` is assumed thread-safe for concurrent provider
    calls; the demo uses one or two sessions.
  - `SessionStore.get`/`state_block` reads still run outside its write lock;
    SQLite's serialized connection mode covers them, but the store was outside
    this card's file set.
  - `calculator.check_answer` does not record `duration_ms`, so the benchmark
    shows `-` for that stage; the check total still includes it.
  - `POST /sessions` still runs on the event loop; it does no provider work.
