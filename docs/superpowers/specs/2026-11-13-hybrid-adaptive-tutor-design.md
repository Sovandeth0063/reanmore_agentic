# Hybrid Adaptive Tutor Design

Date: 2026-11-13
Status: approved 2026-11-13
Related: Task 34, Task 35, `docs/architecture/04-End-to-End-Pipeline.md`,
`docs/image.png` (Westline IP3 Homework 2, 12 items)

## Why

The current tutor is correct, testable, and fast, but its wording is fixed. A
demo for a Grade 3 child should feel like the Westline IP3 conversation: one
question at a time, warm prompts, hints when the child is stuck, praise when
they are right, and automatic progress through the sheet. It must still never
teach wrong arithmetic and must not turn into a free-form chatbot.

The chosen approach is a hybrid:

- the lesson, calculator, and tutor state machine stay authoritative;
- a new dialogue layer selects a teaching mode and renders warm language;
- guided flow advances A1 -> B6 unless the child chooses another exercise;
- a scenario runner records the conversation and latency as JSON, in text and
  voice modes.

## Goals

1. A warm, child-facing dialogue for the 12-item IP3 worksheet.
2. One exercise and one step at a time; wait for the child's answer.
3. Modes: explain, hint, assess, praise, redirect.
4. Auto-advance after a correct final answer; wrap up after B6.
5. Spoken intermediate and final answers continue to work, with handwriting
   checks unchanged.
6. A reproducible scenario runner that outputs JSON with every tutor reply,
   status, capture request, and per-stage latency.
7. Voice mode that drives the same conversation through VoxPocket -> 16 kHz
   PCM -> the real voice API, so text and voice can be compared.
8. No session-contract change; template fallback when the renderer is
   unavailable or invalid.

## Non-goals

- Free-form LLM arithmetic, lesson planning, or answer generation.
- More worksheets or exercises beyond the fixed 12.
- Replacing the deterministic state machine or calculator.
- Streaming TTS.
- General small talk; only brief redirects.
- Storing raw audio or images.

## Approaches considered

| Approach | Trade-off |
| --- | --- |
| Full LLM tutor | Warmest, but arithmetic errors, answer leakage, latency, cost, and non-deterministic tests |
| Richer fixed templates only | Safe and fast, but still mechanical; little adaptation |
| **Hybrid: deterministic decisions + adaptive renderer** | **Chosen**: correct math and pacing, warmer language, bounded latency, template fallback |

The LLM never decides correctness. It may choose wording and, at most, select
among vetted hints. The state machine selects the mode.

## Design

### 1. Deterministic decision layer

The tutor state machine remains the source of truth. Add:

- `flow_mode`: `guided` (demo) or `choice` (current behavior); this is a
  controller setting, not a new database column.
- `attempts_at_step`: reuse the existing `attempts` column and reset it when
  the step advances; no schema migration.
- `last_mode`: in-memory only, used to vary phrasing; not persisted.
- `answers_released`: not needed in v1 because the final answer is never
  revealed.

Mode rules:

| Event | Mode | Next action |
| --- | --- | --- |
| Correct final answer | PRAISE | Guided: present the next exercise; choice: ask for the next choice |
| Correct intermediate answer | HINT | Ask the next vetted step prompt |
| First incorrect answer | HINT | Step-anchored hint, no final answer |
| Second+ incorrect answer | EXPLAIN | Vetted simpler explanation, then the step question |
| Unclear / low-confidence speech | SIMPLIFY | Repeat the same prompt in simpler words |
| "I don't understand" / "help" | EXPLAIN | Vetted explanation, then the step question |
| "Just tell me" | ASSESS | Encourage one more try; release the final answer only after 3 attempts and an explicit confirmation |
| Off-topic | REDIRECT | One short line, then the current step |

Guided flow:

- After the worksheet review, present A1 directly instead of asking for a
  choice.
- After a correct final answer, present the next exercise in lesson order in
  the same response, for example: "That's right, 15. Next is A2: 63 + 24.
  What is 3 + 4?"
- After B6, wrap up with a short review and encouragement.
- A spoken exercise choice or "next" still works and jumps the guided order;
  the tutor resumes guided order from there.
- Choice mode remains available for tests and for a child who prefers to pick.

Answer-release policy:

- Normal flow never speaks the final answer of an exercise the child has not
  solved yet.
- Once the child answers correctly, praise may restate the answer they just
  earned (for example, "That's right, 15"). The guard's forbidden set is the
  answer of an unsolved exercise, not an already-earned one.
- There is no automatic answer reveal in v1. After three attempts, an explicit
  "tell me" returns the next vetted hint and an invitation to try it together,
  not the final answer. This matches "encourage them to try before revealing
  it" without adding a confirmation state.

Content additions:

- Add 2-3 vetted `hints` per step to `agent/lessons/grade3_demo.yaml`, authored
  in child-friendly language and verified by the calculator.
- Add mode-specific response templates (praise variants, explain openers,
  simplify prompts) to the response catalog so the template fallback is warm.
- The renderer may choose among the vetted hints; it may not invent numbers.

### 2. Renderer layer

New module `agent/render.py`:

```text
RenderRequest:
  mode: explain | hint | assess | praise | simplify | redirect
  exercise: id, problem, answer, steps
  step: prompt, expected_intermediate
  child_answer: last spoken answer or None
  allowed_numbers: verified set (never includes the final answer unless release is authorized)
  template_text: deterministic fallback
```

Two implementations:

1. **Template renderer** — always available, no network, deterministic. Uses
   the enriched response catalog and the vetted hint variants.
2. **Hosted renderer** — reuses the existing Haiku route and key
   (`INTENT_*`, shared HTTP client, stable session header). Returns one or two
   short sentences. Prompt includes the mode, problem, step, child answer, and
   allowed numbers. Response is JSON `{ "text": "..." }`.

Validation for the hosted renderer:

- Text is 1-4 short sentences and at most 240 characters.
- Every number in the text is in `allowed_numbers`; otherwise reject. The
  guard reads both digits and English number words (0-100), because the demo
  is voice-first and the child may hear "fifteen" even when the model writes
  no digits.
- Reject and use the template on timeout, HTTP failure, invalid JSON, or a
  guard violation.
- No text/prompt logging.
- Timeout: **3.0 s** on the live route (the original 1.2 s was too short; the
  demo uses the template renderer).

When the hosted renderer runs:

- HINT, EXPLAIN, SIMPLIFY, and PRAISE after a check;
- not on choices, commands, placement, or snapshot parsing;
- one renderer call per check turn at most;
- template path remains the default if `TUTOR_RENDERER=template` or the LLM
  call fails.

### 3. Controller and API

- Add `TUTOR_FLOW` (`choice` safe default; `.env` demo sets `guided`) and
  `TUTOR_RENDERER` (`template` safe and demo default; `llm` opt-in) to
  `Settings`, `.env.example`, and validation. Existing tests keep their
  current behavior; the scenario runner and demo `.env` opt into guided and
  LLM rendering explicitly.
- Pass them into `TutorController` / `TutorSession`; no change to the HTTP
  contract or response schema.
- Add intents `HELP` and `ASK_ANSWER` to the classifier vocabulary and prompt;
  map `HELP` to EXPLAIN and `ASK_ANSWER` to the hint-only release policy. Keep
  `UNCLEAR` for low confidence.
- Guided mode composes existing transitions only
  (PRAISE -> NEXT_EXERCISE -> CHOOSE_EXERCISE -> PRESENT_EXERCISE), so the
  transition table and architecture section do not change. The intermediate
  `ask_choice` text is discarded; the response is the next exercise's
  presentation. Choice mode keeps `offer_next()` and `choose()`.
- The controller renders the final text after the deterministic decision, so
  the calculator result and allowed numbers are known before the LLM sees the
  turn.
- Tool timing rows: add `tutor.render` with the provider (`template` or
  `opencode`) and duration; keep `calculator.check_answer` and `intent`.
- On renderer failure, the response is still sent with template text and
  `tutor.render` records the failure.

### 4. Scenario runner

New `scripts/run_scenario.py` and
`scripts/scenarios/ip3_homework2.yaml`.

Scenario file: ordered student lines with milestones:

- review request -> worksheet snapshot -> summary;
- A1: "nine", "fifteen";
- A2: "seven", "eighty-seven" (or the vetted step answers);
- A3: "two", "fifty-two";
- A4: "sixty-three";
- A5: "fifty-eight";
- A6: "fifty-two";
- B1: "twenty-four";
- B2: "twenty-four";
- B3: "twenty-seven";
- B4: "five";
- B5: "eight";
- B6: "five";
- "done".

The runner resolves the exact lines from the scenario file, so a change to the
step data is a scenario-file change, not a code change.

Modes:

- `--mode text`: in-process controller; call `handle_transcript` for each line;
  no STT. The initial worksheet parse is a checked-in 12-item fixture so the
  pass is deterministic and fast; `--tts` optionally synthesizes tutor lines
  to check the voice path.
- `--mode voice`: synthesize each student line through VoxPocket, resample to
  16 kHz PCM16, and send it to the live `/turn` endpoint. Use the real vision
  call for the initial review. Synthesize each tutor reply and record its WAV
  duration. This is the real voice path.
- `--mode both`: text pass pinned to `TUTOR_RENDERER=template` for a
  deterministic pedagogical transcript; voice pass uses the configured
  renderer. Compare structural fields (status, capture_request, exercise_id,
  milestones) and report a text-diff count; do not require exact text
  equality, because the LLM renderer is not reproducible.

The runner requires the backend and TTS services to be running and checks
their health; it does not start them. The live voice scenario is an opt-in
script, not part of the default test suite. Generated JSON can be written
outside the repo or under a gitignored `artifacts/` path; audio is never
stored in the repo.

JSON output (one file, no secrets, no audio in the repo):

```json
{
  "scenario": "ip3_homework2",
  "mode": "voice",
  "started_at": "2026-11-13T...",
  "worksheet": {
    "vision_ms": 3200,
    "placement": "ready",
    "items": 12
  },
  "turns": [
    {
      "index": 1,
      "student_text": "review my worksheet",
      "stt_ms": 1100,
      "intent_ms": 1000,
      "render_ms": 900,
      "tutor_text": "I can see the worksheet...",
      "status": "checking_sheet",
      "capture_request": "review",
      "tts_ms": 2300,
      "audio_seconds": 2.4,
      "total_ms": 5400
    }
  ],
  "summary": {
    "turns": 30,
    "total_ms": 180000,
    "turn_p50_ms": 3400,
    "turn_p95_ms": 5200,
    "tutor_audio_seconds": 70
  },
  "milestones": {
    "worksheet_recognized": true,
    "all_12_covered": true,
    "auto_advanced": true,
    "final_answer_leaked": false
  },
  "errors": []
}
```

The runner prints the JSON path and a short summary; the JSON contains the full
tutor replies and latencies. It never prints keys or raw audio.

### 5. Silence and interruption

- Interruption already works: `onSpeechStart` cancels the current speech.
- Add an idle prompt in the **browser** `TutorSession`
  (`web/src/session.ts`), not the backend: after the tutor finishes speaking
  and no student utterance arrives within 8 s, speak one gentle prompt and
  re-arm once per turn; clear it on speech start, utterance, stop, or a new
  response. It is a fixed template, not an LLM call, and needs no HTTP
  endpoint or contract change.

### 6. Tests

Deterministic unit tests:

- mode selection matrix (correct, intermediate, wrong, repeated wrong, unclear,
  help, answer request, off-topic);
- guided auto-advance through A1 -> B6, wrap-up after B6;
- choice mode remains unchanged;
- answer-release policy and number guard;
- renderer validation: timeout, HTTP failure, invalid JSON, forbidden number,
  too-long text -> template fallback;
- vetted hints contain only verified numbers;
- idle prompt fires once and is cleared correctly;
- scenario parser and JSON schema.

Integration:

- text scenario with fake providers: all 12 items covered, no final answer
  leaked, milestones true;
- voice scenario live: one worksheet vision call, STT + intent + render + TTS
  timings, no errors;
- existing Python and web suites stay green.

## Acceptance

- The scripted scenario produces a JSON report with every tutor reply and
  per-stage latency in text and voice modes.
- The tutor asks one question at a time, waits, hints/explains after wrong or
  intermediate answers, praises correct answers, and auto-advances A1 -> B6.
- The final answer is never spoken in the normal run; the scenario's milestone
  `final_answer_leaked` is false.
- Warm check turns stay under 3.5 s in text mode; voice mode reports the real
  STT/TTS costs.
- The renderer falls back to template text without breaking the turn if the
  hosted call fails.
- Existing 380 Python tests and 85 web tests remain green.

## Builder-check resolutions

The builder check asked ten questions. These are the settled calls; the body
above reflects them.

| Question | Decision |
| --- | --- |
| Can praise restate the answer? | Yes, only an answer the child has already earned. The forbidden set is the answer of an unsolved exercise. Auto-advance allowed numbers = solved exercise (with its answer) plus next exercise operands (without its answer). |
| Idle prompt location | Browser `web/src/session.ts`; fixed template; no API change. |
| Frozen invariants / defaults | `TUTOR_FLOW=choice` and `TUTOR_RENDERER=template` are safe defaults; the demo `.env` sets `guided`/`template`. Guided composes existing transitions, so the transition table and architecture §3.9 are unchanged. Existing tests stay green. |
| Intermediate equals final / early final | Final match first, so single-step exercises always PRAISE. An early final answer is accepted and completes the exercise. A non-final expected intermediate advances `current_step`, resets attempts, and asks the next step. |
| Answer release | v1 never reveals the final answer. After three attempts, "tell me" returns the next vetted hint and an invitation to try together; no confirmation state. |
| Number words in the guard | Extend the shared number parser to English words 0-100. Use it in `_coerce_answer`, `numbers_in`, and the renderer guard; guard-check vetted hints at authoring time. |
| `--mode both` equality | Text pass pins `TUTOR_RENDERER=template`; voice uses the configured renderer. Compare structure, not exact text; report a text-diff count. |
| What is real in each mode | Text uses a checked-in 12-item parse fixture. Voice uses the real vision snapshot, STT, intent, and TTS. Live voice is opt-in; the runner checks health but does not start services. |
| Wrap-up content | Fixed encouraging line when B6 is completed; no new persisted completed list. The runner tracks coverage for the milestone. |
| Render timeout vs budget | 3.0 s timeout; template fallback. The demo uses template, so the hosted delay is opt-in. |

## What is left to the builder

- Exact response templates and the 2-3 vetted hints per step.
- The renderer prompt wording and validation details.
- The scenario file's exact student lines for each exercise.
- The exact `HELP` / `ASK_ANSWER` classifier prompt wording (the intents
  themselves are required).
- Idle prompt timing and wording.
- Visual treatment of the next-exercise transition in the dashboard.

## Risks

- The hosted renderer adds ~1 s per check turn; target <= 3.5 s warm.
- LLM wording can leak answers or invent numbers; the guard and template
  fallback are mandatory.
- Auto-advance changes the demo's pacing; choice mode must remain available.
- The scenario file is only useful if it matches the actual vetted steps; keep
  it in sync with the lesson data.
- A real child's speech is less predictable than the script; the intent
  classifier and template fallback still need a rehearsal.

## Demo configuration ruling (2026-11-13, live evidence)

- **Voice:** browser `SpeechSynthesis` is the demo default. VoxPocket remains
  opt-in (`VITE_TTS=voxpocket`); live samples showed English short-word/math
  quality and 25-50 s latency that are unsuitable for the child-facing demo.
- **Wording:** the demo `.env` uses `TUTOR_RENDERER=template`. The hosted
  renderer is implemented and tested, but a live text run had a ~64 s provider
  stall and the global leak scan false-positived on printed operands/duplicate
  answers. The template is concise (the spoken-check disclaimer and "Let's
  work on" lead-in were removed) and keeps the turn near 2 s before browser
  speech. `llm` remains opt-in.
- **Renderer deadline:** the live hosted route needed 3.0 s, not the original
  1.2 s; `agent/render.py` uses 3.0 s with template fallback.
- **Evidence:** `docs/scenarios/results/2026-11-13-ip3_homework2-text.json` is
  the demo report. The hosted-renderer and VoxPocket voice files in that folder
  are labelled experimental/diagnostic, not demo evidence.
