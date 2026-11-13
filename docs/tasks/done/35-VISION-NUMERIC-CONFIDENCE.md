# Task 35: Numeric Vision Confidence

## Goal

Stop the hosted vision model from intermittently returning a word
(`"confidence": "high"`) where the parser requires a number, which turns a
valid worksheet read into the `service_error`/`adjust_sheet` path.

## Evidence

Live browser smoke on the laptop:

- First snapshot returned
  `"I need a moment to check the worksheet. Please try again."` with
  `status: adjust_sheet` — the controller's provider-error path, not a
  placement complaint.
- Direct sampling of `VisionClient.parse_worksheet` on `docs/image.png`
  (hosted Haiku through the Go route): **2 of 5** calls returned
  `"confidence": "high"` and raised
  `VisionError("Vision returned an invalid worksheet shape")` in ~3.6 s.
  Numeric calls took 3.1-4.8 s and parsed 12 items.
- The instruction asks for `confidence` without naming a type.
  `test_invalid_confidence_still_raises` deliberately keeps validation strict.
- A stricter instruction ("confidence must be a number from 0 to 1 ... never a
  word") produced **10/10** valid numeric payloads in 3.1-5.3 s.

## Work

- In `agent/vision.py`, make the `parse_worksheet` instruction require
  `confidence` as a number from 0 to 1 (for example `0.9`), never a word.
- Apply the same explicit wording to the `read_handwriting` instruction, and
  match it in `LOCATE_INSTRUCTION` where it already says "0-1".
- Keep all validation unchanged: a non-numeric confidence still raises.
- Update/extend `tests/test_vision.py` so the instruction assertions require
  the numeric-confidence wording for worksheet and handwriting reads.
- No contract, schema, timeout, or retry change.

## Files

`agent/vision.py`, `tests/test_vision.py`.

## Acceptance

- The worksheet and handwriting instruction strings explicitly require a
  numeric 0-1 confidence.
- Existing strict-rejection tests still pass; the Python suite passes.
- A live 10-call sample against `docs/image.png` returns numeric confidence
  every time (manager-run).
- A browser fake-camera smoke reaches the worksheet summary, not
  `service_error`.

## Dependencies

None. Found during Task 34 live verification.

## Estimate

0.25 day.

## Controller Rulings (2026-11-13)

- **Prompt, not parser.** Do not coerce words like "high" in the parser; the
  existing strict test is intentional. Fix the instruction.
- **No retries.** Do not add a retry loop; one clear instruction is enough
  unless the live 10-call sample disproves it.
- **Tests.** Write the tests but do not run pytest; `python -m py_compile` is
  the only allowed execution. Do not commit.

## Live verification (2026-11-13)

- Root cause confirmed with the old wording: 2 of 5 direct
  `parse_worksheet` calls returned `"confidence": "high"` and raised
  `VisionError` after ~3.6 s; numeric calls took 3.1-4.8 s.
- The stricter wording quoted in Evidence measured 10/10 numeric responses
  (3.1-5.3 s) before implementation.
- After the change, `VisionClient.parse_worksheet` on `docs/image.png` returned
  10/10 valid payloads: numeric confidence 0.97-0.98, 12 items, `ready`, in
  2.95-4.07 s.
- The final browser fake-camera smoke reached the worksheet summary
  (`status:"listening"`), not the `service_error`/`adjust_sheet` path.
- Python suite: 380 passed, 785 subtests.
