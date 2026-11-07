# AI Math Tutor Demo

Hands-free English math tutor demo for the attached Grade 3 worksheet
(`docs/image.png`).

## Demo scope

- One worksheet with 12 fixed exercises.
- A camera at an angle sees the whole sheet and the student's handwriting.
- The student talks to the tutor by voice; there is one Start button.
- The tutor reads the 12 items, asks which one to start with, and guides the
  student step by step.
- The tutor checks the handwriting when the student says "check my answer" or
  pauses.
- There is no hint ladder in this demo.
- A deterministic calculation module verifies every number the tutor speaks.
- The tutor has a warm Grade 3 personality and per-session memory.

## Demo exercises

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

## Local provider setup

1. Copy `.env.example` to `.env`.
2. Fill in the LiveKit, Ollama, and vision provider values locally.
3. Never commit `.env` or share its contents.
4. The backend configuration loader is `agent/config.py`.

## Docs

- Demo spec: `docs/tasks/00-DEMO-SPEC.md`
- Task register: `docs/tasks/TASK-REPORT.md`
- Product and architecture context: `docs/architecture/`
