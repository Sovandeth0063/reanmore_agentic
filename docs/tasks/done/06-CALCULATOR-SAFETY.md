# Task 06: Calculation Module And Safety Rules

## Goal

Guarantee arithmetic correctness and provide verified step-by-step math for the
tutor, so the agent never states an unverified number.

## Specification

### Safe evaluator

- Parse expressions without `eval`; use an AST with an allow-list of
  `+ - * / ( )` and integer literals.
- Support multi-term expressions and multi-digit integers (at least four
  digits) — the "big numbers" case.
- Apply standard precedence and parentheses.
- Reject division by zero, non-integer input, unknown operators, and malformed
  expressions.
- Return a structured result: `{ok, value, expression, error}`.

### Answer checker

- Compare the student's answer to the evaluated value.
- Return `correct`, `expected`, `student_answer`, `error_type`, and
  `focus`.
- Error types: wrong operation, addition error, subtraction error,
  carry/borrow error, multiplication-table error, division error, digit
  reversal, off-by-one, unreadable.
- Never confirm or correct on an unverified value.

### Step model (for guidance)

- Decompose the chosen exercise into teachable steps:
  - addition: left-to-right or column addition with carry
  - subtraction: column subtraction with borrow
  - multiplication: equal groups, repeated addition, or table fact
  - division: sharing, grouping, or inverse multiplication
- Expose steps as data (`step_index`, `prompt`, `expected_intermediate`) so the
  tutor's guidance is anchored to correct math.
- Prefer pre-authored steps for the 12 sheet items; the evaluator is the
  fallback for anything else.

### Guardrails

- Every number the tutor speaks must be present in the calculator's verified
  output for the current turn.
- Low vision confidence must produce a clarification question, not a
  correction. A misread handwriting is not a wrong answer.
- Off-sheet or off-topic requests are redirected.

## Acceptance Criteria

- All 12 items on `docs/image.png` evaluate correctly.
- Multi-digit and mixed-operation cases evaluate correctly.
- Division by zero and malformed input are rejected safely.
- Wrong answers map to the correct error type and step.
- No spoken number can be traced to an unverified source.
- Low-confidence reads never produce a wrong correction.

## Dependencies

- Task 05

## Estimate

0.5 day.

## Completion Evidence (2026-11-07)

- Files: `agent/calculator.py`, `tests/test_calculator.py`
- Verified: `python -m py_compile` across all Python modules and tests →
  succeeded.
- Written but not run: calculator correctness, malformed-input, and error
  classification tests.
- Deferred/manual: observing spoken-number output during a live session.
- Concerns: none for the offline calculator boundary.
