# Task 09: Demo-Day Runbook

## Goal

Prepare a repeatable, low-risk **five-minute** demonstration of the interactive
worksheet tutor.

## Specification

- Freeze the worksheet data, response catalog, Ollama model, vision model, and
  browser/system voice.
- Prepare one primary device and one backup device.
- Test camera and microphone permissions before the presentation.
- Print the worksheet clearly on white paper.
- Use a dark marker for handwriting, not a faint pencil, unless the hosted
  vision provider has proven reliable with pencil.
- Position the camera at an angle that sees the whole sheet and the writing
  area.
- Use even lighting; avoid shadows across the writing area.
- Confirm LiveKit, Ollama, faster-whisper, and the vision provider.
- Prepare a backup recording or screenshots in case a provider is unavailable.
- Prepare a one-minute spoken explanation of the architecture.
- Run at least three complete rehearsals.
- Record known limitations and recovery steps.

## Five-Minute Script

| Time | Beat | Fallback |
| --- | --- | --- |
| 0:00-0:45 | Show the sheet, press Start, camera preview appears | Show backup screenshot |
| 0:45-1:30 | Agent lists the 12 items and asks which to start | Show parsed list |
| 1:30-2:00 | Student chooses, agent presents the exercise | Choose a pre-agreed item |
| 2:00-3:15 | Agent guides step by step while the student writes | Speak the steps yourself |
| 3:15-3:45 | Student says "check my answer"; agent reads and verifies | Student says the answer aloud |
| 3:45-4:15 | Agent responds correctly; praise or a guiding question | Show transcript log |
| 4:15-5:00 | Explain the architecture in one minute | Use the architecture diagram |

## Demo-Day Checklist

- [ ] `.env` configured locally
- [ ] LiveKit, Ollama, and faster-whisper start successfully
- [ ] Vision provider responds to a test snapshot
- [ ] Browser loads over HTTPS or localhost
- [ ] Camera and microphone permissions work
- [ ] Framing guide shows the whole sheet and writing area
- [ ] Start button works
- [ ] Agent lists all 12 items
- [ ] Student choice maps to the correct exercise
- [ ] Agent guides one exercise to a correct answer
- [ ] Wrong answer produces calculator-anchored guidance
- [ ] Low-confidence handwriting produces a clarification question
- [ ] Reconnect resumes the chosen exercise
- [ ] Backup recording and screenshots ready

## Acceptance Criteria

- Three consecutive rehearsals complete without manual intervention.
- The presenter can explain the architecture in under two minutes.
- The demo can recover from a failed local service or vision provider.
- The full session fits inside five minutes.

## Dependencies

- Task 08

## Estimate

0.5 day.

## Completion Evidence (2026-11-07)

- Files: `docs/DEMO-RUNBOOK.md`, `docs/tasks/09-DEMO-DAY-RUNBOOK.md`
- Verified: documentation reviewed and `git diff --check` succeeded.
- Written but not run: rehearsal checklist and recovery procedure.
- Deferred/manual: three consecutive five-minute rehearsals and live provider
  readiness checks.
- Concerns: the iPhone 16 Pro Max and laptop must share a reachable network.
