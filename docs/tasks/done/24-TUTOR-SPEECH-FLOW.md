# Task 24: Review, Choice, and Step-by-Step Speech Flow

## Goal

Support the student's review request, placement retry, unambiguous choice,
and spoken back-and-forth without taking extra photos.

## Evidence

`agent/llm.py` currently has no `REVIEW`, `READY`, `ASK_STEP`,
`CHECK_WRITING`, or `CHECK_SPOKEN_ANSWER` intent. The existing
`TutorSession.choose()` presents the problem, but does not provide a first
guiding step. The current start path happens before any review request.

## Work

- Extend and validate the intent schema for the target states. Interpret
  "check my answer" as a written-work check when the student is working on
  paper; treat an explicit spoken-only answer separately.
- Ask for a section when the student says only "number two" or another
  ambiguous item. Accept clear forms such as "A2" and "section A, number two."
- Present the chosen fixed expression, ask one first-step question, and
  answer follow-up questions, repeat requests, and spoken intermediate
  answers through the calculator-anchored step model.
- Restrict guidance to the selected exercise. Do not reveal the final answer
  before an attempt or state an unchecked arithmetic result.
- Persist placement and exercise/step state so a short reconnect resumes the
  right prompt. Keep `NEXT` and `DONE` valid.
- Ensure speech-only turns never call vision or request a snapshot unless the
  classified intent is review, placement retry, or written-work check.

## Files

`agent/llm.py`, `agent/tutor.py`, `agent/responses.py`, `agent/memory.py`,
`agent/prompts/tutor.md`, and conversation tests.

## Acceptance

- A scripted transcript covers review -> placement -> summary -> A2 choice ->
  first step -> follow-up question -> written-work check request.
- Ambiguous "number two" asks which section and leaves state unchanged.
- Ordinary question/repeat/spoken-step turns do not request images.
- Wrong or unsupported intents cannot bypass the placement gate or create a
  new exercise.

## Dependencies

Tasks 20 and 23. Coordinate with Task 21's API response contract.

## Estimate

1 day.

## Controller Rulings (2026-11-09)

- **Ruling: file set.** Edit `agent/llm.py`, `agent/tutor.py`,
  `agent/responses.py`, `agent/prompts/tutor.md`, `agent/controller.py`
  (the Task 21 consumer of intents), and add `tests/test_conversation.py`.
  Update `tests/test_llm.py`, `tests/test_tutor.py`,
  `tests/test_responses.py`, `tests/test_session_api.py`, and
  `tests/test_lesson_flow.py` if their intent fixtures change. Leave
  `agent/main.py`, `agent/snapshots.py`, `agent/vision.py`,
  `server/contract.py`, and `web/` untouched; Task 26 removes the legacy
  runtime. Do not change the SQLite schema: `placement_confirmed`,
  `chosen_exercise`, and `current_step` are already persisted.
- **Ruling: intent vocabulary.** `VALID_INTENTS` becomes `REVIEW`, `READY`,
  `CHOOSE_EXERCISE`, `ASK_STEP`, `REPEAT`, `CHECK_WRITING`,
  `CHECK_SPOKEN_ANSWER`, `NEXT`, `DONE`, `LIST_WORKSHEET`, `OFF_TOPIC`,
  `UNCLEAR`. Accept `CHOOSE` as an alias for `CHOOSE_EXERCISE` and normalize
  the legacy `CHECK_ANSWER` to `CHECK_SPOKEN_ANSWER` when `candidate_answer`
  is present, otherwise to `CHECK_WRITING`. The parser must keep rejecting an
  exercise outside A1-A6/B1-B6 and a guidance step outside the supplied steps.
- **Ruling: slots.** `TutorIntent` gains `section: str | None = None` and
  `number: int | None = None` after the existing fields. Parse and validate
  them: section is `A` or `B` uppercased; number is an integer 1-6. If
  `exercise_id`, `section`, and `number` are all present they must agree, or
  raise `IntentError`. A bare "number two" arrives with `exercise_id=None`,
  `section=None`, `number=2`; the model must not guess a section. Add the same
  fields to the JSON system prompt in `llm.py` and to
  `agent/prompts/tutor.md`, including "never state an unverified number" and
  "return JSON only".
- **Ruling: choice.** Add `Lesson.choice_candidates(text) -> tuple[str, ...]`
  (section+number, or the ids for a bare number) and make `resolve_choice`
  return the single candidate or `None`. `TutorSession.choose()`: exactly one
  candidate selects it; more than one returns `select_response("ask_section")`
  (`"Which section is that, A or B?"`) and stays in `CHOOSE_EXERCISE`; none
  returns `unclear` and stays. After a valid choice, return the fixed
  expression plus the exercise's first step prompt, guarded by
  `guard_numbers(step.prompt, verified_numbers(exercise))` exactly like
  `resume()`. Never reveal the final answer. The controller prefers
  `intent.exercise_id`, then `section`+`number`, then the transcript; a bare
  number goes to `ask_section`.
- **Ruling: step question.** Add `TutorSession.ask_step() -> str`: no state
  change, no capture; return the current step prompt if it passes the number
  guard, else `select_response("ask_step")` (`"What do you think the first
  step is?"`). Add the `ask_section`, `ask_step`, and
  `ready_with_exercise` responses. `ready_with_exercise` is
  `"Tell me your next step when you are ready."`
- **Ruling: intent routing in the controller.** `REVIEW` and `READY` before a
  confirmed placement -> `checking_sheet`, `capture_request="review"`.
  `READY` with a confirmed placement and no exercise -> the worksheet summary
  plus `ask_choice`, no capture. `READY` with an exercise -> `ask_step`, no
  capture. `ASK_STEP` with an exercise -> `tutor.ask_step()`, no capture;
  without an exercise, placement retry before placement and the summary after.
  `CHECK_WRITING`, and `CHECK_SPOKEN_ANSWER` without a candidate, ->
  `reading_work`, `capture_request="check"`, selected `exercise_id`.
  `CHECK_SPOKEN_ANSWER` with a candidate -> `tutor.check(...)` directly,
  `speaking`, no capture. `REPEAT`, `NEXT`, `DONE`, `LIST_WORKSHEET`,
  `OFF_TOPIC`, `UNCLEAR` keep their Task 21/23 behaviour and never request a
  capture. `CHOOSE_EXERCISE` remains placement-gated.
- **Ruling: speech vs written work.** "Check my writing" or "check my paper"
  is `CHECK_WRITING` and always needs a fresh image. A clearly spoken-only
  number ("is fifteen right?") is `CHECK_SPOKEN_ANSWER` and may use the
  calculator without a photo. When an utterance contains both a section/item
  reference and a spoken number for work on paper, prefer `CHECK_WRITING`.
  Task 25 owns the final fresh-image guarantee.
- **Ruling: reconnect.** The next turn after a rebuilt controller must resume
  from persisted `chosen_exercise` and `current_step`; `create_response()`
  already resumes. Add a test that a correct answer advances `current_step`
  and a rebuilt controller's `resume()` presents the saved next step. Do not
  add a new endpoint or change the create-session request.
- **Ruling: tests.** `tests/test_conversation.py` must script the acceptance
  path: review request -> placement retry -> ready -> summary -> A2 choice
  with the first step -> ASK_STEP follow-up -> REPEAT -> CHECK_WRITING
  capture request -> CHECK_SPOKEN_ANSWER check. Also assert: bare "number
  two" asks for the section and leaves state unchanged; ordinary
  question/repeat/spoken-step turns request no capture; an unknown or
  off-topic intent cannot bypass placement or create an exercise; a spoken
  candidate never requests an image; the legacy `CHECK_ANSWER` and `CHOOSE`
  aliases normalize; and the prompt file lists the canonical vocabulary.
- **Ruling: no pytest.** Run only `python -m py_compile` on touched Python
  files. Return status, files, compile results, acceptance status, and
  concerns. Do not commit, stage, or move files. The manager verifies with
  `python -m pytest tests/test_llm.py tests/test_tutor.py
  tests/test_responses.py tests/test_conversation.py tests/test_session_api.py
  tests/test_lesson_flow.py tests/test_main.py -q` and the whole suite.

### Review Amendment (2026-11-09)

- **Ruling: the intent model never sees the answer.** The controller's intent
  call must pass only `{id, problem, steps: [{index, prompt}]}` for the chosen
  exercise, never `answer` or `expected_intermediate`. The model cannot invent
  a `candidate_answer` from the expected result. Add a test that the payload
  the fake intent receives has no `answer` key; leave the vision handwriting
  payload unchanged until Task 25.
- **Ruling: choice wording.** Change `ask_choice` to
  `"Which section and number would you like to start with?"` and update the
  literal assertion in `tests/test_tutor.py`. `offer_next` and
  `list_worksheet` reuse the same string.

## Completion Evidence (2026-11-09)

- Files: `agent/llm.py`, `agent/tutor.py`, `agent/responses.py`,
  `agent/lesson.py` (only `choice_candidates`/`resolve_choice`),
  `agent/controller.py`, `agent/prompts/tutor.md`; `tests/test_conversation.py`
  (new), `tests/test_llm.py`, `tests/test_tutor.py`,
  `tests/test_responses.py`.
- Verified: `python -m pytest tests/test_llm.py tests/test_tutor.py
  tests/test_responses.py tests/test_conversation.py tests/test_session_api.py
  tests/test_lesson_flow.py tests/test_main.py -q -p no:cacheprovider` ->
  **127 passed, 280 subtests passed**. Whole suite `python -m pytest tests -q`
  -> **240 passed, 493 subtests passed**, with only the pre-existing
  `tests/test_token_server.py` LiveKit/`ssl` environment failure.
  `python -m py_compile` on every touched Python file -> **exit 0**.
- Manager review found and fixed:
  - `agent/prompts/tutor.md` wrapped the "never state an unverified number"
    sentence, which failed its own prompt test; the sentence now sits on one
    line.
  - The intent payload no longer includes `answer` or
    `expected_intermediate`, so the classifier cannot invent a candidate
    answer from the expected result. Vision keeps its fuller payload until
    Task 25.
  - `ask_choice` now says "Which section and number would you like to start
    with?", matching the UI brief; a literal test pins it.
- Written but not run: none; the named suites and the whole suite were run.
- Deferred/manual: real Ollama classification of the scripted transcript, a
  process-restart reconnect, and Safari speech/interrupt behaviour.
- Concerns:
  - `LIST_WORKSHEET` is kept beyond the architecture's intent list; it returns
    the placement summary and never captures.
  - The legacy `agent/main.py` runtime still matches `CHECK_ANSWER`,
    `CHOOSE_EXERCISE`, and `LIST_WORKSHEET` only; Task 26 removes it.
  - `_summary()` repeats the summary string in the controller instead of
    calling the tutor, so that answer is not logged as a tutor turn.
  - `guidance_step` is accepted even when no `candidate_answer` is present.
  - The intent payload still carries the printed `problem` and step prompts,
    which is required to guide but means the model sees the exercise wording.
