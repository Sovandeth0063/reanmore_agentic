# Task 05: Fixed Lesson And Responses

## Goal

Represent the 12 worksheet exercises, the student-choice flow, and the fixed
parts of the tutor's speech as testable data.

## Specification

- Store one worksheet record with the 12 exercises in versioned YAML.
- Include `item`, `section`, `problem`, `expression`, expected answer,
  verification expression, and teachable steps.
- Support student choice: map a spoken choice to an exercise id.
- Reject exercise ids outside the 12 fixed items.
- Remove the hint ladder and hint command from this demo.
- Keep the fixed parts of the tutor's speech in the response catalog:
  greeting, worksheet list, ask for choice, present exercise, check request,
  correct, incorrect, unclear, repeat, off-topic, wrap-up, and service error.
- Allow natural guidance wording, but only within the steps returned by the
  calculation module.
- Keep the state machine small: `Greeting`, `ParseWorksheet`, `PresentList`,
  `ChooseExercise`, `PresentExercise`, `StudentWorking`, `ObserveWork`,
  `CheckAnswer`, `Guide`, `Praise`, `NextExercise`, `WrapUp`, `Recover`.
- `ObserveWork` and `CheckAnswer` may use a snapshot; a vision failure moves to
  `Recover` without losing the session.

## Exercise Data

All 12 items from `docs/image.png`:

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

## Acceptance Criteria

- All 12 exercises have fixed answers and verification expressions.
- A spoken choice maps to the correct exercise id.
- Unknown exercise ids are rejected.
- No hint ladder or hint command exists.
- The same state and intent always select the same fixed response key for the
  fixed parts of the speech.
- The agent can resume the chosen exercise after a reconnect.

## Dependencies

- Task 04 for intent and vision data shape

## Estimate

0.75 day.

## Completion Evidence (2026-11-07)

- Files: `agent/lesson.py`, `agent/lessons/grade3_demo.yaml`,
  `agent/responses.py`, `agent/tutor.py`, `tests/test_lesson.py`,
  `tests/test_tutor.py`
- Verified: `python -m py_compile` across all Python modules and tests →
  succeeded.
- Written but not run: lesson and tutor unit tests.
- Deferred/manual: live voice-choice and reconnect rehearsal.
- Concerns: provider and device integration remains external.
