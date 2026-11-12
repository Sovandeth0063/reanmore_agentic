# Task 13: Calculator Error Classification

## Goal

Make the answer checker total: every wrong answer yields a labelled error
without raising, and the labels agree with the module's own tests.

## Findings Addressed

Review 2026-11-08, Required 4 and 5:

- `check_answer("2 + 3 * 4", "20")` raises `ValueError` because `_has_carry`
  splits on `+` and calls `int("3 * 4")`.
- `off_by_one` is checked first, so the module's own assertions fail:
  `check_answer("100 - 48", "51")` returns `off_by_one` (test expects
  `carry_borrow_error`) and `check_answer("20 / 4", "6")` returns `off_by_one`
  (test expects `division_error`). Two tests in `tests/test_calculator.py` are
  red.

## Specification

### Total classification

`check_answer(expression, student_answer)` must never raise for any expression
that `evaluate()` accepts. Classification runs on the parsed AST, not on string
splitting:

- Replace `_has_carry(expression)` and `_has_borrow(expression)` with
  AST-based helpers that walk the top-level `BinOp` operands.
  `_has_carry` is true when the ones digits of the addition operands sum to at
  least 10. `_has_borrow` is true when the subtraction's right ones digit is
  greater than the left ones digit. Mixed expressions simply return `False`
  for the operation they do not match; they must not raise.
- `_error_type(expression)` keeps working for a valid expression and reports
  the outermost operation family.

### Precedence

Keep this exact order, which satisfies the existing tests:

1. `digit_reversal` (multi-digit, reversed expected digits)
2. `carry_borrow_error` (addition carries or subtraction borrows)
3. `division_error` (expression contains division)
4. `multiplication_table_error` (expression contains multiplication)
5. `off_by_one` (`abs(student - expected) == 1`)
6. `addition_error` / `subtraction_error` / `wrong_operation`

Consequences to verify: `100 - 48` with `51` -> `carry_borrow_error`;
`63 + 24` with `86` -> `off_by_one` (no carry); `20 / 4` with `6` ->
`division_error`; `85 - 33` with `25` -> `digit_reversal`; `4 + 5 + 6` with
`14` -> `carry_borrow_error`; `6 * 4` with `20` ->
`multiplication_table_error`.

### Guards

- `student_answer is None` or non-integer -> `unreadable` with expected `None`.
- Invalid expression -> `unreadable`, `expected=None`, no raise.
- Division by a non-integer result stays a rejected evaluation
  (`malformed_expression`); do not loosen the integer-only rule.

## Files

- Modify: `agent/calculator.py`
- Test: `tests/test_calculator.py`

## Tests To Write

- `test_mixed_operation_wrong_answer_does_not_raise`: table of
  `("2 + 3 * 4", "20")`, `("63 + 24 + 1", "90")`, `("10 - 2 - 3", "6")`; assert
  a string error type for each.
- `test_error_precedence_matches_contract`: one assertion per row of the
  precedence list above.
- `test_every_sheet_item_wrong_by_one_classifies`: for all 12 items, pass
  `answer + 1`; assert the returned type is one of the documented labels and
  never `unreadable`.
- Keep the existing five assertions; they are the contract.

## Acceptance Criteria

- `python -m pytest tests/test_calculator.py -q` reports 0 failures (manager
  run).
- No input accepted by `evaluate()` causes `check_answer()` to raise.
- Multi-digit and mixed-operation cases are covered.
- `python -m py_compile agent\calculator.py` succeeds.

## Dependencies

- None.

## Verification Note

Implementer writes tests, runs only `py_compile`. Manager runs
`python -m pytest tests/test_calculator.py -q`.

## Estimate

0.5 day.

## Completion Evidence (2026-11-08)

- Files: `agent/calculator.py`, `tests/test_calculator.py`.
- Verified: `python -m pytest tests/test_calculator.py -q` ->
  **10 passed, 184 subtests passed**. Full suite minus the environment-blocked
  token server: 32 passed, 186 subtests passed, 3 failed — the three failures
  are the known `tests/test_pipeline.py` `FakeTutor.memory` defects owned by
  card 14.
- Written but not run: none.
- Fix round: one test used `sorted(list) | {set}`, which raises `TypeError`;
  replaced with list concatenation. No assertion or expression removed.
- Concerns:
  - Chained subtraction does not register a borrow (`10 - 2 - 3` with `6` is
    `off_by_one`); the card only requires a string error type for that row and
    the worksheet has no chained subtraction. Accepted.
  - `expected` is now `None` for every `unreadable` result, as the card's guard
    requires; the only reader, `allowed_numbers`, skips `None`.
  - Answer coercion is stricter: bools, non-integral floats, and `"5.0"` are
    `unreadable`; integral floats and padded integer strings are accepted.
    Matches "non-integer -> unreadable".
