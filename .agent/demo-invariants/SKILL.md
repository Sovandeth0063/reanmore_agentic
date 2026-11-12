---
name: Demo Invariants
description: Use when implementing, reviewing, or testing any part of the Grade 3 math tutor demo — agent pipeline, browser client, lesson data, prompts, vision, calculator, or session memory. Use when a change could affect what the tutor says, which exercises exist, or what the student sees.
---

# Demo Invariants

## Core principle

This demo is a fixed, five-minute, one-worksheet experience. Determinism beats
flexibility: the calculation module owns arithmetic, the response catalog owns
fixed speech, and the vision model's uncertainty is handled by asking, not
guessing.

## Source of truth

- Demo spec and rulings: `docs/tasks/00-DEMO-SPEC.md`
- Worksheet: `docs/image.png` (12 items)
- Task register: `docs/tasks/TASK-REPORT.md`

When this skill and the spec disagree, the spec wins.

## The 12 fixed exercises

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

## The invariants

1. **One sheet, 12 fixed items.** No generated exercises, no second paper, no
   practice problems. Reject exercise IDs outside A1–A6 and B1–B6.
2. **No hint ladder and no hint command.** Guidance is natural, one step at a
   time, anchored to calculator steps.
3. **The calculator owns every spoken number.** The model may phrase guidance;
   it must never compute or state an arithmetic result that is not in the
   calculator's verified output for the current turn.
4. **Low confidence clarifies, never corrects.** A misread handwritten answer
   is not a wrong answer. Ask the student to say it or write it again.
5. **Hosted vision is the default.** Audio capture, browser turn detection,
   speech-to-text, and intent stay local. Local vision is the fallback and needs
   staged conditions.
6. **Student choice by voice.** One Start button; no other student-facing
   buttons. The student picks the exercise; worksheet order is not used.
7. **Event-driven snapshots only.** One at Start, one per "check my answer" or
   writing pause. No continuous video analysis.
8. **Session memory is per session.** No profiles, accounts, or cross-session
   progress. Never store raw audio or video. Delete the session row at the end
   or after a short retention window.
9. **Persona is warm Grade 3.** Short sentences, one step at a time, praise
   effort, never shame or rush.

## Checklist for any change

- [ ] Does it add an exercise that is not on the sheet? Stop.
- [ ] Does it add a hint level, hint command, or "just tell me" shortcut? Stop.
- [ ] Can the LLM produce or alter a number? Stop.
- [ ] Can a low-confidence read produce a correction? Stop.
- [ ] Does it add a student-facing button or control? Stop.
- [ ] Does it store audio, video, or a long-term profile? Stop.
- [ ] Does a test call a paid vision provider or start a service? Stop.
- [ ] Does the tutor still speak only calculator-verified numbers? Confirm.

## Where the invariants live

| Concern | File | Task |
| --- | --- | --- |
| Provider settings and secrets | `agent/config.py` | 20 |
| Session API and snapshot endpoints | `server/session_api.py`, `agent/controller.py` | 21 |
| Browser client, framing guide | `web/src/` | 22 |
| Worksheet and handwriting reads | `agent/controller.py`, `agent/vision.py` | 23 |
| 12 exercises, response catalog | `agent/lessons/grade3_demo.yaml`, `agent/lesson.py`, `agent/responses.py` | 05 |
| Safe evaluator, checker, steps | `agent/calculator.py` | 06 |
| Persona | `agent/prompts/tutor.md` | 10 |
| Session memory | `agent/memory.py`, SQLite | 10 |

The task register is the source of truth for what is implemented. Check
`docs/tasks/TASK-REPORT.md` before assuming behavior exists.

## Red flags

| Thought | Reality |
| --- | --- |
| "One extra practice problem would be nice." | The demo is fixed. A new item breaks the parse, choice, and answer contracts. |
| "The model can add 4 + 5 itself." | Unverified numbers are the exact failure this project exists to prevent. |
| "Low confidence, but it looks like 15." | Looks-like is not verified. Ask. |
| "A hint button would help the demo." | The hint ladder is out of scope. Voice guidance only. |
| "Continuous frames would feel smoother." | Event-driven snapshots are a latency and cost decision. |
| "I'll cache the student's progress for next time." | Cross-session tracking is a non-goal. |
| "The answer is obviously 52, I'll just say it." | Only the calculator may supply it. |
