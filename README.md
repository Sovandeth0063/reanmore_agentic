# AI Math Tutor Demo

A five-minute, English-only Grade 3 math tutor demo. A laptop webcam sees one
printed worksheet **and the child's handwriting**. The child talks to the
laptop; the tutor listens, guides, and checks answers. One Start button, no
other student-facing controls.

The laptop is the whole experience: UI, microphone, speaker, and AI. An
external 1080p webcam on a stand provides the worksheet image. There is no
iPhone and no LiveKit in the active demo.

## What it is

- One fixed worksheet (`docs/image.png`) with 12 exercises.
- Hands-free voice interaction with a warm, patient Grade 3 tutor.
- A three-pane laptop dashboard: question paper, live webcam, and review.
- The webcam sees the whole sheet and the writing area.
- The student chooses which exercise to start with by voice.
- The tutor guides step by step and checks the handwritten answer on request.
- A deterministic calculation module verifies every number the tutor speaks.
- Session memory keeps the chosen exercise, step, and attempts across a
  reconnect.

## Demo flow

1. An adult connects the external webcam on a stand, opens the laptop app at
   `https://localhost:5173`, grants camera and microphone permission, and
   frames the whole sheet and writing area.
2. The student presses **Start**; the laptop creates a session and captures
   one review image of the sheet.
3. If the sheet is missing, cut off, or unreadable, the tutor asks for a
   repositioning retry and nothing advances until placement is confirmed.
4. Once placement is confirmed, the tutor summarizes the sheet by section —
   A has addition and subtraction, B has multiplication and division. Guided
   mode (the demo `.env`) then starts at A1; choice mode asks which section and
   item to start with.
5. The student answers by voice; the tutor presents one step at a time and, in
   guided mode, auto-advances after a correct answer. Speech turns are short
   audio uploads and need no image.
6. The student writes and says **"check my answer"** (or pauses); the laptop
   captures a fresh image of the written work only.
7. The backend reads the handwriting with a confidence score, verifies it with
   the calculator, and responds. An uncertain read asks for a clearer photo
   instead of grading it.
8. The tutor continues with the exercise, offers the next one, or wraps up.
   **End** stops the camera and microphone and resets the dashboard.

## Worksheet

`docs/image.png` — one sheet, 12 fixed items.

| Item | Problem | Answer |
| --- | --- | --- |
| A1 | `4 + 5 + 6` | `15` |
| A2 | `63 + 24` | `87` |
| A3 | `85 - 33` | `52` |
| A4 | `71 - 8` | `63` |
| A5 | `63 - 5` | `58` |
| A6 | `100 - 48` | `52` |
| B1 | `6 x 4` | `24` |
| B2 | `8 x 3` | `24` |
| B3 | `9 x 3` | `27` |
| B4 | `20 / 4` | `5` |
| B5 | `80 / 10` | `8` |
| B6 | `25 / 5` | `5` |

## Hybrid teaching flow and wording

Two environment variables select the tutor's behavior. Safe defaults come
first; the demo `.env` opts into the hybrid path.

| Variable | Values | Default | Effect |
| --- | --- | --- | --- |
| `TUTOR_FLOW` | `choice`, `guided` | `choice` | `guided` starts at A1 and auto-advances through B6 after each correct answer. `choice` keeps the spoken exercise choice and every existing guard. The demo `.env` uses `guided`. |
| `TUTOR_RENDERER` | `template`, `llm` | `template` | `template` is offline and deterministic. `llm` rephrases each vetted line through the intent route, checks that only verified numbers are spoken, and falls back to the template on timeout, HTTP failure, invalid JSON, a forbidden number, or too-long text. The demo `.env` uses `template`; the hosted path is opt-in because the live route can be slow. |

Guided mode still gates on worksheet placement, and every number still comes
from the calculator. A renderer failure never breaks a turn: the template line
is spoken instead and the `tutor.render` tool row records the fallback.

## Scenario runner

`scripts/run_scenario.py` drives the 16-line scenario in
`scripts/scenarios/ip3_homework2.yaml` and writes one JSON report per run:

```bash
# Text: in-process, deterministic, checked-in worksheet fixture.
py -3.10 scripts/run_scenario.py --mode text \
  --out docs/scenarios/results/2026-11-13-ip3_homework2-text.json

# Voice: diagnostic pass against the real backend and VoxPocket TTS; start
# both services first.
py -3.10 scripts/run_scenario.py --mode voice \
  --out docs/scenarios/results/2026-11-13-ip3_homework2-voice.json

# Both: text pinned to the template renderer, then voice with the configured one.
py -3.10 scripts/run_scenario.py --mode both \
  --out docs/scenarios/results/2026-11-13-ip3_homework2-both.json
```

- Text mode uses the checked-in 12-item worksheet parse fixture, so it needs no
  camera and no vision provider. It still calls the configured intent
  classifier and stays deterministic by pinning the template renderer.
- Voice mode requires the backend on `http://127.0.0.1:8000` and the TTS
  service on `http://127.0.0.1:8001`. It checks both and fails with a clear
  message when either is down; it never starts a service. It uses the real
  vision review, STT, intent, and TTS: each student line is synthesized,
  resampled to 16 kHz PCM16, posted to `/turn`, and the stage timings are read
  from the backend's SQLite tool log, so `DB_URL` must match the backend's.
- `--mode both` reports `text_diff_count`: it compares status, capture request,
  exercise id, and milestones, not exact wording, because the LLM renderer and
  speech recognition are not reproducible.
- `--audio-dir DIR` is optional and must be outside the repository. Without it
  no audio is written, and no audio or image is ever committed.
- The runner exits non-zero when `errors` is non-empty or a required milestone
  fails: `worksheet_recognized`, `all_12_covered`, and `auto_advanced` must be
  true, and `final_answer_leaked` must be false.

The checked-in evidence lives in `docs/scenarios/results/`. The text report is
the demo's agentic and latency evidence: it drives the real controller, tool
log, calculator, and milestones over the checked-in worksheet fixture, so it is
repeatable. The voice report is a **diagnostic**, not the demo path: the
dashboard speaks with the browser voice by default, and only a
`VITE_TTS=voxpocket` build calls the VoxPocket service this mode needs. A voice
report also records the session's opening line under `greeting`, because a
browser or VoxPocket voice speaks that line too. The JSON contains tutor replies
and student lines but no audio, image bytes, prompts, or keys.

## Tech stack

| Layer | Choice |
| --- | --- |
| Transport | HTTPS session API (snapshot uploads and short speech turns) |
| Backend | Python, FastAPI |
| Speech boundaries | Browser turn detector |
| Speech-to-text | faster-whisper on CPU (int8) |
| Intent classification | Hosted Haiku via OpenCode Go; local Ollama fallback (clear commands are deterministic) |
| Vision | Hosted model by default; local fallback |
| Arithmetic | Deterministic Python calculator (no LLM math) |
| Text-to-speech | Browser `SpeechSynthesis` (demo default); optional local VoxPocket TTS service via `VITE_TTS=voxpocket` |
| Memory | SQLite, per session |
| Capture | Laptop webcam preview, one still image per request |
| Dashboard | Three-pane browser console on the laptop |

## Hard rules

These are not preferences. They define the demo.

- One sheet, 12 fixed items. No generated exercises, no second paper.
- **No hint ladder** and no hint command.
- Every number the tutor speaks comes from the calculator's verified output for
  the current turn.
- A low-confidence handwriting read **asks for clarification**; it never
  corrects.
- Hosted vision is the default. Audio capture and browser turn detection stay
  local, as does the speech-to-text. Clear intent commands are deterministic;
  only the ambiguous remainder calls the hosted intent classifier, with the
  local model as its fallback.
- In choice mode the student chooses the exercise by voice; guided mode (the
  demo `.env`) starts at A1 and auto-advances. There is one Start button.
- The laptop is the UI, microphone, speaker, and AI host. An external webcam
  provides the image; there is no iPhone or room transport.
- Snapshots are event-driven only: review, "Ready" retry, or a written-work
  check. No continuous video analysis and no published media track.
- Session memory only. No profiles, accounts, or cross-session tracking. No raw
  audio or video is stored.

## Repository status (as of 2026-11-13)

Tasks 20-26 moved the demo to the HTTPS snapshot API. Task 32 moves the UI and
voice to the laptop with a local webcam; Task 34 adds the optional isolated
VoxPocket TTS service and CPU speech-to-text; Task 35 hardens the numeric vision
confidence. The demo tutor voice is the browser's `SpeechSynthesis`; VoxPocket
is an opt-in diagnostic path. Live TTS/STT and fake-camera validation passed on
2026-11-13; the real external-webcam rehearsal (Task 27) remains.

| Area | State |
| --- | --- |
| Demo spec, task cards, task register | Written and current |
| Architecture docs (`docs/architecture/`) | Updated to the laptop/webcam snapshot path; old rooms are history |
| `README.md`, `.env.example` | Updated to the laptop/webcam path; the tutor voice is browser `SpeechSynthesis` by default |
| `agent/config.py` | Implemented; validates hosted/local vision, optional hosted intent, and CPU STT device/compute type |
| Hybrid tutor (`TUTOR_FLOW`, `TUTOR_RENDERER`) | Guided flow, verified-number renderer with template fallback, and the text/voice scenario runner are implemented on `feature/hybrid-adaptive-tutor` |
| `agent/calculator.py`, `lesson.py`, `responses.py`, `tutor.py` | Core implementations: calculator, fixed lesson, response catalog, placement gate, and state machine |
| `agent/controller.py` | Provider-neutral session controller for the HTTP contract |
| `agent/vision.py`, `llm.py`, `stt.py`, `memory.py` | Implemented with structured boundaries and SQLite session state |
| `server/session_api.py`, `server/contract.py` | Session, speech-turn, snapshot, and end routes implemented |
| `scripts/voxpocket_tts_server.py` | Optional VoxPocket TTS service; `voxcpm` is imported lazily |
| `scripts/run_scenario.py` | Text/voice scenario runner with JSON evidence; text is the repeatable agentic evidence, voice is a live diagnostic |
| `web/index.html`, `web/src/*` | Laptop dashboard, local webcam, browser speech by default with opt-in VoxPocket speech |
| `tests/*` | Configuration, contract, session API, controller, calculator, lesson, memory, tutor, STT, vision, LLM, and TTS-server tests written; provider, TTS, and webcam validation remain |

## Task plan

Cards 01–26: the original ten-task plan below, plus remediation cards 11–19
recorded in the same register, plus the snapshot migration cards 20–26.
Task 32 is the laptop dashboard/webcam enhancement, Task 33 is hosted intent,
Task 34 adds VoxPocket TTS plus CPU speech-to-text, and Task 35 fixes numeric
vision confidence; Task 27 rehearses them. Finished cards are filed under
`docs/tasks/done/` and the register is `docs/tasks/TASK-REPORT.md`. Follow-up
cards are 27–35.

The table below records the original plan; the register has the current status.

| ID | Task | Estimate |
| --- | --- | --- |
| 01 | Provider setup | 0.5 day |
| 02 | LiveKit token and room | 0.25 day |
| 03 | Browser client | 0.5 day |
| 04 | Agent media pipeline | 1.5 days |
| 05 | Fixed lesson and responses | 0.75 day |
| 06 | Calculation module and safety | 0.5 day |
| 07 | End-to-end integration | 1 day |
| 08 | Testing and validation | 1 day |
| 09 | Demo-day runbook | 0.5 day |
| 10 | Personality and session memory | 0.5 day |

## Project skills

Project-local OpenCode skills live in `.agent/` and are registered by
`opencode.json`:

| Skill | Use when |
| --- | --- |
| `implement-task-card` | implementing or resuming a card under `docs/tasks/` |
| `demo-invariants` | changing anything that affects what the tutor says or which exercises exist |
| `verify-providers` | checking the session API, Ollama, faster-whisper, or vision readiness |
| `file-task-card` | closing a finished card into `docs/tasks/done/` |

## Local provider setup

1. Copy `.env.example` to `.env`.
2. Fill in `OLLAMA_MODEL` and, for hosted vision, `VISION_MODEL` and
   `VISION_API_KEY`. `VISION_BASE_URL` is the OpenAI-compatible base URL before
   `/chat/completions`.
3. Never commit `.env` or share its contents.
4. The backend configuration loader is `agent/config.py`.
5. Run `py -3.10 scripts/check_providers.py` and resolve every failed check.
   Add `--live` to send `docs/image.png` to the configured vision provider once
   the key works; it prints the item count or a redacted provider error. The
   live demo environment on this laptop is Python 3.10; use `py -3.10` for the
   backend and provider scripts.

Start the two demo services from the repository root:

```bash
# 1. Backend session API (CPU speech-to-text)
py -3.10 -m uvicorn server.session_api:app --host 127.0.0.1 --port 8000

# 2. Browser client
cd web && npm install && npm run dev
```

The Vite dev server runs over **HTTPS** with a self-signed development
certificate (`@vitejs/plugin-basic-ssl`). Open `https://localhost:5173` on the
laptop, accept the certificate warning once, then grant webcam and microphone
permission on Start. The dev server proxies `/sessions` to
`http://127.0.0.1:8000` and `/tts` to `http://127.0.0.1:8001`; no phone or LAN
address is needed. Use an external 1080p webcam on a stand for the demo sheet.

### Optional VoxPocket voice

The tutor voice is the browser's `SpeechSynthesis` by default, so no third
service is required. The VoxPocket voice is opt-in: copy `web/.env.example` to
`web/.env`, set `VITE_TTS=voxpocket`, start the voice service, and restart the
dev server.

```bash
# Optional third service
C:\Users\ASUS\voxcpm-tts\Scripts\python.exe scripts\voxpocket_tts_server.py --host 127.0.0.1 --port 8001
```

Any other `VITE_TTS` value, or none at all, selects the browser voice. The
VoxPocket model is **not** installed in the backend environment and its torch
CUDA stack is not in `requirements.txt`. The service loads
`muyleanging/VoxPocket-TTS-Khmer` from `%USERPROFILE%\voxcpm-hf`
(`C:\Users\ASUS\voxcpm-hf` on this laptop) and serves 44.1 kHz PCM16 WAV. Set
`VOXPOCKET_CACHE_DIR` to move the cache, or `VOXPOCKET_ALLOW_DOWNLOAD=1` to
permit a hub download. In `voxpocket` mode a failed request or playback falls
back to browser `SpeechSynthesis`, so a missing voice never blocks the session.

Speech-to-text runs on the CPU by default (`WHISPER_DEVICE=cpu`,
`WHISPER_COMPUTE_TYPE=int8`) because faster-whisper's CUDA path fails on this
laptop without `cublas64_12.dll`; the GPU is reserved for VoxPocket. Change the
two values only if the CUDA runtime is repaired. There is no automatic GPU
retry.

Environment variables:

```text
OLLAMA_BASE_URL
OLLAMA_MODEL
WHISPER_MODEL
WHISPER_DEVICE         # cpu (demo) or cuda
WHISPER_COMPUTE_TYPE   # int8 (demo), float16, float32, ...
VISION_PROVIDER        # hosted (default) or local
VISION_BASE_URL        # hosted only; base URL before /chat/completions
VISION_MODEL
VISION_API_KEY         # hosted only; also used by intent
INTENT_PROVIDER        # opencode (demo) or ollama
INTENT_MODEL           # opencode only, e.g. claude-haiku-5-5
INTENT_BASE_URL        # opencode only; base URL before /chat/completions
TUTOR_FLOW             # choice (default) or guided (demo)
TUTOR_RENDERER         # template (default/demo) or llm (opt-in)
VITE_TTS               # web only: browser (default) or voxpocket
LOG_LEVEL
DB_URL
```

The TTS service reads only `VOXPOCKET_CACHE_DIR` (default
`%USERPROFILE%\voxcpm-hf`) and `VOXPOCKET_ALLOW_DOWNLOAD`; it needs no API key
and is only used by the opt-in `VITE_TTS=voxpocket` build.

## Repository layout

```text
agent/                 Python tutor agent
  config.py            provider settings and secret handling
  calculator.py        safe evaluator, answer checker, step model
  lesson.py            12 fixed exercises
  lessons/             versioned worksheet YAML
  responses.py         fixed response catalog
  controller.py        provider-neutral session controller
  vision.py            worksheet and handwriting reads
  llm.py               hosted/local intent classification
  stt.py               faster-whisper transcription
  tutor.py             placement gate and state machine
  memory.py            per-session SQLite state
  prompts/tutor.md     persona
server/session_api.py  session, speech-turn, snapshot, and end routes
server/contract.py     shared request and response contract
scripts/               provider checks, turn benchmark, optional VoxPocket TTS service
  voxpocket_tts_server.py  optional VoxPocket voice service on port 8001
  run_scenario.py      text/voice scenario runner and JSON evidence
  scenarios/           scenario YAML and checked-in worksheet parse fixture
web/                   laptop dashboard and browser client
  src/dashboard.ts     three-pane layout and review state (Task 32)
  src/camera.ts        webcam preview and still capture
  src/browserSpeech.ts browser voice with en-US and a 20 s watchdog
  src/speech.ts        VoxPocket speech with browser fallback (opt-in)
  src/speechMode.ts    VITE_TTS mode selection; browser is the default
  public/worksheet.png fixed question paper for the dashboard
tests/                 unit and integration tests
docs/                  spec, task cards, runbook, architecture
  scenarios/results/   checked-in text/voice scenario JSON evidence
.agent/                project-local OpenCode skills
```

## Main risks

1. **Handwriting accuracy** — the top risk. Hence hosted vision by default and
   low-confidence clarification.
2. **Webcam framing and resolution** — an external 1080p camera on a stand must
   keep the whole sheet and the answer space readable. A built-in laptop camera
   at an angle is the fallback, not the target.
3. **Audio feedback** — the laptop speaker can enter the microphone; use echo
   cancellation, headphones, or speaker placement.
4. **Latency** — full-sheet vision takes several seconds; show a clear checking
   state. The old 2.5-second target is not a guarantee.
5. **Provider setup** — Ollama, faster-whisper, and vision keys are manual and
   currently unverified.

## Docs

- Demo spec: `docs/tasks/00-DEMO-SPEC.md`
- Task register: `docs/tasks/TASK-REPORT.md`
- Task cards: `docs/tasks/` (migration cards 20–32; finished cards in
  `docs/tasks/done/`)
- Five-minute runbook: `docs/DEMO-RUNBOOK.md`
- End-to-end pipeline and measured latency:
  `docs/architecture/04-End-to-End-Pipeline.md`
- Laptop dashboard design:
  `docs/superpowers/specs/2026-11-12-laptop-dashboard-webcam-design.md`
- Product and architecture context: `docs/architecture/`
