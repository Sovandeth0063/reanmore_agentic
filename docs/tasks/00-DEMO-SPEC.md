# Demo Implementation Specification

## Purpose

Build an English-only Grade 3 worksheet tutor demo for a **five-minute
demonstration**. The tutor sees the whole worksheet and the child's handwriting
through a camera, talks with the child by voice, lets the child choose an
exercise, guides them like a human tutor, and checks answers with a
deterministic calculator.

## Source Worksheet

`docs/image.png` — one sheet, 12 items:

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

## Fixed Scope

- One worksheet (the image above), 12 fixed exercises. No generation and no
  second paper.
- Camera is placed at an angle that sees the whole sheet and the student's
  handwriting.
- Student communicates by voice; one Start button, no other student-facing
  buttons.
- Student chooses which exercise to start with by voice.
- No hint ladder and no hint command. The tutor guides naturally, step by step,
  like a human sitting beside the child.
- Answer checking happens when the student says "check my answer" or asks to
  check, and after a pause in writing.
- Snapshots are event-driven: one at Start to read the exercise list, and one
  per check or pause to read the handwriting. No continuous video analysis.
- Silero VAD detects speech boundaries.
- faster-whisper performs local speech-to-text.
- Local Ollama handles intent classification and guidance wording.
- A hosted vision model reads the worksheet and handwriting by default.
- A deterministic calculation module verifies every number and decomposes the
  exercise into teachable steps.
- Browser `SpeechSynthesis` speaks the tutor's responses.
- The tutor has a fixed, warm Grade 3 personality.
- Session memory persists the chosen exercise, current step, attempts, last
  answer, and recent turns in SQLite.
- Target response latency is under about 2.5 seconds per turn.

## Controller Rulings (2026-11-07)

- **Interactive scope, not one-exercise scope.** The demo is the full worksheet
  flow described above. The earlier single-exercise plan is superseded.
- **No hint ladder.** The hint feature is removed from this demo. Guidance is
  natural and anchored to calculator steps.
- **Handwriting is required.** The camera must see the student's writing.
  Low-confidence reads ask for clarification and never produce a correction.
- **Hosted vision is the default.** Handwriting accuracy is the main demo risk;
  a hosted vision model is materially better than a 3B local model on a 6 GB
  GPU. Audio, STT, and intent stay local. If hosted vision is rejected, the
  local fallback requires staged conditions: dark marker, large writing, good
  light, camera close to the paper.
- **One sheet only.** The two-paper / 10-15 exercise scope is deferred.
- **Student choice replaces worksheet order.** The tutor asks which exercise to
  start with instead of walking the sheet top to bottom.

## Demo Flow

1. An adult positions the camera so the whole sheet and the writing area are
   visible.
2. The student presses Start.
3. The browser joins LiveKit and publishes microphone and camera tracks.
4. The agent samples one frame, parses the 12 printed items, validates them
   with the calculator, and briefly confirms what it sees.
5. The agent asks which exercise the student would like to start with.
6. The student chooses by voice; the agent maps the choice to an exercise id.
7. The agent presents the chosen exercise and guides the student step by step,
   watching what they write.
8. The student says "check my answer" or pauses.
9. The agent samples a frame, reads the handwriting and the spoken answer,
   verifies with the calculator, and responds.
10. The agent continues with the same exercise, offers the next step, or asks
    which exercise to do next.
11. The agent praises effort and wraps up by voice.

## Five-Minute Demo Script

| Time | Beat | Fallback |
| --- | --- | --- |
| 0:00-0:45 | Show the sheet, press Start, camera preview appears | Show backup screenshot |
| 0:45-1:30 | Agent lists the 12 items and asks which to start | Show parsed list |
| 1:30-2:00 | Student chooses, agent presents the exercise | Choose a pre-agreed item |
| 2:00-3:15 | Agent guides step by step while the student writes | Speak the steps yourself |
| 3:15-3:45 | Student says "check my answer"; agent reads and verifies | Student says the answer aloud |
| 3:45-4:15 | Agent responds correctly; praise or a guiding question | Show transcript log |
| 4:15-5:00 | Explain the architecture in one minute | Use the architecture diagram |

## Non-Goals

- Hint ladder or hint command
- A second worksheet
- Dynamic exercise generation
- Accounts, dashboards, or progress tracking over time
- Multiple languages or subjects
- RAG or curriculum ingestion
- Offline mode
- Continuous video analysis
- OCR of other worksheets
- Production-grade scaling

## Definition Of Done

The demo is ready when an adult can start a session, the agent reads the 12
items from the sheet, the student chooses one by voice, the agent guides the
student through it while seeing their handwriting, the calculator verifies the
answer, the tutor responds correctly, and the full flow completes three times
in a row inside five minutes on the demo device.
