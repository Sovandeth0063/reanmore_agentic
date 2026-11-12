# Task 23: Worksheet Placement Gate and Operation Summary

## Goal

Require a readable image of the fixed worksheet before offering exercise
choice, and summarize its operation types briefly.

## Evidence

- `agent/snapshots.py` calls `tutor.start()` after a capture or vision error.
- `TutorSession.start()` treats an invalid or absent parse as a valid path to
  `CHOOSE_EXERCISE` and says it can see the worksheet.
- `agent/vision.py` has no explicit missing, partial, unreadable, or
  different-sheet result; its prompt only requests an item list.
- `agent/responses.py` speaks all 12 ids instead of summarizing the sheet.

## Work

- Return structured placement results: `missing`, `partial`, `unreadable`,
  `different_sheet`, or `ready`, with a short adjustment reason.
- Check visibility and match detected A1-A6/B1-B6 expressions against the
  versioned lesson. Use the lesson as the source of truth; do not adopt
  unverified OCR expressions or a different sheet.
- Add a waiting-for-placement state. A failed image asks for a specific
  adjustment; "Ready" requests a new snapshot. Do not proceed to exercise
  choice until the sheet is confirmed.
- Summarize A as addition/subtraction and B as multiplication/division. Do
  not spend demo time reading all 12 exercise ids.
- Keep a provider failure distinct from a poor photo. Both allow retry,
  without claiming that the sheet was read.

## Files

`agent/vision.py`, `agent/tutor.py`, `agent/responses.py`,
`agent/snapshots.py` or its upload replacement, and focused tests.

## Acceptance

- Empty/blank, cropped, dark, wrong-sheet, low-confidence, and provider-error
  fixtures never produce "I can see the worksheet" or permit a choice.
- A clear image matching the fixed sheet produces the short operation summary
  and asks where to start.
- A retake after a poor image can enter choice without starting a new session.

## Dependencies

Tasks 20 and 21.

## Estimate

1 day.

## Controller Rulings (2026-11-09)

- **Ruling: file set.** Edit `agent/vision.py`, `agent/tutor.py`,
  `agent/responses.py`, and `agent/controller.py` (the upload replacement for
  the legacy `agent/snapshots.py`). Update `tests/test_vision.py`,
  `tests/test_tutor.py`, `tests/test_responses.py`,
  `tests/test_session_api.py`, and `tests/test_lesson_flow.py`. Do not edit
  `agent/main.py`, `agent/snapshots.py`, `agent/llm.py`, `agent/memory.py`,
  `server/contract.py`, or any `web/` file. Task 26 removes the legacy media
  path.
- **Ruling: vision shape.** Add placement constants to `agent/vision.py`:
  `ready`, `missing`, `partial`, `unreadable`, `different_sheet`.
  `WorksheetParse` gains `placement: str = "ready"` and `reason: str = ""`
  after the existing fields, so existing constructors keep working. The
  `parse_worksheet` instruction asks for `placement`, `reason`, `items`, and
  `confidence`. A missing `placement` defaults to `"ready"` (the lesson match
  below still gates it); an unknown value raises
  `VisionError("Vision returned an invalid placement")`; `reason` becomes
  `str(value or "")` capped at 160 characters. Keep the existing item parsing.
- **Ruling: placement decision.** Add public
  `worksheet_placement(worksheet: WorksheetParse | None, lesson: Lesson) -> str`
  to `agent/tutor.py` and keep `_is_valid_worksheet` as
  `worksheet_placement(...) == "ready"`. Order: `None` -> `missing`; an
  unknown `worksheet.placement` -> `unreadable`; any explicit non-ready model
  placement -> itself; `confidence < 0.75` -> `unreadable`; zero items ->
  `missing`; fewer than the lesson's items -> `partial`; more items, unknown
  ids, or duplicate ids -> `different_sheet`; any item expression that does
  not normalize to the lesson expression or evaluate to the lesson answer ->
  `different_sheet`; otherwise `ready`. The lesson stays the source of truth;
  never adopt model expressions.
- **Ruling: tutor state.** Add `TutorState.WAITING_FOR_PLACEMENT`. In
  `TutorSession.__init__`: a saved chosen exercise -> `STUDENT_WORKING`; else a
  confirmed placement -> `CHOOSE_EXERCISE`; else `WAITING_FOR_PLACEMENT`.
  `start()` is allowed only in `WAITING_FOR_PLACEMENT` or `GREETING`. With a
  non-ready placement it stays waiting and returns the specific prompt without
  appending a tutor turn. With a ready placement it reaches `CHOOSE_EXERCISE`
  and returns the summary plus `ask_choice`, appending one tutor turn. Remove
  the controller's `_restore_state`; the tutor now owns it. Add
  `request_placement(status: str) -> str` that sets `WAITING_FOR_PLACEMENT`,
  returns the specific prompt, and appends no turn. Transition table:
  `(WAITING_FOR_PLACEMENT, "start") -> PARSE_WORKSHEET`,
  `(PARSE_WORKSHEET, "parse_failed") -> WAITING_FOR_PLACEMENT`; keep the rest.
- **Ruling: no bypass.** `list_worksheet()` raises `InvalidTransition` unless
  the state is `CHOOSE_EXERCISE` or `NEXT_EXERCISE`; from `NEXT_EXERCISE` it
  first takes the `"choose"` edge. `choose()` stays gated as it is. No path
  may reach `CHOOSE_EXERCISE` without a ready placement.
- **Ruling: wording.** Remove the `worksheet_list` key that names all 12 ids.
  Add `worksheet_summary`: `"I can see the worksheet. Section A is addition
  and subtraction. Section B is multiplication and division."` Both `start()`
  and `list_worksheet()` return `worksheet_summary + " " + ask_choice`; never
  enumerate exercise ids. Add these exact keys: `placement_missing` ->
  `"I cannot see the worksheet. Please place the whole sheet in the camera
  view. Say ready when it is there."`; `placement_partial` -> `"I can only
  see part of the worksheet. Please move the camera so the whole sheet fits.
  Say ready when it is there."`; `placement_unreadable` -> `"I cannot read the
  worksheet clearly. Please move it closer and keep it steady. Say ready when
  it is there."`; `placement_different` -> `"This does not look like our
  practice worksheet. Please show the grade three practice sheet. Say ready
  when it is there."` Keep `placement_retry` as the fallback. Add
  `placement_prompt(status)` mapping the four statuses to those keys and
  anything else to `placement_retry`.
- **Ruling: controller.** `_handle_review` computes
  `worksheet_placement(worksheet, self.lesson)`; when it is not `ready`, call
  `tutor.request_placement(status)` and return `status="adjust_sheet"`,
  `capture_request="review"`. Only a ready sheet may call `tutor.start(...)`
  or confirm placement. `_placement_retry(status)` uses
  `placement_prompt`. `LIST_WORKSHEET` before a confirmed placement returns
  the placement retry instead of the summary.
- **Ruling: tests.** Cover every placement status, the missing-field default,
  the unknown-value error, low confidence, empty/partial/extra/duplicate/
  wrong-expression sheets, the exact A/B summary text with no 12-id list, a
  retake on the same session reaching choice, `list_worksheet` raising before
  placement, state restore after a confirmed placement, and the controller's
  `adjust_sheet` path. Update the old assertions that an invalid sheet still
  advances to choice and that LIST_WORKSHEET names every id. Use a
  valid-sheet helper in `test_lesson_flow.py` before choosing.
- **Ruling: no pytest.** Run only `python -m py_compile` on touched Python
  files. Return status, files, compile results, acceptance status, and
  concerns. Do not commit, stage, or move files. The manager verifies with
  `python -m pytest tests/test_vision.py tests/test_tutor.py
  tests/test_responses.py tests/test_session_api.py tests/test_lesson_flow.py
  -q` and then the whole suite.

### Review Amendment (2026-11-09)

- **Ruling: a failed re-review never unsets an active session.**
  `request_placement(status)` sets `WAITING_FOR_PLACEMENT` only when the saved
  state has neither a chosen exercise nor a confirmed placement. Otherwise it
  returns the specific prompt and leaves the tutor state unchanged, so a bad
  review photo during an exercise cannot turn a following check into
  `not_allowed_in_state`.
- **Ruling: re-review status.** A successfully reviewed sheet while an
  exercise is chosen presents the problem and step again, so the controller
  returns `status="speaking"`, not `reading_work`; `reading_work` is reserved
  for a pending fresh written-work capture.
- **Ruling: fix tests.** Add a tutor test that `request_placement` after a
  valid choice keeps `STUDENT_WORKING` and leaves `check` usable, and API
  tests that a bad review snapshot with a chosen exercise returns
  `adjust_sheet` yet a subsequent check turn still succeeds, and that a valid
  review with a chosen exercise returns `speaking` with the exercise id.

## Completion Evidence (2026-11-09)

- Files: `agent/vision.py`, `agent/tutor.py`, `agent/responses.py`,
  `agent/controller.py`; `tests/test_vision.py`, `tests/test_tutor.py`,
  `tests/test_responses.py`, `tests/test_session_api.py`,
  `tests/test_lesson_flow.py`.
- Verified: `python -m pytest tests/test_vision.py tests/test_tutor.py
  tests/test_responses.py tests/test_session_api.py tests/test_lesson_flow.py
  -q -p no:cacheprovider` -> **104 passed, 244 subtests passed**. Whole suite
  `python -m pytest tests -q` -> **216 passed, 450 subtests passed**, with only
  the pre-existing `tests/test_token_server.py` LiveKit/`ssl` environment
  failure. `python -m py_compile` on every touched Python file -> **exit 0**.
- Manager review found and fixed two defects before filing:
  - `request_placement()` used to force `WAITING_FOR_PLACEMENT` even during an
    active exercise, so a bad re-review photo made the next check return
    `not_allowed_in_state`. It now only enters the gate when neither a chosen
    exercise nor a confirmed placement exists.
  - A successful re-review during an exercise returned `reading_work` with no
    pending capture; it now returns `speaking`.
  Both regressions have dedicated tests in `test_tutor.py` and
  `test_session_api.py`.
- Written but not run: none; the named suites and the whole suite were run.
- Deferred/manual: a real vision provider's placement classification, real
  photos for missing/partial/dark/wrong-sheet cases, and the Safari flow.
- Concerns:
  - A provider that ignores the new `placement` field is treated as `ready`,
    but the lesson match still classifies the sheet; a non-object JSON body
    would still raise `AttributeError` out of `parse_worksheet` because
    `_request` only catches decode errors. Task 25 should harden that.
  - Placement prompts are spoken but not appended to the turn log, so a failed
    placement does not look like progress in `state_block`.
  - `partial` is count-based (fewer than the lesson's 12 items); a cropped
    sheet that still yields 12 plausible ids but wrong expressions becomes
    `different_sheet`.
  - `recover()` with no chosen exercise now enters `WAITING_FOR_PLACEMENT`,
    which closes the old parse-failure bypass but changes the legacy
    `MediaPipeline` fallback text; Task 26 removes that path.
  - `worksheet_list` is gone; any caller that still expects all 12 ids must use
    the summary instead.
