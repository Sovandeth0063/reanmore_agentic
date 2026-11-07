# Demo Task Report

## Purpose

Single tracking report for all implementation task files in this folder.

## Status Legend

- `TODO`: not started
- `IN PROGRESS`: currently being implemented
- `BLOCKED`: waiting on access, provider, or decision
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
| 01 | Provider setup | None | 0.5 day | IN PROGRESS | Config loader, `.gitignore`, README, and unit test complete; local services and vision provider still need setup |
| 02 | LiveKit token and room | 01 | 0.25 day | TODO | `GET /get-token`, JWT, dispatch |
| 03 | Browser client | 02 | 0.5 day | TODO | One Start button, mic/camera tracks, framing guide |
| 04 | Agent media pipeline | 01, 02 | 1.5 day | TODO | Silero, faster-whisper, worksheet parse, handwriting snapshot |
| 05 | Fixed lesson and responses | 04 | 0.75 day | TODO | 12 exercises, student choice, no hints |
| 06 | Calculation module and safety | 05 | 0.5 day | TODO | Safe evaluator, error types, step model, number guard |
| 07 | End-to-end integration | 02-06, 10 | 1 day | TODO | Parse, choose, guide, check, resume |
| 08 | Testing and validation | 07 | 1 day | TODO | Automated, vision, manual, performance |
| 09 | Demo-day runbook | 08 | 0.5 day | TODO | Staging, five-minute script, fallback plan |
| 10 | Personality and session memory | 05 | 0.5 day | TODO | Persona prompt, state block, SQLite persistence |

**Total critical path: about 7 working days.**

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
- The camera sees the handwriting; low-confidence reads ask instead of
  correcting.
- Every number the tutor speaks is verified by the calculation module.
- The tutor's tone matches the personality spec.
- Session memory resumes the chosen exercise after a reconnect.
- The full interaction path works: LiveKit -> Silero VAD -> faster-whisper ->
  Ollama -> hosted vision -> browser SpeechSynthesis.
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
