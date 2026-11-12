# Task 12: Session Flow Recovery, Continuation, And Resume

## Goal

Make the tutor survive a full multi-turn session: a wrong answer, a corrected
answer, a vision failure, a reconnect, and a student who says "next" or "I'm
done" must all leave the session usable.

## Findings Addressed

Review 2026-11-08, Critical 2:

- `RECOVER` has no outgoing transition, so one vision/parse failure permanently
  blocks the session.
- After `GUIDE` (wrong answer) or `PRAISE` (correct answer), the next check
  raises `InvalidTransition`; production code never calls `continue_working()`.
- `OBSERVE_WORK -> CHECK_ANSWER` exists in the table but is never emitted;
  `check_handwriting()` calls `check()` directly and crashes from that state.
- `NEXT`, `DONE`, and "which exercises are there" are not handled; `NEXT`
  falls through to the `unclear` response.
- Resume sets `STUDENT_WORKING` but `start()` then raises "already started" and
  there is no re-present path.

## Specification

### Transition table (`agent/tutor.py`)

The table must mirror architecture 02 §3.9 exactly. Do not add shortcut edges:
`Guide` and `Praise` return to `StudentWorking`, they never jump straight to
`CheckAnswer` or `PresentExercise`.

Required edges `(state, event) -> next`:

- `(GREETING, "start") -> PARSE_WORKSHEET`
- `(PARSE_WORKSHEET, "parsed") -> PRESENT_LIST`
- `(PARSE_WORKSHEET, "parse_failed") -> PRESENT_LIST`
- `(PRESENT_LIST, "presented") -> CHOOSE_EXERCISE`
- `(CHOOSE_EXERCISE, "choice_valid") -> PRESENT_EXERCISE`
- `(CHOOSE_EXERCISE, "choice_unclear") -> CHOOSE_EXERCISE`
- `(PRESENT_EXERCISE, "presented") -> STUDENT_WORKING`
- `(STUDENT_WORKING, "pause") -> OBSERVE_WORK` (pause or "check my answer")
- `(STUDENT_WORKING, "check") -> OBSERVE_WORK` (replace the direct
  `STUDENT_WORKING -> CHECK_ANSWER` edge; every check passes through
  `ObserveWork`)
- `(OBSERVE_WORK, "read_confident") -> CHECK_ANSWER`
- `(OBSERVE_WORK, "read_unclear") -> GUIDE` (low confidence asks, never
  corrects)
- `(OBSERVE_WORK, "vision_failed") -> RECOVER`
- `(CHECK_ANSWER, "correct") -> PRAISE`
- `(CHECK_ANSWER, "incorrect") -> GUIDE`
- `(CHECK_ANSWER, "vision_failed") -> RECOVER`
- `(GUIDE, "presented") -> STUDENT_WORKING`
- `(PRAISE, "more") -> NEXT_EXERCISE`
- `(PRAISE, "done") -> WRAP_UP`
- `(NEXT_EXERCISE, "choose") -> CHOOSE_EXERCISE` (diagram
  `NextExercise --> ChooseExercise`)
- `(RECOVER, "resumed") -> STUDENT_WORKING` when a chosen exercise exists,
  otherwise `CHOOSE_EXERCISE` (a parse failure at Start has no exercise yet;
  the diagram routes that through `PresentList -> ChooseExercise`)

Delete the `(PRAISE, "presented") -> STUDENT_WORKING` edge: §3.9 gives `Praise`
only `more` (-> `NEXT_EXERCISE`) and `done` (-> `WRAP_UP`).

`choose()` must be valid from `CHOOSE_EXERCISE` and `NEXT_EXERCISE`; `check()`
only from `STUDENT_WORKING`. `check_handwriting()` emits `pause` then
`read_confident`/`read_unclear`/`vision_failed`, so it never crashes from
`STUDENT_WORKING` and never bypasses `ObserveWork`. `offer_next()` takes
`PRAISE -> NEXT_EXERCISE` and returns the `ask_choice` text.

### Recovery

`recover(reason)` must end in `STUDENT_WORKING` (chosen exercise present) or
`CHOOSE_EXERCISE`, never `RECOVER`. It returns the fixed `service_error` or
`unclear` text. The chosen exercise, step, and attempts are preserved.

### Continuation

- After `GUIDE` the state is `STUDENT_WORKING` (§3.9 `Guide --> StudentWorking`),
  so the next check needs no special edge.
- After `PRAISE` the only exits are `more` (`-> NextExercise`) and `done`
  (`-> WrapUp`). A check that arrives before a choice is answered with the fixed
  "more practice" prompt and `offer_next()`; the student may redo the same
  exercise by choosing it again from `ChooseExercise`.
- `continue_working()` remains available for an explicit "next step" event and
  takes `GUIDE`/`PRAISE` to `STUDENT_WORKING`; the transition table above is the
  safety net, so no caller is required to invoke it to keep the session usable.

### Intents (`agent/llm.py`, `agent/main.py`)

- Extend `VALID_INTENTS` with `"DONE"` and `"LIST_WORKSHEET"`.
- `TutorIntent` keeps `intent`, `exercise_id`, `candidate_answer`,
  `guidance_step`.
- `TutorRuntime._apply_intent` must handle: `NEXT` -> `session.offer_next()`
  (`Praise -> NextExercise`, returns `ask_choice`; the following choice moves
  `NextExercise -> ChooseExercise -> PresentExercise`), `DONE` ->
  `session.wrap_up()` (returns `wrap_up`), `LIST_WORKSHEET` ->
  `session.list_worksheet()` (sets `PresentList`, presents the 12 ids, then
  `ChooseExercise`; returns `ask_choice`).
- Add `TutorSession.offer_next()`, `TutorSession.wrap_up()`,
  `TutorSession.list_worksheet()` with the transitions above.
- Unknown intents still return `unclear`; off-topic still returns `off_topic`.

### Resume

- Add `TutorSession.resume() -> str`: requires a chosen exercise, sets
  `STUDENT_WORKING`, and returns
  `select_response(f"present.{exercise.id}", problem=exercise.problem)` plus
  the current step prompt when one exists.
- `TutorRuntime`/worker (Task 11) calls `resume()` when the store already has a
  chosen exercise, instead of `start()`.
- `start()` keeps raising when a session already has a chosen exercise; the
  rejection is tested.

## Files

- Modify: `agent/tutor.py`
- Modify: `agent/main.py`
- Modify: `agent/llm.py`
- Test: `tests/test_tutor.py`, `tests/test_lesson_flow.py` (currently a
  docstring-only stub; fill it), `tests/test_llm.py`

## Tests To Write

- `test_full_flow_survives_wrong_then_right_then_next`: start, choose A1,
  check 14 (guide), check 15 (praise), offer next, choose B2, check 24.
  No `InvalidTransition` at any step.
- `test_recover_keeps_exercise_and_allows_retry`: start, choose A1, then force a
  vision failure through `check_handwriting()` (`StudentWorking -> ObserveWork
  -> Recover`); assert `recover()` leaves state `STUDENT_WORKING`, the chosen
  exercise unchanged, and a following check succeeds.
- `test_check_after_guide_stays_usable`: after an incorrect answer the state is
  `STUDENT_WORKING` (not `GUIDE`); a second check on the same exercise
  succeeds.
- `test_check_in_praise_routes_to_more_practice`: a check before an explicit
  next/done returns the `ask_choice` text and leaves the session on the
  `Praise -> NextExercise` path, with no `InvalidTransition`.
- `test_check_handwriting_from_student_working_after_pause`: low-confidence
  read goes `ObserveWork -> Guide` and leaves the session usable.
- `test_resume_presents_saved_exercise`: new `TutorSession` on the same store
  returns the saved problem and state `STUDENT_WORKING`.
- `test_start_twice_is_rejected`.
- `test_next_done_and_list_intents`: `_apply_intent` returns `ask_choice`,
  `wrap_up`, and the 12 ids respectively.
- `test_llm_accepts_done_and_list_intents`.

## Acceptance Criteria

- No scripted multi-turn path raises `InvalidTransition`.
- The transition table matches architecture 02 §3.9 with no shortcut edges.
- A vision failure does not block the session (card 04 criterion).
- The chosen exercise and step survive `recover()` and a new `TutorSession`.
- `test_lesson_flow.py` contains real tests, not a docstring.
- `python -m py_compile` succeeds for every touched file.

## Dependencies

- None (isolated to the tutor, intents, and their tests).

## Verification Note

Implementer writes tests, runs only `py_compile`. The manager runs
`python -m pytest tests/test_tutor.py tests/test_lesson_flow.py -q`.

## Estimate

1 day.

## Completion Evidence (2026-11-08)

- Files: `agent/tutor.py`, `agent/main.py`, `agent/llm.py`,
  `tests/test_tutor.py`, `tests/test_lesson_flow.py`, `tests/test_llm.py`.
- Verified: `python -m pytest tests/test_tutor.py tests/test_lesson_flow.py
  tests/test_llm.py -q` -> **16 passed, 4 subtests passed**. Full suite minus
  the environment-blocked token server: 43 passed, 188 subtests, 3 failed —
  only the known `tests/test_pipeline.py` `FakeTutor.memory` failures owned by
  card 14.
- Written but not run: none.
- Concerns / accepted rulings:
  - The transition table has 20 edges and matches architecture 02 §3.9 exactly
    (including `ObserveWork -> Guide` on a low-confidence read,
    `NextExercise -> ChooseExercise`, `Guide -> StudentWorking`,
    `Recover -> StudentWorking`). `PRAISE presented -> StudentWorking` and
    `NEXT_EXERCISE choice_valid -> PRESENT_EXERCISE` are gone.
  - `offer_next()`, `wrap_up()`, `continue_working()`, and `recover()` use
    method-level state resets for intents that arrive in an unexpected state,
    so a child can always recover. The transition table itself has no shortcut
    edges. Cost if wrong: the table alone does not reject every premature
    intent.
  - `check_handwriting(None)` treats a provider failure as
    `ObserveWork -> Recover` and returns `service_error`; a caller must invoke
    `recover()` to return to `StudentWorking` (the pipeline does).
  - `start()` now emits `parse_failed` for a missing/invalid worksheet and still
    presents the fixed list.
  - `resume()` is not in §3.9; it implements the demo-scope reconnect
    requirement and ends in `StudentWorking` by design.
