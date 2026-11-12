# Task 25: Selected Exercise Handwriting Read and Verified Feedback

## Goal

Read the chosen item's written answer from a new snapshot and give feedback
only when the read is supported by the image and the calculator.

## Evidence

- `agent/vision.py` asks generically for `raw_text`, `value`,
  `confidence`, and `visible_work`; it does not ask for the selected
  answer area or evidence tying a read to A2 versus B2.
- `TutorSession.check_handwriting()` accepts one model confidence threshold.
- `agent/main.py` checks a spoken candidate directly, so saying a number
  with "check my answer" can bypass the handwriting snapshot.

## Work

- Pass the selected exercise id, printed expression, and expected location
  or crop to vision. Return the extracted answer, visibility, location or
  crop evidence, and uncertainty reasons.
- Require a fresh image for a written-work check even when the utterance
  contains a candidate answer. Do not silently grade the spoken candidate
  as if it came from the paper.
- Distinguish blank, obscured, overwritten, multiple-answer, and wrong-item
  reads. Ask the student to say or rewrite the answer when uncertain; never
  mark an uncertain read wrong.
- Verify a clear candidate with the deterministic calculator. Use the
  selected item's guidance for incorrect work and praise for correct work.
- Keep a speech-only fallback explicit: "I can check what you said, but I
  cannot read your writing yet."

## Files

`agent/vision.py`, `agent/tutor.py`, the snapshot controller/API path,
`agent/responses.py`, and handwriting tests.

## Acceptance

- A clear A2 answer checks A2 even though B2 also exists.
- Missing/uncertain/wrong-region images cannot produce an incorrect mark.
- A simultaneous spoken number and "check my writing" still causes one
  fresh snapshot.
- Provider failure leaves the exercise usable for retry or spoken-only
  checking, without claiming visual confirmation.

## Dependencies

Tasks 22, 23, and 24.

## Estimate

1 day.

## Controller Rulings (2026-11-09)

- **Ruling: file set.** Edit `agent/vision.py`, `agent/tutor.py`,
  `agent/responses.py`, `agent/controller.py`, and add
  `tests/test_handwriting.py`. Update `tests/test_vision.py`,
  `tests/test_tutor.py`, `tests/test_responses.py`,
  `tests/test_session_api.py`, and `tests/test_conversation.py` where the
  spoken-check wording changes. Do not edit `server/contract.py`, `web/`,
  `agent/main.py`, or `agent/snapshots.py`.
- **Ruling: read contract.** Add visibility constants to `agent/vision.py`:
  `clear`, `blank`, `obscured`, `overwritten`, `multiple_answer`,
  `wrong_item`, with a frozen set. Extend `HandwritingRead` after
  `visible_work` with `visibility: str = "clear"`, `location: str = ""`, and
  `reasons: tuple[str, ...] = ()`, so existing constructors still work.
  `read_handwriting` validates visibility (missing -> `clear`, unknown ->
  `VisionError("Vision returned an invalid visibility")`), truncates
  `location` to 160 characters, and keeps at most five reason strings of 160
  characters. Also reject a non-object JSON payload with `VisionError` in both
  `parse_worksheet` and `read_handwriting`.
- **Ruling: selected-item payload, no answer.** Add a handwriting payload
  helper in `agent/controller.py` with exactly `id`, `section`, `item`,
  `problem`, `expression` (the lesson's printed expression), and
  `answer_area` (for example `"the answer space for item A2 in section A"`).
  It must not contain `answer` or `expected_intermediate`; the model reads the
  paper, it does not confirm a known result. The instruction asks for
  `raw_text`, `value`, `confidence`, `visible_work`, `visibility`, `location`,
  and `reasons`, and says to read only the given item's answer area.
- **Ruling: never mark uncertain work.** Add `uncertain_prompt(visibility)`
  in `agent/responses.py` with these exact keys and texts: `reading_blank` ->
  `"I cannot see an answer yet. Please write your answer and say ready."`;
  `reading_obscured` -> `"I cannot see the answer clearly. Please move your
  hand or shadow away and say ready."`; `reading_overwritten` -> `"That answer
  is hard to read. Please rewrite it clearly and say ready."`;
  `reading_multiple` -> `"I can see more than one answer. Please show just
  the answer you want me to check."`; `reading_wrong_item` -> `"I cannot find
  the answer for this item. Please show the answer space for this exercise."`;
  fallback `unclear`. Add `spoken_only_fallback` ->
  `"I can check what you said, but I cannot read your writing yet."`
  `TutorSession.check_handwriting` treats any visibility other than `clear`,
  `value is None`, blank `value`, or `confidence < threshold` as uncertain:
  return the matching prompt, do not call `check`, do not increment attempts,
  and stay able to retry. Only a clear, confident read reaches the calculator.
- **Ruling: fresh image even with a spoken number.** In the controller, a
  check intent whose transcript mentions written work (`write`, `writing`,
  `written`, `paper`, `sheet`, or `work`) is always `CHECK_WRITING`: one
  `reading_work` response with `capture_request="check"` and no calculator
  call. This applies even when the intent is `CHECK_SPOKEN_ANSWER` or legacy
  `CHECK_ANSWER` and a `candidate_answer` is present, so "check my writing,
  it's 15" cannot grade the spoken number as paper evidence.
- **Ruling: spoken-only check.** A genuine `CHECK_SPOKEN_ANSWER` may check the
  candidate with the calculator, requests no image, and prefixes the result
  with `spoken_only_fallback`. Never describe that result as read from the
  paper.
- **Ruling: uncertain snapshot response.** In `_handle_check`, an uncertain
  read returns `status="adjust_sheet"`, `capture_request="check"`, and the
  selected `exercise_id`; a clear read still returns `speaking`. A provider
  failure keeps the current retry response and the exercise, and a later
  spoken check must still work without claiming a visual read.
- **Ruling: tests.** `tests/test_handwriting.py` must cover the vision fields
  and payload (no `answer`/`expected_intermediate`, includes `answer_area`),
  unknown visibility, each uncertain prompt with no attempt increment and no
  calculator call, a clear A2 read checking A2 while B2 exists, the controller
  forcing a fresh image for "check my writing, it's 15", provider failure
  followed by a successful spoken check, and the spoken-only prefix. Update
  the Task 24 conversation expectation for the prefixed spoken-check text.
- **Ruling: no pytest.** Run only `python -m py_compile` on touched Python
  files. Return status, files, compile results, acceptance status, and
  concerns. Do not commit, stage, or move files. The manager verifies with
  `python -m pytest tests/test_vision.py tests/test_tutor.py
  tests/test_responses.py tests/test_handwriting.py tests/test_session_api.py
  tests/test_conversation.py -q` and the whole suite.

## Completion Evidence (2026-11-10)

- Files: `agent/vision.py`, `agent/tutor.py`, `agent/responses.py`,
  `agent/controller.py`; `tests/test_handwriting.py` (new),
  `tests/test_vision.py`, `tests/test_tutor.py`, `tests/test_responses.py`,
  `tests/test_session_api.py`, `tests/test_conversation.py`.
- Verified: `python -m pytest tests/test_vision.py tests/test_tutor.py
  tests/test_responses.py tests/test_handwriting.py tests/test_session_api.py
  tests/test_conversation.py -q -p no:cacheprovider` -> **143 passed, 313
  subtests passed**. Whole suite `python -m pytest tests -q` -> **267 passed,
  538 subtests passed**, with only the pre-existing
  `tests/test_token_server.py` LiveKit/`ssl` environment failure.
  `python -m py_compile` on every touched Python file -> **exit 0**.
- The first Task 25 implementer was cancelled mid-run; the partial work was
  inspected, the same session was resumed, and one test's expected blank-read
  phrase was corrected. The implemented behaviour was reviewed: selected-item
  payload without answers, visibility and reason parsing, uncertain-read
  gating before the calculator, written-work detection forcing one fresh
  image, and the spoken-only prefix.
- Written but not run: none; the named suites and the whole suite were run.
- Deferred/manual: real hosted/local vision accuracy on the printed sheet and
  real handwriting; a camera capture on the demo phone.
- Concerns:
  - The confidence threshold is the only guard against a confident but wrong
    model read; the calculator verifies arithmetic, not that the digits came
    from A2's answer space.
  - `_mentions_written_work` is substring-based (`work` also matches
    "working") and applies only to check intents; a spoken "is fifteen right,
    I'm working on it" therefore requests a fresh image.
  - Uncertain reads return `adjust_sheet` with `capture_request="check"`; the
    browser does not auto-capture on a snapshot response, so the student must
    say "ready" again.
  - `visible_work` and `reasons` are model text and may contain handwriting
    content; they are not spoken.
  - The vision request still carries the printed `problem`, which is needed to
    locate the item but is not the answer.
