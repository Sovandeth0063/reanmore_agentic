# Task 11: Agent Worker, Media Wiring, And Browser Delivery

## Goal

Make the demo runnable end to end: a LiveKit worker starts, joins the room,
subscribes the student's tracks, turns speech into transcripts, drives the
tutor, and delivers approved text to the browser.

## Findings Addressed

Review 2026-11-08, Critical 1 and Required 9:

- `agent/main.py:126` raises `RuntimeError`; `build_runtime()` and
  `handle_transcript()` have no caller.
- No `publish_data` exists anywhere, so `web/src/room.ts` `DataReceived` can
  never fire and the tutor never speaks.
- `SpeechSegmenter` and `Transcriber` are never referenced; barge-in does not
  exist.
- `Transcriber.transcribe()` passes raw PCM bytes to faster-whisper and treats
  `avg_logprob` as a 0-1 confidence.

## Specification

### Worker entrypoint

- `agent/main.py` is the agent entrypoint (architecture 02 §3.4 and §10).
  Replace the raising `main()` with
  `agents.cli.run_app(agents.WorkerOptions(entrypoint_fnc=entrypoint))`.
  Do not add a new `worker.py`; that would leave the documented entrypoint
  unusable.
- Use `livekit.agents` (`WorkerOptions`, `cli.run_app`); the worker is named
  `math-tutor` to match `server/token_server.py:37`.
- Keep `build_runtime()` and `TutorRuntime` in `agent/main.py` as the
  provider-neutral boundary.
- One `TutorRuntime` per job. Session id is `job.room.name`.
- Keep `agent/stt.py` as the repo's existing implementation of the
  architecture's `agent/audio.py` boundary; do not rename or add a parallel
  `audio.py`.

### Delivery contract (must match Task 17)

- `publish_speech(room, text: str)` sends
  `{"type": "speech", "text": <approved text>}`.
- `publish_interrupt(room)` sends `{"type": "interrupt"}`.
- `publish_looking(room, on: bool)` sends `{"type": "looking", "on": <bool>}`.
- All use `room.local_participant.publish_data(payload.encode("utf-8"), reliable=True)`.
- Only `select_response()` output or calculator-anchored guidance may be
  published. No raw model text.

### Media path

- Wait for a data message `{"type": "start"}` from the student before taking
  the Start snapshot. Order: connect -> wait for start -> subscribe/create
  video track -> `pipeline.start(track)`.
- Snapshot once at Start; on `{"type": "check"}` (sent by the browser when the
  student says check, or by the worker on a speech pause) take one fresh frame
  via `pipeline.check(track, exercise)`.
- Audio: consume `rtc.AudioStream(audio_track)`, push chunks through
  `SpeechSegmenter`, transcribe non-empty segments, then
  `runtime.handle_transcript(...)` and `publish_speech(room, response)`.
- Barge-in: on VAD speech start, call `publish_interrupt(room)` before
  transcribing.
- Log transcript text, confidence, and latency to the logger. Never store or
  write raw audio/video.

### Speech-boundary fixes

- `SpeechSegmenter` stays frame-agnostic; add
  `SileroVad(sample_rate=16000, window=512)` in `agent/stt.py` exposing
  `__call__(pcm: bytes) -> bool`, wrapping `silero_vad` and returning
  `speech_probability >= 0.5`.
- `decode_pcm16le(pcm: bytes) -> list[float]` converts LiveKit PCM16LE to
  float32 in `[-1.0, 1.0]`; `Transcriber.transcribe` accepts that.
- `Transcript.confidence` becomes `exp(mean(avg_logprob))` clamped to
  `[0.0, 1.0]`, so `0.75` thresholds mean what they say.
- All of this must be injectable for tests: `Transcriber(model_factory=None)`
  where tests pass a fake model.

### Lifecycle

- On job shutdown: `runtime.close()`.
- On participant/room disconnect: `runtime.session.memory.delete(session_id)`
  before closing, preserving the no-retention rule.
- Provider failure returns `service_error` text, not an exception (see Task
  16 for the catch types).

## Files

- Modify: `agent/main.py` (worker entrypoint, remove raising `main`)
- Modify: `agent/stt.py` (VAD adapter, PCM decode, confidence)
- Modify: `requirements.txt` (`livekit-agents`)
- Test: `tests/test_main.py`, `tests/test_stt.py`

## Tests To Write

- `test_publish_speech/interrupt/looking_use_the_documented_json`: fake room
  whose `local_participant.publish_data` records payloads.
- `test_main_waits_for_start_before_snapshot`: fake context; assert
  `pipeline.start` is not called until the start message arrives.
- `test_main_publishes_tutor_response`: fake pipeline returns "hi"; assert a
  speech message.
- `test_vad_adapter_threshold`: fake model probability 0.9/0.1 -> True/False.
- `test_decode_pcm16le`: `b"\x00\x00\xff\x7f"` -> approx `[0.0, 1.0]`.
- `test_transcriber_confidence_is_probability`: fake segment `avg_logprob=-0.1`
  -> `exp(-0.1)`.
- `test_disconnect_deletes_session_row`.

## Acceptance Criteria

- `python -m py_compile` succeeds for every touched Python file.
- The worker module imports without starting a server (CLI guarded by
  `if __name__ == "__main__"`).
- `python -m agent.main --help` works once dependencies are installed.
- No `publish_data` call carries free-form model text.
- The delivery JSON matches Task 17's browser handler exactly.
- Live check (deferred-manual): worker joins a room, receives tracks, and the
  browser speaks the first response.

## Dependencies

- Tasks 12, 14, 16 (state flow must not raise; pipeline constructor is final;
  provider failures return controlled text).

## Controller Rulings (2026-11-08)

- **Ruling: lazy livekit imports.** `livekit-agents`/`livekit.rtc` are not
  installed in this environment. `import agent.main` must succeed without them;
  import `livekit.agents` and `livekit.rtc` only inside `entrypoint`, `main`,
  and the media runner. Tests use fake rooms/tracks and must not require the
  SDK.
- **Ruling: `publish_*` helpers are async.** `rtc` publish calls are awaitable;
  define `async def publish_speech(room, text)`, `publish_interrupt(room)`,
  `publish_looking(room, on)` and `await room.local_participant.publish_data(...)`.
  A fake room with an async recorder is the test seam.
- **Ruling: `SileroVad(model=None)` and `Transcriber(model_factory=None)` accept
  fakes.** Import `silero_vad`/`faster_whisper` only when the model argument is
  absent, so the default path stays real and the test path needs no model
  download.
- **Ruling: register the data handler before waiting for `start`.** The browser
  publishes `{"type":"start"}` immediately after both tracks, which can race the
  handler; register `room.on("data_received", ...)` first, then await connect /
  the start event.
- **Ruling: keep `tests/test_main.py` and `tests/test_stt.py` self-contained.**
  They may use `unittest.IsolatedAsyncioTestCase`; no network, no LiveKit
  server, no model download.
- **Ruling: report in the final message, no report file.** No pytest or
  services; `python -m py_compile` only.

## Verification Note

The implementer writes the tests and runs only
`python -m py_compile <files>`. The manager runs
`python -m pytest tests/test_main.py tests/test_stt.py -q` once.

## Estimate

1.5 days.

## Completion Evidence (2026-11-08)

- Files: `agent/main.py`, `agent/stt.py`, `requirements.txt`,
  `tests/test_main.py` (new), `tests/test_stt.py` (new).
- Verified: `python -m pytest tests/test_main.py tests/test_stt.py -q` ->
  **24 passed**. Whole suite minus the environment-blocked token server:
  **112 passed, 347 subtests**.
- Written but not run: none.
- Fix round: the worker only read a frame on a browser `check` message, but the
  browser (card 17) sends only `start`, so handwriting was unreachable. Added
  `TutorRuntime.last_intent`; `_deliver` now takes exactly one fresh frame when
  the turn is `CHECK_ANSWER` without a spoken number (the fixed
  `check_request` path). Added the positive and negative tests.
- Concerns / accepted rulings:
  - `agent.main` imports cleanly without `livekit-agents`/`livekit.rtc`; SDK
    imports are lazy inside `main()`, `entrypoint`'s audio stream, and
    `SessionWorker._open_audio`.
  - `publish_speech`/`publish_interrupt`/`publish_looking` are async and send
    exactly `{"type":"speech","text":...}`, `{"type":"interrupt"}`,
    `{"type":"looking","on":bool}` with `reliable=True`.
  - `SessionWorker` registers `data_received`/`track_subscribed`/disconnect
    handlers before connect, waits for `start` then the video/audio tracks, and
    publishes `looking` around snapshots.
  - Reconnect: if the store already has a chosen exercise, the worker publishes
    `resume()` instead of re-parsing. Disconnect deletes the session row before
    `runtime.close()`; shutdown is idempotent.
  - `STTError` and tutor turn failures publish `service_error`; VAD failure
    disables barge-in instead of crashing.
  - `SileroVad(model=...)` and `Transcriber(model_factory=...)` are injectable;
    real models load lazily. Confidence is `exp(mean(avg_logprob))` clamped.
  - Deferred-manual: `python -m agent.main dev`, a real LiveKit join, and a real
    browser speech playback (no SDK or hardware here).
