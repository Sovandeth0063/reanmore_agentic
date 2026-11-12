---
name: Implement Task Card
description: Use when asked to implement a task card under docs/tasks/ in this project, or to continue a partially implemented card. Covers reading the card and spec first, staying inside the named files, writing every specified test without running it, and reporting what was and was not verified.
---

# Implement A Task Card

## Core principle

The card is the contract. The demo spec and any `## Controller rulings` section
override the card body. The report must separate what was written from what was
actually verified.

## Before touching code

1. Read `docs/tasks/<NN>-<NAME>.md` in full.
2. Read `docs/tasks/00-DEMO-SPEC.md` for global constraints.
3. If the card has a `## Controller rulings` section, it wins over the body.
4. Check `docs/tasks/TASK-REPORT.md` for status and dependencies.
5. Read the existing files the card names, plus the tests that cover them.
6. Load the `demo-invariants` skill if the change affects what the tutor says,
   which exercises exist, or what the student sees.

If the card is ambiguous, decide and record the decision in your report. Do not
silently widen scope.

## While implementing

- Change only the files the card names, plus the tests it names.
- No drive-by refactors, renames, formatting passes, or dependency swaps.
- Preserve unrelated uncommitted work. Never revert someone else's changes.
- Keep secrets in `agent/config.py` and `.env`; never in `web/`, logs, or
  committed files.
- Prefer the existing module boundaries:

```text
agent/config.py       provider settings
agent/calculator.py   safe evaluator, checker, step model
agent/lesson.py       12 fixed exercises
agent/responses.py    fixed response catalog
agent/controller.py   session controller for the snapshot API
agent/tutor.py        state machine and intent handling
agent/memory.py       per-session SQLite state
server/session_api.py session, speech-turn, and snapshot routes
web/src/              browser client
```

## Tests

- Write every test file and case the card names, covering each acceptance
  criterion.
- Do not run pytest, unittest, or any other test runner.
- Do not start Docker, LiveKit, Ollama, or download models.
- `python -m py_compile <file>` is the only permitted execution.
- Tests are part of the deliverable. A test that is never written can never be
  run later.

## Git

- Do not commit, stage, stash, checkout, reset, or clean unless the human
  partner asks for it in that session.
- Do not create branches or worktrees for a card in this project.

## Report

Return, in this order:

1. Status: implemented, partial, or blocked.
2. Files changed.
3. Compile summary: the exact command and its result.
4. Acceptance criteria: met, written-but-unverified, or deferred-manual.
5. Concerns and decisions you had to make.

Never write "tests pass" for a test you did not run.

## Red flags

| Thought | Reality |
| --- | --- |
| "I'll run pytest once to be sure." | Forbidden. Write the test; the manager runs it. |
| "This helper is cleaner." | Out of scope. The card's file list is binding. |
| "I'll commit so nothing is lost." | Forbidden. Leave the working tree alone. |
| "The card says 12 items, but 13 is better." | The spec is fixed. |
| "The provider check probably works." | Mark it deferred-manual, not done. |
| "The card is vague, so I'll design the whole feature." | Decide narrowly, record the ruling, stay in scope. |
| "I'll delete the failing old test." | Never weaken a test to get green. Report the conflict. |

## Card map

| Card | Main files |
| --- | --- |
| 01 Provider setup | `agent/config.py`, `requirements.txt`, `scripts/check_providers.py`, `tests/test_config.py` |
| 02 LiveKit token and room | `server/token_server.py`, `tests/test_token_server.py` |
| 03 Browser client | `web/index.html`, `web/src/*` |
| 04 Agent media pipeline | `agent/snapshots.py`, `agent/tutor.py`, `tests/test_pipeline.py` |
| 05 Fixed lesson and responses | `agent/lesson.py`, `agent/lessons/grade3_demo.yaml`, `agent/responses.py` |
| 06 Calculator and safety | `agent/calculator.py`, `tests/test_calculator.py` |
| 07 End-to-end integration | `agent/main.py`, `agent/tutor.py`, integration tests |
| 08 Testing and validation | `tests/`, `docs/` runbook notes |
| 09 Demo-day runbook | `docs/` runbook |
| 10 Personality and session memory | `agent/prompts/tutor.md`, `agent/memory.py`, `tests/test_memory.py` |

Confirm the actual paths in the card; this table is a map, not the contract.
