# Task 10: Personality And Session Memory

## Goal

Give the tutor a consistent, warm Grade 3 personality and per-session memory so
it behaves like a human tutor across turns.

## Specification

### Personality

- Keep the persona in `agent/prompts/tutor.md`.
- Warm, patient, upbeat; short sentences; simple Grade 3 English.
- One step at a time; wait after asking a question.
- Praise effort and specific progress, not only correct answers.
- Ask before assuming when a read is unclear.
- Never shame, rush, or use sarcasm.
- Stay on math; redirect off-topic talk kindly.
- Ask no personal questions.
- The persona prompt controls tone and phrasing. The calculation module
  controls every number the tutor speaks.

### Session memory

- Store per session: session id, chosen exercise, current step, attempts, last
  answer, last vision confidence, last 4-6 turns, created and updated
  timestamps.
- Persist in SQLite tables `sessions`, `turns`, and `tool_calls`.
- Inject a compact state block into each Ollama call.
- Do not rely on the model's context window for state.
- Resume the chosen exercise and step after a reconnect.
- Do not store raw audio or video.
- Delete the session row at session end, or after a fixed short retention
  window.

### Boundary

- No long-term profiles, accounts, or progress tracking across sessions. Those
  remain PRD non-goals.

## Acceptance Criteria

- The tutor's tone matches the persona in scripted tests.
- The state block contains the chosen exercise, current step, attempts, and last
  answer.
- A reconnect resumes the same exercise and step.
- The tutor never asks for personal information.
- No raw media is stored.
- Session rows can be deleted.

## Dependencies

- Task 05

## Estimate

0.5 day.

## Completion Evidence (2026-11-07)

- Files: `agent/prompts/tutor.md`, `agent/memory.py`, `agent/tutor.py`,
  `tests/test_memory.py`, `tests/test_tutor.py`
- Verified: `python -m py_compile` across all Python modules and tests →
  succeeded.
- Written but not run: memory persistence, deletion, state-block, and reconnect
  tests.
- Deferred/manual: live reconnect behavior through the deployed room.
- Concerns: retention cleanup is session-end deletion; scheduled retention is
  outside the demo scope.
