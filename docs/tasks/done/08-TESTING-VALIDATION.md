# Task 08: Testing And Validation

## Goal

Verify that the interactive one-sheet demo is reliable enough for a five-minute
demonstration.

## Specification

### Automated Tests

- Calculation module correctness for all 12 items.
- Multi-digit and mixed-operation cases.
- Division by zero and malformed input rejection.
- Exercise-choice mapping from spoken input.
- State transitions across the full flow.
- Fixed response key selection.
- Invalid intent and unknown exercise id rejection.
- Session memory read and write.
- Token endpoint failure handling.

### Vision Tests

- Parse the 12 printed items from a clean snapshot.
- Parse the 12 printed items from an angled snapshot.
- Read handwritten answers at several confidence levels.
- Confirm low-confidence reads trigger clarification, not correction.
- Confirm a failed snapshot does not block the session.

### Manual Tests

- Correct answer on the first try.
- Wrong answer and guiding response.
- "Check my answer."
- "Repeat."
- Silence and background noise.
- Unclear handwriting.
- Student interruption while the tutor speaks.
- Student chooses different exercises.
- Network reconnect.
- Frame or vision provider failure.

### Performance Tests

- Measure VAD-to-STT latency.
- Measure STT-to-Ollama latency.
- Measure snapshot-to-vision-result latency.
- Measure total time until tutor audio begins.
- Target approximately 2.5 seconds for normal responses.

## Acceptance Criteria

- All automated tests pass.
- The scripted conversation matrix passes for correct, wrong, check, repeat,
  silence, unclear handwriting, and exercise choice.
- No unverified arithmetic feedback is observed.
- No low-confidence read produces a correction.
- The demo works on the selected mobile browser and network.
- Known limitations are written in the demo runbook.

## Dependencies

- Task 07

## Estimate

1 day.

## Completion Evidence (2026-11-07)

- Files: `tests/test_config.py`, `tests/test_token_server.py`,
  `tests/test_pipeline.py`, `tests/test_calculator.py`, `tests/test_lesson.py`,
  `tests/test_memory.py`, `tests/test_tutor.py`, `tests/test_llm.py`
- Verified: `python -m py_compile` across all Python modules and tests →
  succeeded; `npm run build` in `web/` → succeeded.
- Written but not run: automated unit/integration tests and scripted
  conversation matrix.
- Deferred/manual: vision snapshots, iPhone Safari, network reconnect,
  performance measurements, and three full rehearsals.
- Concerns: test execution requires the manager's test-run policy and provider
  setup.
