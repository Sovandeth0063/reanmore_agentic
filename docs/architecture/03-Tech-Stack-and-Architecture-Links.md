# Snapshot Worksheet Tutor: Stack and Demo Overview

This is the short overview of the [architecture](02-Architecture-ai-math-tutor.md)
for the five-minute demo. The snapshot upload and turn API are implemented;
the remaining UI work is the laptop dashboard with a local webcam (Task 32).
There is no iPhone or LiveKit in the active design.

## What the audience sees

1. The student asks the tutor to review the one printed worksheet.
2. A still image checks whether the sheet is in camera range. If not, the tutor
   asks the student to move it and takes another photo when they say "Ready."
3. The tutor says the sheet mixes addition, subtraction, multiplication, and
   division, then asks which exercise to start with.
4. The student chooses a section and item, such as "A2." The tutor explains
   that problem and answers spoken questions without taking more photos.
5. When asked to check the student's writing, the tutor takes a fresh photo,
   reads the selected answer, verifies it with the calculator, and responds.

The webcam preview remains local to the laptop. Only requested still images are
sent for vision. Speech is sent as short turns from the laptop microphone.
There is no continuous AI video interpretation and no need to complete all 12
items on stage.

## Stack

| Layer | Target choice | Role |
| --- | --- | --- |
| Laptop UI | Browser dashboard on the laptop | Three panes, Start/End, webcam preview, framing guide, still capture, spoken output |
| Camera | External 1080p webcam on a stand | Local preview and still images; no phone and no room transport |
| Transport | HTTPS requests | Send one speech turn or still image per event; return response text |
| Speech input | Laptop microphone + local faster-whisper | Turn-based transcription; no published microphone track |
| Intent | Local Ollama model with structured output | Map speech to review, choice, question, check, repeat, next, or done |
| Vision | Hosted vision/OCR model | Check sheet visibility, confirm printed items, read selected handwriting |
| Tutor | Python state machine and response catalog | Own exercise choice, placement recovery, pacing, and feedback |
| Lesson | Fixed YAML for A1-A6 and B1-B6 | Known expressions and guided steps for `docs/image.png` |
| Arithmetic | Deterministic Python calculator | Verify answers and any spoken arithmetic result |
| Speech output | Browser SpeechSynthesis | Speak the returned tutor text on the laptop |
| Session data | SQLite | Keep selected item, step, attempts, and recent turns during the session |

## Review decisions

- A missing or unreadable sheet leads to a placement prompt, never a guessed
  summary.
- OCR confirms the fixed worksheet and reads handwriting. The lesson file
  supplies the problem and answer.
- "Number two" is ambiguous across A and B; ask which section.
- Conversation alone does not trigger a photo. "Check my writing" does.
- An uncertain handwritten read leads to a question, never a wrong mark.
- The five-minute script shows one complete exercise. The full sheet remains
  available for student choice.

## Current code versus remaining work

The snapshot API, controller, lesson, calculator, vision, response, and session
modules are implemented. The remaining work is the laptop dashboard and local
webcam UI (Task 32), then the five-minute rehearsal (Task 27). No LiveKit
worker, token endpoint, room client, Docker stack, or iPhone page is part of the
active demo. See the [current implementation note](02-Architecture-ai-math-tutor.md#current-implementation-2026-11-12).

## Related documents

- [Product requirements](01-PRD-ai-math-tutor.md)
- [Detailed architecture](02-Architecture-ai-math-tutor.md)
- [Laptop UI brief](ui-brief-snapshot-review.md)
- [Webcam dashboard design](../superpowers/specs/2026-11-12-laptop-dashboard-webcam-design.md)
- [Current demo runbook](../DEMO-RUNBOOK.md)

## Reference documentation

- [Media capture in browsers](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia)
- [Canvas still-image capture](https://developer.mozilla.org/en-US/docs/Web/API/HTMLCanvasElement/toBlob)
- [Browser audio recording](https://developer.mozilla.org/en-US/docs/Web/API/MediaRecorder)
- [Browser speech synthesis](https://developer.mozilla.org/en-US/docs/Web/API/SpeechSynthesis)
- [FastAPI](https://fastapi.tiangolo.com/)
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
