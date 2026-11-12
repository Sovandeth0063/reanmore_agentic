# Demo Task Report

## Snapshot Review Migration (2026-11-09)

The current target is the
[snapshot-based one-worksheet architecture](../architecture/01-PRD-ai-math-tutor.md).
The student requests a review; the tutor checks sheet placement, summarizes
the operation types, takes a spoken section/item choice, converses without
additional images, and captures a new image to check written work. One
exercise is demonstrated within five minutes. Tasks 20-25 implement this
target on the HTTPS snapshot path; Task 26 removes the legacy LiveKit runtime.
Task 32 moves the UI and voice to the laptop with a local webcam, and Task 27
rehearses that five-minute flow end to end. There is no iPhone or room
transport in the active demo.

| ID | New task | Depends on | Estimate | Status | Main gap |
| --- | --- | --- | --- | --- | --- |
| [20](done/20-SNAPSHOT-CONTRACT-CONFIG.md) | Snapshot contract and configuration | None | 0.5 day | DONE | Shared contract, snapshot/livekit config split, TS mirror, and contract tests complete (2026-11-09); `test_config.py` + `test_contract.py` -> 50 passed, 13 subtests; `tsc --noEmit` exit 0 |
| [21](done/21-SESSION-TURN-API.md) | Session, speech-turn, and snapshot API | 20 | 1.25 days | DONE | Provider-neutral controller, FastAPI session/turn/snapshot/end routes, per-session lock, lazy runtime, multipart dependency, and API tests complete (2026-11-09); `test_session_api.py` + `test_memory.py` + `test_responses.py` -> 47 passed, 161 subtests; whole suite 187 passed except the pre-existing LiveKit import failure |
| [22](done/22-BROWSER-LOCAL-CAPTURE-VOICE.md) | Browser local capture and voice | 20, 21 | 1.25 days | DONE | Local preview, PCM16LE turn recorder, turn detector, HTTP client, capture-on-`capture_request`, and browser SpeechSynthesis complete (2026-11-09); `tsc --noEmit` exit 0; `npm test` -> 40 passed; Safari/device checks deferred-manual |
| [23](done/23-PLACEMENT-GATE-WORKSHEET-SUMMARY.md) | Placement gate and summary | 20, 21 | 1 day | DONE | Structured placement results, `WAITING_FOR_PLACEMENT`, specific retry prompts, A/B operation summary, no 12-id list, and no-bypass gates complete (2026-11-09); named suites 104 passed, 244 subtests; whole suite 216 passed with only the pre-existing LiveKit import failure |
| [24](done/24-TUTOR-SPEECH-FLOW.md) | Review, choice, and step-by-step speech | 20, 23 | 1 day | DONE | Canonical intent set, section/number slots, ambiguous-choice prompt, first guiding step, ask-step/repeat, written vs spoken checks, answer-free intent payload, and scripted conversation tests complete (2026-11-09); named suites 127 passed, whole suite 240 passed with only the pre-existing LiveKit import failure |
| [25](done/25-SELECTED-WORK-OCR-CHECK.md) | Selected-work OCR and verified feedback | 22-24 | 1 day | DONE | Visibility/reason read contract, answer-free selected-item payload, uncertain reads never graded, forced fresh image for written checks, spoken-only fallback, and handwriting suite complete (2026-11-10); named suites 143 passed, whole suite 267 passed with only the pre-existing LiveKit import failure |
| [26](done/26-REMOVE-LEGACY-MEDIA-PATH.md) | Remove legacy media path and update setup | 21-25 | 0.75 day | DONE | LiveKit worker/token/browser/infra files, settings, and packages removed; VAD classes removed; README, runbook, spec, checker, and skills moved to the two-terminal snapshot path (2026-11-10); 241 Python tests passed, 40 web tests passed, `tsc` and `npm run build` clean |
| [27](27-SNAPSHOT-E2E-REHEARSAL.md) | Integration tests and laptop webcam rehearsal | 26, 32 | 1 day + webcam/provider access | TODO | No end-to-end proof of the laptop/webcam flow |
| [28](done/28-BACKEND-TURN-LATENCY.md) | Share speech model and unblock API event loop | 26 | 0.75-1 day | DONE | One shared `Transcriber`/`httpx.Client`, thread-safe lazy model load, serialized STT, `asyncio.to_thread` per-session work, lifespan shutdown, benchmark script, and runbook timing table complete (2026-11-10); 249 Python tests passed; laptop timings deferred to Task 27 |
| [29](done/29-SPEECH-TURN-FAST-PATH.md) | Tune turn ending and clear-intent routing | 26 | 0.75-1 day | DONE (clear-intent path) | Deterministic parser for repeat/ready/next/done/step/review/writing-check/complete ids bypasses Ollama and records `intent.fast_path`; 268 Python tests passed; parser 4.31 us/call; the 700 ms turn window is deliberately unchanged pending Task 27 laptop/webcam recordings |
| [30](done/30-SELECTED-WORK-IMAGE-ACCURACY.md) | Ground handwriting OCR in the selected answer area | 26 | 1-1.5 days | DONE (synthetic) | Fixed 12-item layout, model-located sheet corners, perspective rectification, fixed-box crop, wrong/ambiguous-area refusal, Pillow dependency, and synthetic A2/B2 crop suite complete (2026-11-11); 293 Python tests passed; real handwriting calibration and laptop webcam photos deferred to Task 27 |
| [31](31-GEMINI-VISION-FEASIBILITY.md) | Check Gemini eligibility and benchmark vision | None for research | 0.75-1.5 days | BLOCKED | Research complete: Go exposes `gemini-4-argon`; live model metadata confirms JPEG/PNG image input, 1M context, 0-day retention. Isolated Gemini adapter, config, checker/runbook notes, and fake-HTTP tests done (2026-11-11; 309 Python tests passed). Remaining: provider answer on non-coding OCR traffic, a Go API key, same-case comparison, and Task 27 laptop check before any switch |
| [32](32-LAPTOP-DASHBOARD-WEBCAM.md) | Laptop dashboard with local webcam | 21-26, 30 | 1.5-2 days | IN PROGRESS (branch `feature/task-32-laptop-dashboard`, commit `1c7ba68`) | Three-pane laptop dashboard, local webcam, laptop mic/TTS, Start/End, capture-on-request, fixed-sheet highlight, and demo-image browser smoke test complete (2026-11-12); 71 web tests and build pass; file after merge and Task 27 rehearsal |
| [33](done/33-HAIKU-INTENT.md) | Haiku intent with local fallback | 31 | 0.5-0.75 day | DONE | Hosted `claude-haiku-5-5` via the Go OpenAI route, stable session header, 10 s timeout, shared JSON validation, one-shot local qwen fallback, provider-aware `intent.interpret` logging, checker `--live` intent result, and key reuse from `VISION_API_KEY` (no second key) complete (2026-11-12); 356 Python tests passed; live check `UNCLEAR via opencode` |

**Suggested order:** Task 32 (laptop dashboard + webcam) first, then Task 27
(three five-minute laptop rehearsals). Tasks 28-31 are already implemented or
blocked; do not reopen them for the demo unless the rehearsal proves a gap.
Task 31 stays optional and does not block the existing hosted provider. Do not
close Task 27 until the final configuration passes its acceptance criteria.
The old task rows below record the previous LiveKit/phone design. Their `DONE`
labels do not mean the laptop/webcam flow is complete. The old seven-day
schedule and "only deferred-manual work remains" statement are historical and
do not apply to Tasks 20-32.

**Live run status (2026-11-12):** the laptop/webcam dashboard is Task 32. The
hosted vision is `claude-haiku-5-5` through the OpenCode Go OpenAI-compatible
route (`billing_source=go`), after the Console balance returned 402. The live
check parses all 12 fixed expressions in about 6 s; `deepseek-v4.1-flash` also
works at 16-22 s, and local `gemma4:e4b` is the no-key fallback at about 23 s.
Task 31 remains `BLOCKED` on provider confirmation for non-coding OCR traffic;
the Console balance is still empty. Python 3.10 is the live environment;
`enum.StrEnum` has a dependency-free fallback.

Current baseline (2026-11-12):

- The snapshot API, controller, contract, placement gate, intent flow, and
  handwriting crop path are implemented. There is no LiveKit worker, token
  endpoint, room client, or `infra/` stack.
- Python 3.10 is the live environment; the full suite passed at **327 tests,
  767 subtests**. The web suite passed at **40 tests**, with `tsc --noEmit` and
  `npm run build` clean.
- Hosted vision is live on `claude-haiku-5-5` via the OpenCode Go
  OpenAI-compatible route; local `gemma4:e4b` is the no-key fallback.
- The remaining demo gap is Task 32 (laptop dashboard + local webcam), then
  Task 27 (three laptop rehearsals).

## Purpose

Single tracking report for all implementation task files in this folder.

## Status Legend

- `TODO`: not started
- `IN PROGRESS`: currently being implemented
- `BLOCKED`: waiting on access, provider, or decision
- `REOPENED`: a review found acceptance criteria unmet; follow-up task assigned
- `DONE`: acceptance criteria verified

## Controller Rulings (2026-11-07)

- **Interactive one-sheet scope.** The demo uses `docs/image.png` and its 12
  items. The tutor reads the sheet, lets the student choose an exercise, guides
  them, and checks their handwriting.
- **No hint ladder.** The hint feature is removed for this demo. Guidance is
  natural and anchored to calculation-module steps.
- **Handwriting is required.** The camera must see the writing area.
  Low-confidence reads ask for clarification and never correct.
- **Hosted vision is the default.** Handwriting accuracy is the main risk on a
  6 GB GPU. Audio, STT, and intent stay local. Local vision is the fallback and
  requires staged conditions.
- **Calculation module is mandatory.** Every number the tutor speaks must come
  from it, including big-number and multi-step cases.
- **Student choice replaces worksheet order.** The tutor asks which exercise to
  start with.
- **Timeline:** about seven working days, with handwriting accuracy as the main
  schedule risk.

## Task Register

| ID | Task | Dependency | Estimate | Status | Evidence / Notes |
| --- | --- | --- | --- | --- | --- |
| 01 | Provider setup | None | 0.5 day | DONE | Repository setup, validation, provider check, `.gitignore`, README, and configuration tests complete; live provider smoke checks deferred-manual |
| 02 | LiveKit token and room | 01 | 0.25 day | DONE | `GET /get-token`, short-lived JWT, room creation, agent dispatch, failed-dispatch room cleanup, and non-secret failure test implemented; live LiveKit verification deferred-manual |
| 03 | Browser client | 02 | 0.5 day | DONE | One Start button, iPhone 16 Pro Max Safari camera/mic tracks, framing guide, reconnect handling, permission handling, screen-wake behavior, and Vite/TypeScript build setup implemented; browser/device verification deferred-manual |
| 04 | Agent media pipeline | 01, 02 | 1.5 day | REOPENED | Review 2026-11-08: pipeline is not wired to any worker; one vision failure leaves the session stuck in `RECOVER`; `tests/test_pipeline.py` fails. Covered by 11, 14 |
| 05 | Fixed lesson and responses | 04 | 0.75 day | DONE | Fixed YAML validation, choice mapping, response catalog, and resumable state machine implemented; scripted runtime validation deferred-manual |
| 06 | Calculation module and safety | 05 | 0.5 day | REOPENED | Review 2026-11-08: `check_answer` raises on mixed operations and its own error-type tests fail. Covered by 13 |
| 07 | End-to-end integration | 02-06, 10 | 1 day | REOPENED | Review 2026-11-08: no worker entrypoint and no data-channel delivery, so the flow cannot run. Covered by 11, 12, 17 |
| 08 | Testing and validation | 07 | 1 day | REOPENED | Review 2026-11-08: `pytest` is 5 failed / 19 passed; `test_lesson_flow.py` is an empty stub. Covered by 12, 13, 14, 16 |
| 09 | Demo-day runbook | 08 | 0.5 day | DONE | Five-minute iPhone 16 Pro Max script, checklist, fallback, and recovery guidance documented; rehearsals deferred-manual |
| 10 | Personality and session memory | 05 | 0.5 day | DONE | Persona prompt, SQLite sessions/turns/tool calls, compact state injection, reconnect restoration, and deletion implemented; live reconnect verification deferred-manual |

**Total critical path: about 7 working days.**

## Review Findings And Follow-Up Tasks (2026-11-08)

The done-task review found that four cards were marked DONE on
"written but not run" evidence. The current run is:

- `python -m pytest tests -q` -> 5 failed, 19 passed, 19 subtests passed.
- `npm run build` in `web/` -> succeeded.
- No provider or device checks were executed; no `.env` is present.

The blocking gaps are the missing LiveKit worker and delivery path, the state
machine's dead ends, and the red calculator and pipeline tests. The follow-up
cards below close them in this order. They are remediation work, not new demo
scope; the demo invariants in `00-DEMO-SPEC.md` are unchanged.

| ID | Task | Dependency | Estimate | Status | Closes |
| --- | --- | --- | --- | --- | --- |
| 11 | Agent worker, media wiring, and browser delivery | 12, 14, 16 | 1.5 days | DONE | `agent/main.py` worker entrypoint (lazy SDK imports), async publish helpers, start-gated snapshots, VAD/STT/segments, barge-in, check-intent frame, resume, disconnect deletion; `pytest tests/test_main.py tests/test_stt.py -q` -> 24 passed (whole suite: 112 passed) |
| 12 | Session flow recovery, continuation, and resume | none | 1 day | DONE | 20-edge table mirrors architecture §3.9; `Recover`/`Guide`/`NextExercise` paths fixed; NEXT/DONE/LIST intents and `resume()` added; `pytest tests/test_tutor.py tests/test_lesson_flow.py tests/test_llm.py -q` -> 16 passed, 4 subtests |
| 13 | Calculator error classification | none | 0.5 day | DONE | AST carry/borrow helpers, documented precedence, total `check_answer`; `pytest tests/test_calculator.py -q` -> 10 passed, 184 subtests passed |
| 14 | Pipeline decoupling and test hygiene | 12 | 0.5 day | DONE | `MediaPipeline(vision, tutor, store)`; no `tutor.memory`; hermetic config tests; response catalog suite; `pytest tests/test_pipeline.py tests/test_config.py tests/test_responses.py -q` -> 17 passed, 126 subtests (whole suite minus token server: 53 passed) |
| 15 | Vision parse use, step guidance, and number guard | 12, 14 | 0.75 day | DONE | Strict sheet validation, `verified_numbers`, step-anchored `guidance_for`, `guidance_step` wired; `pytest tests/test_responses.py tests/test_tutor.py tests/test_calculator.py -q` -> 41 passed, 336 subtests (whole suite: 76 passed) |
| 16 | Provider failure handling and session retention | 14, 19 | 0.5 day | DONE | Vision/Ollama HTTP and shape errors become domain errors with redacted messages; `STTError` added; `prune()` called once at startup; `pytest tests/test_vision.py tests/test_llm.py tests/test_memory.py -q` -> 23 passed, 11 subtests (whole suite: 88 passed) |
| 17 | Browser client cleanup and delivery contract | 11 | 0.5 day | DONE | `messages.ts` parser (null-safe), speech/interrupt/looking handling, one `start` signal, tracks stopped on failure/disconnect/unload, permission mapping, wake-lock refresh; `npm run build` succeeded |
| 18 | Dependencies, provider setup, and docs hygiene | 11, 17, 19 | 0.25 day | DONE | HTTPS dev plugin, `infra/livekit.yaml` + compose, worker command and provider docs, redacted `--live` check; `npm install` + `npm run build` succeeded, `py_compile scripts\check_providers.py` exit 0. Docker/iPhone checks deferred-manual |
| 19 | Configurable vision provider endpoint | none | 0.25 day | DONE | `VISION_BASE_URL` added, hardcoded OpenAI host removed, fence/400-retry handled; `pytest tests/test_config.py tests/test_vision.py -q` -> 13 passed. Token-suite fixture update written but environment-blocked (`aiohttp`/Python 3.14 SSL import error) |

**Follow-up effort: all nine cards are done** (11–19). Only deferred-manual
device/provider rehearsal work remains.

**Scope of these cards: code and automated tests only.** Hardware and live
providers are supplied later by the human: the iPhone 16 Pro Max, LiveKit
server, Ollama model, faster-whisper model, Silero VAD model, and the hosted
vision key. No follow-up card closes on a device or provider check; those stay
deferred-manual. Card 18 writes only placeholder values and local development
configuration, never a real key or device detail.

Recommended execution order: 13 (isolated), 19, 12, 14, 15, 16, 11, 17, 18.
Tasks 13, 19, and 12 have no dependencies and can start immediately.

## Seven-Day Sequence

### Day 1

- Task 01: Provider setup
- Task 02: LiveKit token and room

### Day 2

- Task 03: Browser client
- Task 04: Agent media pipeline begins

### Day 3

- Task 04: Agent media pipeline finishes
- Task 05: Fixed lesson and responses

### Day 4

- Task 06: Calculation module and safety
- Task 10: Personality and session memory
- Task 07: End-to-end integration begins

### Day 5

- Task 07: End-to-end integration finishes
- Task 08: Testing and validation begins

### Day 6

- Task 08: Testing and validation finishes
- Task 09: Demo-day runbook

### Day 7

- Rehearsal 1
- Fix demo-blocking issues
- Rehearsals 2 and 3
- Record the fallback video
- Freeze scope and configuration

## Definition Of Demo Ready

- The agent reads all 12 items from the sheet.
- The student chooses an exercise by voice and the correct exercise starts.
- The agent guides at least one exercise from presentation to correct answer.
- The laptop webcam sees the handwriting; low-confidence reads ask instead of
  correcting.
- Every number the tutor speaks is verified by the calculation module.
- The tutor's tone matches the personality spec.
- Session memory resumes the chosen exercise after a reconnect.
- The full interaction path works: laptop webcam -> browser turn detector ->
  faster-whisper -> Ollama -> hosted vision -> browser SpeechSynthesis.
- A fallback exists for vision, provider, or network failure.
- The full session fits inside five minutes.

## Out Of Scope For This Demo

- Hint ladder or hint command
- A second worksheet
- Worksheet generation or other worksheets
- Long-term profiles, accounts, or dashboards
- Production analytics
- Continuous video analysis
- Provider switching during the demo build
