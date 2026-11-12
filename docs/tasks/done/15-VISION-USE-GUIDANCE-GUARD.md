# Task 15: Vision Parse Use, Step-Anchored Guidance, And Number Guard

## Goal

Make the Start snapshot mean something, and make the "every spoken number is
verified" invariant enforced by code instead of by luck.

## Findings Addressed

Review 2026-11-08, Required 6 and 7:

- `TutorSession.start()` validates only "12 ids in A1..B6 whose expressions
  evaluate", then speaks the YAML list regardless. A parse with the wrong
  expression for an item still passes, and the parsed data is discarded.
- `steps_for()`, the YAML `steps`, `TutorIntent.guidance_step`, and
  `allowed_numbers()` have no production call site; guidance is a fixed
  "focus" sentence.
- Nothing prevents a composed sentence from containing an unverified number.

## Specification

### Strict worksheet validation

`_is_valid_worksheet(worksheet, lesson)` in `agent/tutor.py` must require:

- exactly 12 unique `item` values equal to the fixed id set;
- for each item
  `normalize(item.expression) == normalize(exercise.verification_expression)`;
- `evaluate(item.expression).value == exercise.answer`;
- `worksheet.confidence >= 0.75`.

`normalize()` (new, in `agent/calculator.py`) lowercases, removes all
whitespace, and maps `x`, `X`, `×` to `*` and `÷` to `/`.

On failure the tutor keeps the fixed lesson, appends the existing
"I will use the worksheet items I already know." once, and the session
continues. Ruling: the parsed sheet confirms presence only; arithmetic and
speech always use `agent/lessons/grade3_demo.yaml`.

### Verified number set

In `agent/calculator.py`, replace `allowed_numbers()` (no callers) with:

```python
def verified_numbers(exercise, check) -> set[int]:
    """Answer, printed operands, and verified step intermediates. Never the
    student's answer."""
```

The student's answer must not be in the set: the tutor must not repeat a wrong
number back to the child.

### Guidance

Scope ruling: architecture 02 §3.8 puts fixed speech and guidance selection in
`agent/responses.py`, and verified numbers and steps in `agent/calculator.py`.
Do not add a new `agent/guidance.py`; the module list in §10 is the boundary.

- In `agent/responses.py`:
  - `numbers_in(text: str) -> set[int]`
  - `guard_numbers(text: str, allowed: set[int]) -> bool` (every integer in
    `text` is allowed)
  - `guidance_for(exercise: agent.lesson.Exercise, check: CheckResult,
    step_index: int | None = None) -> str`
- `guidance_for` uses `steps_for(exercise)` (already in
  `agent/calculator.py`) by `step_index`, else the first
  step whose `expected_intermediate` has not yet been reached, else step 1.
  It returns the step `prompt` only when `guard_numbers` passes; otherwise it
  returns `check.focus` (no digits).
- `TutorSession.check(student_answer, step_index=None)` on an incorrect answer
  returns `select_response("incorrect.<id>", focus=...) + " " +
  guidance_for(...)`.
- `TutorRuntime._apply_intent` passes `intent.guidance_step` into `check()`
  and into the handwriting path, so the field is finally used.
- `select_response("present.<id>")` and `select_response("correct.<id>")` are
  static catalog text; test that their numbers are all in
  `verified_numbers(...)` for every one of the 12 exercises.

## Files

- Modify: `agent/calculator.py` (`normalize`, `verified_numbers`, delete
  `allowed_numbers`)
- Modify: `agent/tutor.py` (strict validation, guidance call, `step_index`)
- Modify: `agent/responses.py` (`numbers_in`, `guard_numbers`, `guidance_for`)
- Modify: `agent/main.py` (pass `guidance_step`)
- Modify: `agent/llm.py` (no change to validation; `guidance_step` is now
  consumed)
- Test: `tests/test_responses.py` (created by Task 14),
  `tests/test_tutor.py`, `tests/test_calculator.py`

## Tests To Write

- `test_worksheet_rejects_wrong_expression`: A2 parsed as `63 + 25` ->
  invalid; `start()` returns the fallback sentence.
- `test_worksheet_rejects_duplicate_or_missing_ids`.
- `test_worksheet_accepts_exact_sheet`: the 12 fixed expressions with `0.99`.
- `test_verified_numbers_excludes_student_answer`: `check("85 - 33", "25")`
  -> `25` absent, `52` present.
- `test_guard_rejects_unverified_number`: `"The answer is 99"` -> `False`.
- `test_guidance_never_echoes_wrong_answer`: A1 checked with `14`; the
  returned text contains no `14` and every number is verified.
- `test_guidance_uses_step_index`: `step_index=2` for A1 selects "Add 6 to 9".
- `test_present_and_praise_numbers_are_verified`: loop the 12 ids.

## Acceptance Criteria

- A parse whose expressions do not match the fixed sheet is rejected and the
  session continues.
- Every dynamically composed tutor sentence passes `guard_numbers`.
- `guidance_step` from the intent reaches step selection.
- `steps_for`, the YAML steps, and `verified_numbers` all have production
  callers.
- `python -m py_compile` succeeds for every touched file.

## Dependencies

- Tasks 12 (check/state signatures) and 14 (pipeline/tests stable).

## Controller Rulings (2026-11-08)

- **Ruling: `steps_for` takes the production `Exercise`.** The current
  `steps_for(exercise: dict)` has no callers, and `TutorSession` holds
  `agent.lesson.Exercise` objects whose `steps` are already `Step` instances.
  Change it to accept `Exercise` and return `list(exercise.steps)` (keep a dict
  branch only if a test needs it). Do not construct a second parallel step
  model in `guidance_for`.
- **Ruling: remove the duplicate vision tool-call rows in `agent/tutor.py`.**
  Cards 12/14 left `TutorSession.start()` and `check_handwriting()` appending
  their own bare `vision.*` rows while `MediaPipeline` now logs the same call.
  Delete the two tutor-side `append_tool_call` calls so the pipeline is the
  single logger; leave the `calculator.check_answer` row alone. Update any test
  that asserts those rows. Cost if wrong: a session driven without the pipeline
  logs no vision call.
- **Ruling: no new module.** Guidance helpers live in `agent/responses.py`;
  `normalize` and `verified_numbers` live in `agent/calculator.py`. `tests/
  test_responses.py` already exists from Task 14; add to it.
- **Ruling: report in the final message, no report file.** Do not run pytest or
  any service; `python -m py_compile` only.

## Verification Note

Implementer writes tests, runs only `py_compile`. Manager runs
`python -m pytest tests/test_responses.py tests/test_tutor.py
tests/test_calculator.py -q`.

## Estimate

0.75 day.

## Completion Evidence (2026-11-08)

- Files: `agent/calculator.py` (`normalize`, `steps_for`, `verified_numbers`),
  `agent/responses.py` (`numbers_in`, `guard_numbers`, `guidance_for`),
  `agent/tutor.py` (strict validation, guidance, `step_index`, duplicate
  vision log removal), `agent/main.py` (`guidance_step`), `tests/
  test_responses.py`, `tests/test_tutor.py`, `tests/test_calculator.py`.
- Verified: `python -m pytest tests/test_responses.py tests/test_tutor.py
  tests/test_calculator.py -q` -> **41 passed, 336 subtests passed**. Whole
  suite minus the environment-blocked token server: **76 passed, 340
  subtests**.
- Written but not run: none.
- Fix round: the B6 subtest built a `CheckResult` whose `student_answer` was the
  correct answer; `verified_numbers` correctly discards the student's answer, so
  `5` vanished. The test now uses `check_answer(expr, None)` and the assertion
  is unchanged.
- Concerns / accepted rulings:
  - Strict validation evaluates `normalize(item.expression)` so a sheet printed
    as `6 x 4` / `÷` validates. Normalization only changes whitespace/glyphs;
    arithmetic is unchanged.
  - `steps_for` accepts `Exercise` (production) and keeps a dict branch for the
    standalone calculator test; both return the same step fields.
  - `verified_numbers` discards the student's answer unconditionally, so a
    partial answer that is also a printed operand makes the authored step prompt
    fail the guard and fall back to `check.focus`. Safe and tested.
  - `present.<id>`/`correct.<id>` numbers are asserted to be inside
    `verified_numbers` for all 12 exercises.
  - The two tutor-side `vision.*` tool-call rows are gone; `MediaPipeline` is the
    single vision logger.
  - `MediaPipeline.check` does not pass a step index (no intent object there);
    spoken checks reach `guidance_for` through `_apply_intent`.
