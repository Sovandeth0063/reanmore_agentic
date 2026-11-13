# Task 34: VoxPocket TTS and CPU Speech-to-Text

## Goal

Make the live demo use the local VoxPocket TTS voice, keep STT working on the
RTX 4050, and verify the real audio path end to end.

## Evidence

- VoxPocket `muyleanging/VoxPocket-TTS-Khmer` generated three English tutor
  lines on the RTX 4050: 2.12 GB post-load, 2.45 GB peak, 44.1 kHz; after
  warmup RTF 1.12 and 0.99. `small.en` transcribed all three lines correctly.
- The model/runtime is installed only in `C:\Users\ASUS\voxcpm-tts`; the model
  cache is `C:\Users\ASUS\voxcpm-hf` (~13 GB).
- The main Python 3.10 STT fails when faster-whisper chooses CUDA:
  `RuntimeError: Library cublas64_12.dll is not found`. CPU `small.en` works.
- The app still uses browser `SpeechSynthesis`; no TTS service exists.

## Work

- **STT CPU.** Add `WHISPER_DEVICE` (default `cpu` for the demo) and
  `WHISPER_COMPUTE_TYPE` (default `int8`) to `agent/config.py`; pass them into
  `Transcriber` and `WhisperModel`. Set them in `.env` and `.env.example`.
  Update config/STT tests and the runtime factory. Verify a short real WAV
  transcribes through the same path the API uses.
- **TTS service.** Add `scripts/voxpocket_tts_server.py`:
  - `create_app(engine_factory=None, ...)` with a lazy default engine that
    imports `voxcpm` only inside the factory and loads
    `muyleanging/VoxPocket-TTS-Khmer` with `load_denoiser=False`,
    `optimize=False`, `device=cuda`.
  - `POST /tts` JSON `{text}` -> `audio/wav` (44.1 kHz, PCM16); reject empty
    or >400 characters; split sentences and concatenate; prepend the designed
    voice prompt `(A warm, patient Grade 3 math tutor voice, clear and
    friendly)`; serialize generation with a lock; run generation off the
    event loop.
  - `GET /health` -> model/sample-rate readiness without loading lazily on a
    health check.
  - CLI defaults `--host 127.0.0.1 --port 8001`.
  - Fake-engine tests in the main env; `voxcpm` must not be imported at module
    load.
- **Frontend speech.** Add `web/src/speech.ts` with
  `createVoxPocketSpeech({ fetchImpl, audioFactory, createObjectUrl,
  revokeObjectUrl, browserFallback })`:
  - `speak(text, handlers)` calls `POST /tts`, plays the returned WAV through
    an `Audio` object, calls `onStart` before the request (so the recorder is
    gated while generating/playing), and `onEnd` on ended/error/abort.
  - `cancel()` aborts the request, pauses/clears the audio, revokes the URL.
  - Any HTTP/audio failure falls back to browser `SpeechSynthesis`; never
    leave the UI silent.
  - `main.ts` uses this adapter; keep the `TutorSpeech` interface. Add
    `/tts` -> `http://127.0.0.1:8001` to `vite.config.ts`.
  - Tests for request/body, playback, cancel, fallback, and URL cleanup.
- **Docs/runbook.** Third terminal:
  `C:\Users\ASUS\voxcpm-tts\Scripts\python.exe scripts\voxpocket_tts_server.py
  --host 127.0.0.1 --port 8001`; browser TTS is the fallback; model cache
  location; CPU STT setting; no key. Update README, runbook, `.env.example`,
  task register.

## Files

`agent/config.py`, `agent/stt.py`, `server/session_api.py`,
`scripts/voxpocket_tts_server.py`, `tests/test_config.py`,
`tests/test_stt.py`, `tests/test_tts_server.py`, `web/src/speech.ts`,
`web/src/main.ts`, `web/tests/speech.test.ts`, `web/vite.config.ts`,
`.env.example`, `README.md`, `docs/DEMO-RUNBOOK.md`,
`docs/tasks/TASK-REPORT.md`.

## Acceptance

- The API's STT path transcribes a short 16 kHz WAV on CPU without the cuBLAS
  error, and a normal speech turn returns a transcript rather than service
  text.
- `POST /tts` returns a valid 44.1 kHz WAV for a tutor line; `small.en`
  transcribes it back correctly; the service stays responsive under a second
  request.
- The dashboard uses VoxPocket speech; cancel/interruption stops audio; if the
  TTS service is down, browser TTS speaks the line.
- `tsc --noEmit`, `npm test`, `npm run build`, and the Python suite pass.
- Live test: start backend + TTS + Vite, request `/tts` through the Vite proxy,
  run the real STT path, and complete a browser Start smoke test with the demo
  image.
- No raw audio is stored; the TTS service never logs text, prompts, or keys.

## Dependencies

Tasks 32 and 33.

## Estimate

1-1.5 days.

## Controller Rulings (2026-11-13)

- **Separate TTS service.** Do not install VoxCPM/torch CUDA into the main
  backend environment. The service runs from `C:\Users\ASUS\voxcpm-tts`; the
  repo script is environment-agnostic and imports `voxcpm` lazily.
- **STT CPU.** Default to CPU int8 for reliability; the GPU is reserved for
  VoxPocket. No silent GPU retry loops.
- **Browser fallback.** VoxPocket is primary; `SpeechSynthesis` remains the
  fallback when the service is unavailable or playback fails.
- **No contract change.** The browser still receives `tutor_text`; it calls
  the local TTS service separately.
- **Bounded input.** TTS text is capped at 400 characters; sentences are split;
  no transcript logging.
- **Tests.** Implementer writes tests and runs `py_compile`/`tsc` only; the
  manager runs the suites and the live service/browser checks.

## Live verification (2026-11-13)

- The isolated TTS service started from `C:\Users\ASUS\voxcpm-tts`; `/health`
  returned 200 with `loaded:false` before the first request, as designed.
- First `POST /tts` ("Ask me to review your worksheet.") loaded the cached
  model and returned HTTP 200 in 53.8 s. The WAV was 1 channel, 16-bit,
  44.1 kHz, 2.40 s; CPU `small.en` transcribed it exactly.
- A warm second request returned 200 in 2.70 s; ASR exact. Through the Vite
  proxy (`https://localhost:5173/tts`) a request returned 200 in 1.75 s with a
  valid 44.1 kHz WAV and correct ASR.
- The API's real STT path: `POST /sessions`, then a 16 kHz PCM16LE upload of
  the same line, returned 200 with `status:"checking_sheet"` and
  `capture_request:"review"` — the transcript drove the normal review intent,
  with no cuBLAS error and no service text.
- Browser smoke in Chrome (fake camera showing `docs/image.png`, fake mic
  playing the VoxPocket line): Start -> dashboard, turn 200 -> camera capture,
  snapshot 200 -> "I can see the worksheet..." summary, a VoxPocket line
  played from a blob URL, and End restored the Start panel with the camera
  off.
- Fallback drill with the TTS service stopped: `/tts` returned 500 and the
  dashboard spoke the line through `SpeechSynthesis`. During a slow
  badcase-retry generation the 20 s watchdog also fell back live, so the
  recorder was never left gated.
- Suites: 380 Python tests + 785 subtests passed; 84 web tests passed;
  `tsc --noEmit` exit 0; `npm run build` clean.
- Task review returned CHANGES REQUESTED for the missing engine-factory and
  log-redaction tests plus an optional watchdog; all three were implemented in
  the review fix round and re-verified.

## Controller Rulings (2026-11-13, review fix round)

The task review returned CHANGES REQUESTED. Address these in the existing
files; do not widen scope:

1. **Engine factory test.** In `tests/test_tts_server.py`, inject a fake
   `sys.modules["voxcpm"]` (as `tests/test_stt.py` fakes `faster_whisper`) and
   call the default engine factory. Assert the exact `VoxCPM.from_pretrained`
   kwargs: `muyleanging/VoxPocket-TTS-Khmer`, `load_denoiser=False`,
   `optimize=False`, `device="cuda"`, the `%USERPROFILE%\voxcpm-hf` default
   cache, and `local_files_only=True` unless `VOXPOCKET_ALLOW_DOWNLOAD=1`.
2. **Log-redaction test.** For a failing synthesis, use `assertLogs` and assert
   neither the input text nor `VOICE_PROMPT` appears in any record, in addition
   to the existing response-body assertion.
3. **TTS watchdog (controller ruling).** Add an optional injectable
   `timeoutMs` (default 20000) to `createVoxPocketSpeech`. If the request has
   not settled by then, fall back to the browser voice; a late response or
   blob must not start audio after the fallback (guard with a `settled` flag
   cleared on `cancel`). Add tests with a short timeout and a late resolve.
   Clear the timer in `release`/`finish` so normal playback does not leak it.
4. Re-run `python -m py_compile` on the changed Python file and
   `node node_modules/typescript/bin/tsc --noEmit` in `web/`; do not run the
   suites, services, or model generation. Do not commit.
