# Task 29: Shorten Speech Turns and Route Clear Intents Quickly

## Goal

Make ordinary voice turns feel faster while retaining reliable child speech
capture and clarification for ambiguous requests.

## Evidence

`web/src/turnDetector.ts` waits 700 ms of silence before ending a turn. Every
confident transcript then calls the local Ollama intent classifier in
`agent/controller.py`, including short commands and explicit exercise IDs.
Neither delay has been measured on the demo iPhone and laptop.

## Work

- Measure intent-classification time with local recordings. Preserve the
  current turn-detector default until device recordings justify a change.
- Use browser tests and available recordings to explore the silence window
  and onset behavior. During Task 27, check slow child speech, pauses between
  digits, background noise, and barge-in on the iPhone before accepting a
  tuned value.
- Add a narrow deterministic parser for unambiguous commands and complete
  exercise IDs (for example, "repeat", "ready", and "A2"). Keep Ollama for
  ambiguous or conversational utterances.
- Preserve the placement gate, section ambiguity rule, written-work capture
  rule, and state-machine validation. A fast path must never directly grade a
  spoken number as handwriting.
- Compare accepted-intent accuracy and turn latency before and after.

## Files

`web/src/turnDetector.ts`, `agent/controller.py`, `agent/llm.py` or a small
intent parser, browser and Python tests, and the runbook timing table.

## Acceptance

- The clear-command test set bypasses the model; ambiguous phrases still
  reach the model or ask for clarification.
- "Number two" still asks for a section, and "check my writing, it's 15"
  still requests a fresh image.
- Local recordings are not cut off by a changed turn detector, if one is
  changed. Task 27 must later confirm that result with real iPhone speech.
- Local speech-end-to-response time improves for the clear-command set
  without increasing misroutes on the available test set; Task 27 later
  records full device timing.

## Dependencies

Task 26 for the active snapshot runtime. The deterministic intent path can be
implemented and tested without a phone. Device tuning and final acceptance of
turn-detector changes belong in Task 27.

## Estimate

0.75-1 day, plus iPhone speech samples.

## Controller Rulings (2026-11-10)

- **Scope: clear-intent path only.** Implement the deterministic parser and
  its tests now. Do **not** change `web/src/turnDetector.ts`: keep
  `SILENCE_MS = 700`, `ONSET_MS = 150`, the RMS thresholds, and the 15-second
  cap exactly as they are. The human partner explicitly deferred threshold
  tuning until real iPhone recordings; simulated audio is not evidence.
  Record the measured parser/model times, but do not tune the silence window.
- **Ruling: file set.** Add `agent/intent_parser.py` and
  `tests/test_intent_parser.py`. Edit `agent/controller.py`,
  `tests/test_conversation.py`, `tests/test_session_api.py`, and
  `docs/DEMO-RUNBOOK.md` (one short note). Do not edit `web/`, `agent/llm.py`,
  `server/contract.py`, or the tutor state machine.
- **Ruling: parser contract.** `parse_clear_intent(text: str, *,
  allow_choice: bool) -> TutorIntent | None` returns a `TutorIntent` with the
  canonical name, or `None` to fall through to Ollama. Normalize case,
  punctuation, and whitespace; match whole commands or the documented
  safe prefixes. Accept:
  - `REPEAT`: `repeat`, `say that again`, `say it again`,
    `repeat that please`.
  - `READY`: `ready`, `i'm ready`, `i am ready`, `ready now`.
  - `NEXT`: `next`, `next one`, `next exercise`.
  - `DONE`: `done`, `i'm done`, `i am done`, `finish`.
  - `ASK_STEP`: `first step`, `what's the first step`, `what is the first
    step`, `what's the next step`, `what is the next step`.
  - `REVIEW`: a leading `review my worksheet`, `review the worksheet`, or
    `look at my worksheet`.
  - `CHECK_WRITING`: a leading `check my writing`, `check my paper`, or
    `check my work` (extra words such as a spoken number are allowed; the
    result is still a fresh image).
  - `CHOOSE_EXERCISE` only when `allow_choice=True`: a complete fixed id in
    the forms `A2`, `a 2`, `section A number two`, `section a, number 2`.
    Validate against A1-A6/B1-B6. A bare `number two` is **not** a clear
    choice and returns `None` so the section question runs.
  - Everything else returns `None`, including `check my answer` (context
    dependent), bare numbers, "hint", mixed commands, and conversational
    sentences. When in doubt, fall through.
- **Ruling: controller wiring.** In `handle_transcript`, after the existing
  empty/low-confidence guard, call the parser with
  `allow_choice = state.placement_confirmed and (state.chosen_exercise is None
  or self.tutor.state in {CHOOSE_EXERCISE, NEXT_EXERCISE})`. On a hit, record
  one `intent.fast_path` tool call with its duration and no text, then pass the
  intent to `_apply_intent`. On a miss, keep the current
  `ollama.interpret` path. The fast path must not change any gate: bare
  numbers still ask for a section, `CHECK_WRITING` still requests a fresh
  image, and choice still requires placement.
- **Ruling: tests.** `tests/test_intent_parser.py` covers every accepted
  phrase, every id form, the full A1-A6/B1-B6 set, and a rejection set
  (`number two`, `C1`, `A7`, `check my answer`, `is fifteen right`,
  `what is a hint`, `repeat the first step please` only if it is not an
  accepted whole command, mixed commands). Controller tests assert a clear
  command never calls the Ollama fake, a conversational turn still does, a
  low-confidence clear command returns unclear without either path, `A2`
  before placement returns the placement retry, and `check my writing, it's
  15` still requests a snapshot. Do not change the browser tests.
- **Ruling: measurement.** Report the parser cost on the test set (for example
  `time.perf_counter` over the phrase list, microsecond average) and the
  number of model calls avoided. State that end-to-end speech latency and the
  700 ms silence window remain unverified until Task 27. Add one runbook note
  that clear commands skip Ollama and that the turn detector is unchanged
  pending iPhone recordings.
- **Ruling: no pytest.** Run only `python -m py_compile` on touched Python
  files. Return status, files, compile results, acceptance status, and
  concerns. Do not run a browser, start services, commit, stage, or move
  files. The manager runs the suites.

## Completion Evidence (2026-11-11)

- Files: `agent/intent_parser.py` (new), `agent/controller.py` (fast-path call
  in `handle_transcript`), `tests/test_intent_parser.py` (new),
  `tests/test_conversation.py`, `tests/test_session_api.py`,
  `docs/DEMO-RUNBOOK.md`.
- Verified: `python -m pytest tests -q -p no:cacheprovider` -> **268 passed,
  700 subtests passed**. `python -m py_compile` on every touched Python file
  -> **exit 0**. Parser microbenchmark on the 16-phrase accepted set, 20,000
  iterations: **4.31 microseconds per call**, all 16 accepted and all 8
  rejection phrases (`number two`, `C1`, `A7`, `check my answer`,
  `is fifteen right`, `what is a hint`, a conversational sentence, a mixed
  request) returned `None`.
- Manager fix during review: three HTTP-layer fast-path tests sliced the tool
  log and forgot the `stt.transcribe` row that precedes the intent row; the
  exact expected lists now include it.
- Threshold constraint honoured: `web/src/turnDetector.ts` is unchanged
  (`SILENCE_MS = 700`, `ONSET_MS = 150`, `DEFAULT_RMS_THRESHOLD = 0.02`).
  No tuning was attempted from synthetic audio.
- Written but not run: none; the suite was run.
- Deferred/manual: real iPhone speech-end-to-response timing and a decision on
  the 700 ms window. Task 27 collects those recordings; the current default
  stands until then.
- Concerns:
  - A complete id spoken before placement deliberately falls through to
    Ollama (`allow_choice=False`), so it still costs one model call before the
    placement retry; the fast path cannot bypass the gate.
  - `CHECK_WRITING` accepts arbitrary trailing words unless they embed another
    accepted command; it never carries a candidate answer, so the image gate
    still applies.
  - The deterministic set is intentionally narrow; phrases such as "check my
    answer" remain model-classified because their meaning depends on state.
  - End-to-end latency improvement is inferred from zero model calls plus the
    microsecond parser cost, not measured on a device.
