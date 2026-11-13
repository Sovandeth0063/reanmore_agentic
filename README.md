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
   A has addition and subtraction, B has multiplication and division — and
   asks which section and item to start with.
5. The student chooses by voice; the tutor presents the exercise and guides
   step by step. Speech turns are short audio uploads and need no image.
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
| Text-to-speech | Local VoxPocket TTS service; browser `SpeechSynthesis` fallback |
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
- The student chooses the exercise by voice; there is one Start button.
- The laptop is the UI, microphone, speaker, and AI host. An external webcam
  provides the image; there is no iPhone or room transport.
- Snapshots are event-driven only: review, "Ready" retry, or a written-work
  check. No continuous video analysis and no published media track.
- Session memory only. No profiles, accounts, or cross-session tracking. No raw
  audio or video is stored.

## Repository status (as of 2026-11-13)

Tasks 20-26 moved the demo to the HTTPS snapshot API. Task 32 moves the UI and
voice to the laptop with a local webcam; Task 34 adds the isolated VoxPocket
TTS service and CPU speech-to-text; Task 35 hardens the numeric vision
confidence. Live TTS/STT and fake-camera validation passed on 2026-11-13; the
real external-webcam rehearsal (Task 27) remains.

| Area | State |
| --- | --- |
| Demo spec, task cards, task register | Written and current |
| Architecture docs (`docs/architecture/`) | Updated to the laptop/webcam snapshot path; old rooms are history |
| `README.md`, `.env.example` | Updated to the laptop/webcam and VoxPocket TTS path |
| `agent/config.py` | Implemented; validates hosted/local vision, optional hosted intent, and CPU STT device/compute type |
| `agent/calculator.py`, `lesson.py`, `responses.py`, `tutor.py` | Core implementations: calculator, fixed lesson, response catalog, placement gate, and state machine |
| `agent/controller.py` | Provider-neutral session controller for the HTTP contract |
| `agent/vision.py`, `llm.py`, `stt.py`, `memory.py` | Implemented with structured boundaries and SQLite session state |
| `server/session_api.py`, `server/contract.py` | Session, speech-turn, snapshot, and end routes implemented |
| `scripts/voxpocket_tts_server.py` | Separate VoxPocket TTS service; `voxcpm` is imported lazily |
| `web/index.html`, `web/src/*` | Laptop dashboard, local webcam, VoxPocket speech with browser fallback |
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

Start the three services from the repository root:

```bash
# 1. Backend session API (CPU speech-to-text)
py -3.10 -m uvicorn server.session_api:app --host 127.0.0.1 --port 8000

# 2. VoxPocket TTS, using the isolated environment that has the model stack
C:\Users\ASUS\voxcpm-tts\Scripts\python.exe scripts\voxpocket_tts_server.py --host 127.0.0.1 --port 8001

# 3. Browser client
cd web && npm install && npm run dev
```

The Vite dev server runs over **HTTPS** with a self-signed development
certificate (`@vitejs/plugin-basic-ssl`). Open `https://localhost:5173` on the
laptop, accept the certificate warning once, then grant webcam and microphone
permission on Start. The dev server proxies `/sessions` to
`http://127.0.0.1:8000` and `/tts` to `http://127.0.0.1:8001`; no phone or LAN
address is needed. Use an external 1080p webcam on a stand for the demo sheet.

The VoxPocket model is **not** installed in the backend environment and its
torch CUDA stack is not in `requirements.txt`. The service loads
`muyleanging/VoxPocket-TTS-Khmer` from `%USERPROFILE%\voxcpm-hf`
(`C:\Users\ASUS\voxcpm-hf` on this laptop) and serves 44.1 kHz PCM16 WAV. Set
`VOXPOCKET_CACHE_DIR` to move the cache, or `VOXPOCKET_ALLOW_DOWNLOAD=1` to
permit a hub download. If the service is down, the dashboard falls back to
browser `SpeechSynthesis`, so a missing voice never blocks the session.

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
LOG_LEVEL
DB_URL
```

The TTS service reads only `VOXPOCKET_CACHE_DIR` (default
`%USERPROFILE%\voxcpm-hf`) and `VOXPOCKET_ALLOW_DOWNLOAD`; it needs no API key.

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
scripts/               provider checks, turn benchmark, VoxPocket TTS service
  voxpocket_tts_server.py  separate VoxPocket voice service on port 8001
web/                   laptop dashboard and browser client
  src/dashboard.ts     three-pane layout and review state (Task 32)
  src/camera.ts        webcam preview and still capture
  src/speech.ts        VoxPocket speech with browser fallback
  public/worksheet.png fixed question paper for the dashboard
tests/                 unit and integration tests
docs/                  spec, task cards, runbook, architecture
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
