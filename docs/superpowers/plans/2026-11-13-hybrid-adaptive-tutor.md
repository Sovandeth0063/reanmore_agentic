# Hybrid Adaptive Tutor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the IP3 worksheet tutor teach one question at a time with warm, adaptive language and guided auto-advance, and prove it with a text/voice scenario runner that emits JSON with per-stage latency.

**Architecture:** The deterministic lesson, calculator, and tutor state machine stay authoritative. A new renderer layer rephrases the tutor's chosen HINT / EXPLAIN / SIMPLIFY / PRAISE move, with a hosted Haiku renderer, a strict number guard, and a template fallback. Guided mode composes the existing state transitions to present A1 -> B6 and auto-advance after a correct final answer. A scenario runner drives the real pipeline in text and voice modes.

**Tech Stack:** Python 3.10, FastAPI, SQLite, faster-whisper (CPU int8), hosted Haiku via the OpenCode Go route, VoxPocket TTS (separate process), TypeScript/Vite, Node test runner, pytest.

**Spec:** `docs/superpowers/specs/2026-11-13-hybrid-adaptive-tutor-design.md`

## Global Constraints

- Python 3.10; do not add runtime dependencies. Reuse `httpx`, `pyyaml`, `faster-whisper`.
- The session HTTP contract and response schema do not change.
- The calculator, lesson, and state machine are authoritative. The LLM never decides correctness.
- v1 never reveals the final answer of an unsolved exercise.
- Number checks cover digits and English number words 0-100.
- Safe defaults are `TUTOR_FLOW=choice` and `TUTOR_RENDERER=template`; the demo `.env` sets `guided` and `llm`.
- Renderer timeout is 1.2 s; template fallback on any failure; target <= 3.5 s warm check turn.
- No raw audio/images stored; never log transcript text, prompts, or keys.
- VoxPocket stays in `C:\Users\ASUS\voxcpm-tts`; `voxcpm` never becomes a backend dependency.
- Existing 380 Python tests + 785 subtests and 85 web tests must stay green.
- **Execution policy for implementers:** write tests and code, run only `python -m py_compile` / `node node_modules/typescript/bin/tsc --noEmit`, do not run pytest/npm test, do not start services, do not commit or stage. The manager runs the tests and commits.
- Work in the `feature/hybrid-adaptive-tutor` worktree.

## Review Focus

These are the input classes most likely to break a child-facing run; each has a test in the task that owns the code.

1. Spoken number words and hyphenation ("nine", "eighty-seven", "one hundred") must grade and guard correctly.
2. An intermediate answer equal to the final answer, or an early final answer, must PRAISE and advance, never stall.
3. The renderer must not speak an unsolved answer in digits or words; reject and use the template.
4. Auto-advance must cross A1 -> B6 and wrap up after B6, while a spoken choice can still interrupt.
5. A renderer timeout or stopped TTS service must still leave the child with a spoken line and an ungated recorder.

---

### Task 1: Number Words and Guarded Allowed Numbers

**Files:**
- Modify: `agent/calculator.py`
- Modify: `agent/responses.py`
- Test: `tests/test_calculator.py`
- Test: `tests/test_responses.py`

**Interfaces:**
- Produces: `parse_number(value: object) -> int | None`
- Produces: `numbers_in(text: str) -> set[int]` (digits and English words 0-100)
- Produces: `verified_numbers(exercise, check=None, *, include_answer: bool = True) -> set[int]`
- Existing `guard_numbers(text, allowed)` keeps its signature.

- [ ] **Step 1: Write the failing tests (implementer; do not run)**

In `tests/test_calculator.py` add:

```python
class NumberWordTests(unittest.TestCase):
    def test_parse_number_accepts_words_and_digits(self) -> None:
        from agent.calculator import parse_number
        self.assertEqual(parse_number("nine"), 9)
        self.assertEqual(parse_number("eighty-seven"), 87)
        self.assertEqual(parse_number("twenty one"), 21)
        self.assertEqual(parse_number("one hundred"), 100)
        self.assertEqual(parse_number("15"), 15)
        self.assertIsNone(parse_number("banana"))

    def test_check_answer_accepts_a_spoken_number_word(self) -> None:
        result = check_answer("4 + 5 + 6", "fifteen")
        self.assertTrue(result.correct)
        self.assertEqual(result.student_answer, 15)

    def test_verified_numbers_can_exclude_the_unsolved_answer(self) -> None:
        from agent.lesson import load_lesson
        lesson = load_lesson("agent/lessons/grade3_demo.yaml")
        values = verified_numbers(lesson.get("A1"), include_answer=False)
        self.assertNotIn(15, values)
        self.assertLessEqual({4, 5, 6, 9}, values)
```

In `tests/test_responses.py` add to `NumberGuardTests`:

```python
    def test_numbers_in_reads_number_words(self) -> None:
        self.assertEqual(numbers_in("The answer is fifteen and 3."), {15, 3})
        self.assertEqual(numbers_in("eighty-seven"), {87})

    def test_guard_rejects_a_word_number(self) -> None:
        self.assertFalse(guard_numbers("The answer is fifteen", {14}))
```

- [ ] **Step 2: Implement the parser and guard**

In `agent/calculator.py` add `parse_number` with:
- digits via `int(str(value).strip())`;
- English words 0-100, including hyphenated and space-separated tens/ones
  (`twenty one`, `eighty-seven`) and `one hundred`;
- `None` for anything else. `_coerce_answer` delegates to it.
- `verified_numbers(..., include_answer=True)`: when `False`, remove the
  exercise answer after collecting operands and intermediates.

In `agent/responses.py`, make `numbers_in` return `{parse_number(token) ...}`
for digit and word spans; ignore `None`. Keep `guard_numbers` as a subset
check. Do not change the response catalog text yet.

- [ ] **Step 3: Compile and report**

Run: `py -3.10 -m py_compile agent/calculator.py agent/responses.py tests/test_calculator.py tests/test_responses.py`
Expected: exit 0. Do not run pytest.

- [ ] **Step 4: Manager verification**

Run: `py -3.10 -m pytest tests/test_calculator.py tests/test_responses.py -q`
Expected: PASS, including all pre-existing cases.

- [ ] **Step 5: Manager commit**

```bash
git add agent/calculator.py agent/responses.py tests/test_calculator.py tests/test_responses.py
git commit -m "feat: parse spoken number words in grading and guards"
```

---

### Task 2: Renderer, Config, and Template Fallback

**Files:**
- Create: `agent/render.py`
- Modify: `agent/config.py`
- Modify: `.env.example`
- Test: `tests/test_render.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True)
class RenderRequest:
    mode: str                     # explain | hint | assess | praise | simplify | redirect
    exercise: Exercise
    step: Step | None
    child_answer: str | None
    template_text: str
    allowed_numbers: frozenset[int]

@dataclass(frozen=True)
class RenderResult:
    text: str
    provider: str                 # "template" or "opencode"
    fallback: bool

class Renderer(Protocol):
    def render(self, request: RenderRequest) -> RenderResult: ...

def build_renderer(settings: Settings, http=None, *, session_id: str | None = None) -> Renderer: ...
```

- Produces Settings fields: `tutor_flow: str = "choice"`, `tutor_renderer: str = "template"`.
- Env: `TUTOR_FLOW` in `{"choice", "guided"}`; `TUTOR_RENDERER` in
  `{"template", "llm"}`. Invalid values raise `ConfigurationError` naming the
  variable, never the value.

- [ ] **Step 1: Write the failing tests (implementer; do not run)**

`tests/test_config.py`:

```python
def test_tutor_defaults_keep_existing_behavior(self) -> None:
    settings = Settings.from_environment(require_secrets=False)
    self.assertEqual(settings.tutor_flow, "choice")
    self.assertEqual(settings.tutor_renderer, "template")

def test_invalid_tutor_flow_fails_fast(self) -> None:
    with patch.dict(os.environ, {"TUTOR_FLOW": "magic"}, clear=False):
        with self.assertRaises(ConfigurationError):
            Settings.from_environment(require_secrets=False)
```

`tests/test_render.py` (use a fake HTTP object; no network):

```python
def test_template_renderer_returns_the_template(self) -> None:
    result = TemplateRenderer().render(request(template_text="Add 4 and 5."))
    self.assertEqual(result.text, "Add 4 and 5.")
    self.assertEqual(result.provider, "template")
    self.assertFalse(result.fallback)

def test_hosted_renderer_returns_validated_text(self) -> None:
    http = FakeHttp('{"text": "First, what is 4 plus 5?"}')
    result = HostedRenderer(settings(), http).render(request(allowed={4, 5}))
    self.assertEqual(result.text, "First, what is 4 plus 5?")
    self.assertEqual(result.provider, "opencode")
    self.assertFalse(result.fallback)

def test_hosted_renderer_rejects_a_forbidden_word_number(self) -> None:
    http = FakeHttp('{"text": "The answer is fifteen."}')
    result = HostedRenderer(settings(), http).render(request(allowed={4, 5}, template_text="Add 4 and 5."))
    self.assertEqual(result.text, "Add 4 and 5.")
    self.assertTrue(result.fallback)

def test_hosted_renderer_falls_back_on_timeout_or_bad_json(self) -> None:
    # FakeHttp raises httpx.TimeoutException; another returns "not json".
    ...
    self.assertTrue(result.fallback)
```

Also assert: a response over 240 characters falls back; `build_renderer` returns
`TemplateRenderer` for `tutor_renderer="template"` and `HostedRenderer` for
`"llm"`.

- [ ] **Step 2: Implement `agent/render.py`**

- `TemplateRenderer.render` returns `RenderResult(request.template_text, "template", False)`.
- `HostedRenderer` uses `settings.intent_model`, `settings.intent_base_url`,
  `settings.intent_api_key or settings.vision_api_key`, and the shared HTTP
  client. POST `/chat/completions` with `response_format={"type":"json_object"}`,
  `stream=False`, and `timeout=1.2`. Add the `x-opencode-session` header only
  when the base URL hostname is exactly `opencode.ai`.
- System prompt: "You are a warm Grade 3 math tutor. Rewrite the given tutor
  line in one or two short child-friendly sentences. Keep the same teaching
  move. Use only numbers from the allowed list. Never state the final answer
  or invent a number. Return JSON {\"text\": \"...\"}."
- User payload: mode, problem, step prompt, child answer, allowed numbers,
  template text.
- Validate: text is 1-2 sentences, <= 240 chars, `numbers_in(text) <= allowed`.
  Any failure returns the template with `fallback=True`; never log text.
- `build_renderer` selects based on `settings.tutor_renderer`.

- [ ] **Step 3: Add config**

Add `tutor_flow` / `tutor_renderer` to `Settings`, `from_environment`,
validation, and `.env.example` with comments:

```text
# Demo: guided flow + hosted wording. Safe defaults are choice/template.
TUTOR_FLOW=guided
TUTOR_RENDERER=llm
```

- [ ] **Step 4: Compile and report**

Run: `py -3.10 -m py_compile agent/render.py agent/config.py tests/test_render.py tests/test_config.py`
Expected: exit 0.

- [ ] **Step 5: Manager verification**

Run: `py -3.10 -m pytest tests/test_render.py tests/test_config.py -q`
Expected: PASS.

- [ ] **Step 6: Manager commit**

```bash
git add agent/render.py agent/config.py tests/test_render.py tests/test_config.py .env.example
git commit -m "feat: add template and hosted tutor renderer"
```

---

### Task 3: Vetted Step Hints

**Files:**
- Modify: `agent/lesson.py`
- Modify: `agent/lessons/grade3_demo.yaml`
- Test: `tests/test_lesson.py`

**Interfaces:**
- Produces: `Step.hints: tuple[str, ...] = ()`.
- Loader reads `hints` from each step; missing hints become `()`.

- [ ] **Step 1: Write the failing tests**

```python
def test_every_step_has_two_vetted_hints(self) -> None:
    lesson = load_lesson("agent/lessons/grade3_demo.yaml")
    for exercise in lesson.exercises:
        for step in exercise.steps:
            self.assertGreaterEqual(len(step.hints), 2, f"{exercise.id} step {step.index}")
            for hint in step.hints:
                self.assertTrue(hint.strip())
                self.assertTrue(all(0 <= n <= 100 for n in numbers_in(hint)))
```

- [ ] **Step 2: Add hints to the YAML**

Add `hints: [ ... ]` to every step. Author two child-friendly sentences per
step. Examples:

```yaml
- {index: 1, prompt: "Add 4 and 5", expected_intermediate: 9,
   hints: ["Which two numbers should we add first?", "Start with the first two numbers."]}
- {index: 2, prompt: "Add 6 to 9", expected_intermediate: 15,
   hints: ["Now add the last number.", "What is 9 plus 6?"]}
```

For A2, use hints such as "Look at the ones digits" and "What is 3 plus 4?"
(3 and 4 are authored hint numbers; the renderer's allowed set includes them).
Do not put the exercise's final answer in a hint. The final answer must not
appear in any hint text.

- [ ] **Step 3: Load the hints**

Add `hints: tuple[str, ...] = ()` to `Step`; parse
`tuple(str(hint) for hint in step.get("hints", []))`. Keep the existing
`Step(...)` positional construction working in tests by making `hints` the last
field with a default.

- [ ] **Step 4: Compile and report**

Run: `py -3.10 -m py_compile agent/lesson.py tests/test_lesson.py`
Expected: exit 0.

- [ ] **Step 5: Manager verification**

Run: `py -3.10 -m pytest tests/test_lesson.py -q`
Expected: PASS.

- [ ] **Step 6: Manager commit**

```bash
git add agent/lesson.py agent/lessons/grade3_demo.yaml tests/test_lesson.py
git commit -m "feat: add vetted child-friendly step hints"
```

---

### Task 4: Tutor Check Modes and Guided Advance

**Files:**
- Modify: `agent/tutor.py`
- Test: `tests/test_tutor.py`
- Test: `tests/test_lesson_flow.py`

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True)
class CheckOutcome:
    text: str
    result: CheckResult | None
    mode: str          # praise | hint | explain | noop
    step: Step | None  # next step to prompt
    completed: bool

def check_with_mode(self, student_answer, step_index=None) -> CheckOutcome
def begin_guided(self, worksheet: WorksheetParse) -> str
def advance_guided(self) -> str
```

- `check()` remains and returns `(outcome.text, outcome.result)` for existing
  callers.

- [ ] **Step 1: Write the failing tests**

```python
def test_intermediate_answer_advances_the_step_and_hints(self) -> None:
    session = self.tutor_at_a1()
    outcome = session.check_with_mode("nine")
    self.assertEqual(outcome.mode, "hint")
    self.assertEqual(outcome.step.expected_intermediate, 15)
    self.assertFalse(outcome.completed)
    self.assertEqual(session.memory.get(self.sid).current_step, 2)
    self.assertEqual(session.memory.get(self.sid).attempts, 0)

def test_final_answer_is_praise_and_completes(self) -> None:
    session = self.tutor_at_a1()
    outcome = session.check_with_mode("fifteen")
    self.assertEqual(outcome.mode, "praise")
    self.assertTrue(outcome.completed)

def test_single_step_exercise_accepts_its_answer(self) -> None:
    session = self.tutor_at_a4()
    outcome = session.check_with_mode("sixty-three")
    self.assertEqual(outcome.mode, "praise")
    self.assertTrue(outcome.completed)

def test_guided_advance_goes_a1_to_a2_and_wraps_after_b6(self) -> None:
    session = self.tutor_at_a1()
    session.check_with_mode("fifteen")
    text = session.advance_guided()
    self.assertIn("A2", text)
    # move to B6 and complete it; advance_guided returns the wrap-up line
```

Also test: two incorrect attempts produce `mode="explain"`; an early final
answer is accepted; choice mode still uses `offer_next()`.

- [ ] **Step 2: Implement the mode outcome**

In `check_with_mode`:
1. Call `check_answer` as today.
2. If correct: PRAISE, `current_step + 1`, `completed=True`, reset attempts.
3. Else if the answer matches a step's `expected_intermediate` and a later step
   exists: set `current_step` to the next step, reset attempts, mode HINT,
   state GUIDE -> STUDENT_WORKING.
4. Else: increment attempts; mode HINT for the first attempt, EXPLAIN for the
   second and later; state GUIDE -> STUDENT_WORKING. Use the existing
   `guidance_for` step selection.

Keep `check()` as a wrapper. Add `begin_guided`:
- if the state is GREETING/WAITING_FOR_PLACEMENT, call `start(worksheet)`;
- if the state is CHOOSE_EXERCISE, choose the first exercise (`A1`) and return
  the worksheet summary + its presentation;
- do not speak the `ask_choice` line.

Add `advance_guided`:
- from PRAISE, call `offer_next()` then `choose(next_id)`; return the
  presentation;
- after B6, call `wrap_up()` and return its text;
- never add a new transition edge; compose the existing ones.

- [ ] **Step 3: Compile and report**

Run: `py -3.10 -m py_compile agent/tutor.py tests/test_tutor.py tests/test_lesson_flow.py`
Expected: exit 0.

- [ ] **Step 4: Manager verification**

Run: `py -3.10 -m pytest tests/test_tutor.py tests/test_lesson_flow.py -q`
Expected: PASS; update only tests that pin the old intermediate-as-incorrect
text.

- [ ] **Step 5: Manager commit**

```bash
git add agent/tutor.py tests/test_tutor.py tests/test_lesson_flow.py
git commit -m "feat: add tutor check modes and guided advance"
```

---

### Task 5: Controller Rendering, Guided Flow, and Conversation Intents

**Files:**
- Modify: `agent/controller.py`
- Modify: `agent/llm.py`
- Test: `tests/test_controller.py`
- Test: `tests/test_llm.py`
- Test: `tests/test_session_api.py`

**Interfaces:**
- `TutorController.__init__` gains:
  `renderer: Renderer | None = None`, `flow_mode: str = "choice"`.
- Consumes `build_renderer`, `RenderRequest`, `RenderResult`.
- Adds `HELP` and `ASK_ANSWER` to `VALID_INTENTS` and the classifier prompt.
- Adds a `tutor.render` tool row (name, duration, success).

- [ ] **Step 1: Write the failing tests**

```python
def test_guided_review_presents_a1(self) -> None:
    controller = self.controller(flow_mode="guided")
    response = controller.handle_snapshot(jpeg, "image/jpeg", "review")
    self.assertEqual(response.status, "speaking")
    self.assertEqual(response.exercise_id, "A1")
    self.assertIn("A1", response.tutor_text)

def test_correct_check_renders_praise_and_auto_advances(self) -> None:
    controller = self.controller(flow_mode="guided", renderer=RecordingRenderer())
    # choose A1, then send a spoken final answer
    response = controller.handle_transcript(Transcript("fifteen", 0.99))
    self.assertEqual(response.exercise_id, "A2")
    self.assertIn("A2", response.tutor_text)
    self.assertEqual(self.rows("tutor.render")[-1]["success"], 1)

def test_renderer_failure_uses_template_and_still_answers(self) -> None:
    controller = self.controller(renderer=FailingRenderer())
    response = controller.handle_transcript(Transcript("fifteen", 0.99))
    self.assertTrue(response.tutor_text)
    self.assertEqual(self.rows("tutor.render")[-1]["success"], 0)

def test_help_explains_the_current_step_without_the_answer(self) -> None:
    response = controller.handle_transcript(Transcript("I don't understand", 0.99))
    self.assertEqual(response.status, "speaking")
    self.assertNotIn("15", response.tutor_text)

def test_ask_for_the_answer_never_reveals_it(self) -> None:
    response = controller.handle_transcript(Transcript("just tell me the answer", 0.99))
    self.assertNotIn("15", response.tutor_text)
```

- [ ] **Step 2: Implement the controller flow**

- Add `self.renderer = renderer or TemplateRenderer()` and `self.flow_mode`.
- Add `_render(mode, exercise, step, child_answer, template_text, allowed)`
  that times `renderer.render`, records `tutor.render`, and returns the text.
- In `_handle_review`, guided mode calls `tutor.begin_guided(worksheet)` after
  confirming placement and returns `speaking` with `A1`.
- In `CHECK_SPOKEN_ANSWER`, use `check_with_mode`; render the mode; when
  `completed` and guided, call `tutor.advance_guided()` and append its text;
  when completed and choice, leave the current behavior.
- The allowed set: `verified_numbers(exercise, include_answer=outcome.completed)`
  plus the selected hint's numbers plus the child's answer only when it is a
  correct intermediate. When auto-advancing, also add the **next** exercise's
  problem numbers (never its answer), so the rendered line can say
  "Next is A2: 63 + 24." Never include an unsolved final answer.
- Select a hint deterministically: use `step.hints[attempts % len(step.hints)]`
  (or the first hint when attempts is 0), and include that hint's numbers in
  the allowed set.
- `HELP`: render EXPLAIN with the current step (or list the worksheet if no
  exercise). `ASK_ANSWER`: render a hint/encouragement; never the final answer.
- Extend the intent prompt and `VALID_INTENTS`; keep `_intent_from_data`
  validation. Update the prompt's "intent is exactly one of" list.

- [ ] **Step 3: Compile and report**

Run: `py -3.10 -m py_compile agent/controller.py agent/llm.py tests/test_controller.py tests/test_llm.py`
Expected: exit 0.

- [ ] **Step 4: Manager verification**

Run: `py -3.10 -m pytest tests/test_controller.py tests/test_llm.py tests/test_session_api.py -q`
Expected: PASS, with choice-mode tests pinned to `flow_mode="choice"`.

- [ ] **Step 5: Manager commit**

```bash
git add agent/controller.py agent/llm.py tests/test_controller.py tests/test_llm.py tests/test_session_api.py
git commit -m "feat: guide the tutor with rendered modes and auto-advance"
```

---

### Task 6: Runtime Wiring

**Files:**
- Modify: `server/session_api.py`
- Test: `tests/test_session_api.py`
- Test: `tests/test_stt.py`

**Interfaces:**
- The runtime's controller factory passes `renderer=build_renderer(...)`,
  `flow_mode=settings.tutor_flow`.
- No endpoint or response change.

- [ ] **Step 1: Write the failing test**

```python
def test_runtime_wires_guided_flow_and_renderer(self) -> None:
    settings = Settings(tutor_flow="guided", tutor_renderer="template")
    runtime = _Runtime(settings=settings, store=..., controller_factory=None)
    controller = runtime.controller_factory("session-1")
    self.assertEqual(controller.flow_mode, "guided")
    self.assertIsInstance(controller.renderer, TemplateRenderer)
```

- [ ] **Step 2: Implement**

In `_default_controller_factory`, build one shared `http` client and
`build_renderer(settings, http=http, session_id=session_id)` per controller;
pass it and `flow_mode=settings.tutor_flow` to `TutorController`. Keep the
existing shared transcriber. Do not construct a renderer for test factories
that inject their own controller.

- [ ] **Step 3: Compile and report**

Run: `py -3.10 -m py_compile server/session_api.py tests/test_session_api.py`
Expected: exit 0.

- [ ] **Step 4: Manager verification**

Run: `py -3.10 -m pytest tests/test_session_api.py tests/test_stt.py -q`
Expected: PASS.

- [ ] **Step 5: Manager commit**

```bash
git add server/session_api.py tests/test_session_api.py tests/test_stt.py
git commit -m "feat: wire guided flow and renderer into the runtime"
```

---

### Task 7: Browser Idle Prompt

**Files:**
- Modify: `web/src/session.ts`
- Test: `web/tests/session.test.ts`

**Interfaces:**
- `TutorSessionDeps` gains optional `timers?: TutorTimers`,
  `idlePromptMs?: number` (default 8000), `idlePrompt?: string`.
- `TutorTimers`: `{ setTimeout(callback: () => void, ms: number): unknown; clearTimeout(id: unknown): void }`.
- No HTTP or backend change.

- [ ] **Step 1: Write the failing tests**

```ts
test("an idle session speaks one gentle prompt", async () => {
  const timers = new FakeTimers();
  const harness = createHarness({ timers, idlePromptMs: 100, idlePrompt: "Take your time." });
  await harness.session.start();
  harness.timers.advance(100);
  assert.deepEqual(harness.spoken, ["Take your time."]);
  harness.timers.advance(100);
  assert.equal(harness.spoken.length, 1);
});

test("student speech cancels the idle prompt", async () => {
  // start, advance almost to the deadline, call handleSpeechStart, advance past it
});

test("stop clears the idle timer", async () => {
  // start, stop, advance past the deadline, no prompt
});
```

- [ ] **Step 2: Implement the timer**

- After `speak(text)` ends (`onEnd`), start one idle timer if started, not
  stopped, and not pending. Clear it on `handleSpeechStart`,
  `handleUtterance`, `applyResponse` (new tutor line), and `stop`.
- On fire, if still started and not pending, call `this.speak(idlePrompt)`;
  do not arm another idle prompt from the prompt's own `onEnd`.
- Use the injected timers in tests; default to `globalThis.setTimeout` /
  `clearTimeout`.

- [ ] **Step 3: Type-check and report**

Run: `node node_modules/typescript/bin/tsc --noEmit` in `web/`.
Expected: exit 0. Do not run npm test.

- [ ] **Step 4: Manager verification**

Run: `cd web && npm test -- --test-name-pattern="idle"` (or `npm test`).
Expected: PASS.

- [ ] **Step 5: Manager commit**

```bash
git add web/src/session.ts web/tests/session.test.ts
git commit -m "feat: add a browser idle prompt for waiting children"
```

---

### Task 8: Scenario Runner (Text Mode, JSON, Fixture)

**Files:**
- Create: `scripts/run_scenario.py`
- Create: `scripts/scenarios/ip3_homework2.yaml`
- Create: `scripts/scenarios/ip3_worksheet.json`
- Test: `tests/test_scenario_runner.py`

**Interfaces:**
- `load_scenario(path: str | Path) -> Scenario`
- `run_text(scenario, *, settings, store, vision, intent, renderer) -> dict`
- `write_report(report: dict, path: str | Path) -> None`
- CLI: `py -3.10 scripts/run_scenario.py --mode text [--out PATH]`.
- JSON schema exactly as in the design: `scenario`, `mode`, `worksheet`,
  `turns[]`, `summary`, `milestones`, `errors`.

- [ ] **Step 1: Write the scenario and fixture**

`scripts/scenarios/ip3_worksheet.json` is a 12-item parse fixture for A1-B6
using the item ids, problems, and expressions already in
`agent/lessons/grade3_demo.yaml`.

`scripts/scenarios/ip3_homework2.yaml`:

```yaml
name: ip3_homework2
worksheet: docs/image.png
turns:
  - student: "Ask me to review your worksheet."
  - student: "nine"
  - student: "fifteen"
  - student: "seven"
  - student: "eighty-seven"
  - student: "two"
  - student: "fifty-two"
  - student: "sixty-three"
  - student: "fifty-eight"
  - student: "fifty-two"
  - student: "twenty-four"
  - student: "twenty-four"
  - student: "twenty-seven"
  - student: "five"
  - student: "eight"
  - student: "five"
```

These lines follow the vetted steps: A1 (9, 15), A2 (7, 87), A3 (2, 52),
A4-B6 one answer each. The tutor auto-advances after each final answer.

- [ ] **Step 2: Write the failing runner test**

```python
def test_text_scenario_covers_all_twelve_and_never_leaks_an_answer(self) -> None:
    report = run_text(load_scenario(...), settings=test_settings(), store=temp_store(),
                      vision=FixtureVision(), intent=FakeIntent(), renderer=TemplateRenderer())
    self.assertEqual(report["mode"], "text")
    self.assertEqual(report["worksheet"]["items"], 12)
    self.assertEqual(len(report["turns"]), 16)
    self.assertTrue(report["milestones"]["worksheet_recognized"])
    self.assertTrue(report["milestones"]["all_12_covered"])
    self.assertTrue(report["milestones"]["auto_advanced"])
    self.assertFalse(report["milestones"]["final_answer_leaked"])
    self.assertEqual(report["summary"]["turns"], 16)
    self.assertIn("turn_p50_ms", report["summary"])
```

Also test: a missing scenario key raises a clear error; JSON writer creates the
parent directory; the fixture parses into `WorksheetParse`.

- [ ] **Step 3: Implement text mode**

- Load the scenario; build a `TutorController` with `flow_mode="guided"`,
  the real lesson/calculator, the provided intent/renderer, a no-op
  transcriber, and the fixture vision.
- For each student line, call `controller.handle_transcript(Transcript(line, 0.99))`
  and time the call. If the response has `capture_request`, send the worksheet
  snapshot through `controller.handle_snapshot(jpeg, "image/jpeg", purpose)`
  and record its time before the next line.
- Collect tool rows (`intent.interpret`, `tutor.render`,
  `vision.parse_worksheet`, `calculator.check_answer`) from the store; the
  per-turn stage fields are `intent_ms`, `render_ms`, `total_ms`; `stt_ms` is
  null in text mode.
- Track the exercise ids and correctness to compute milestones. For each tutor
  text, parse numbers with `numbers_in` and check the answers of exercises not
  yet completed; set `final_answer_leaked` if any match.
- Write JSON with the design's schema. Never write audio or keys.

- [ ] **Step 4: Compile and report**

Run: `py -3.10 -m py_compile scripts/run_scenario.py tests/test_scenario_runner.py`
Expected: exit 0.

- [ ] **Step 5: Manager verification**

Run: `py -3.10 -m pytest tests/test_scenario_runner.py -q`
Expected: PASS.

- [ ] **Step 6: Manager commit**

```bash
git add scripts/run_scenario.py scripts/scenarios tests/test_scenario_runner.py
git commit -m "feat: add the IP3 text scenario runner and JSON report"
```

---

### Task 9: Voice Runner, Live Evidence, and Docs

**Files:**
- Modify: `scripts/run_scenario.py`
- Modify: `tests/test_scenario_runner.py`
- Modify: `README.md`
- Modify: `docs/DEMO-RUNBOOK.md`
- Create: `docs/scenarios/results/2026-11-13-ip3_homework2-{text,voice}.json`

**Interfaces:**
- CLI adds `--mode voice` and `--mode both`.
- Voice mode requires `http://127.0.0.1:8000` and `http://127.0.0.1:8001`;
  it checks health and fails clearly if either is absent.
- `--audio-dir` is optional and outside the repo; no audio is committed.

- [ ] **Step 1: Write the failing voice test**

```python
def test_voice_runner_posts_audio_and_records_tts(self) -> None:
    http = FakeHttpApi()          # returns session, turn, snapshot, tts responses
    report = run_voice(load_scenario(...), http=http, tts=FakeTts())
    self.assertEqual(report["mode"], "voice")
    self.assertTrue(all(t["stt_ms"] is not None for t in report["turns"]))
    self.assertTrue(all(t["tts_ms"] is not None for t in report["turns"]))
    self.assertGreater(report["summary"]["tutor_audio_seconds"], 0)
```

Also test: a missing TTS service produces a clear error, not a traceback; a
WAV at 44.1 kHz is resampled to 16 kHz PCM before the turn.

- [ ] **Step 2: Implement voice mode**

- `POST /sessions`; for each student line, `POST /tts`, decode WAV, resample to
  16 kHz mono PCM16, `POST /turn`; if `capture_request`, `POST /snapshot` with
  `docs/image.png` converted to JPEG.
- Synthesize every tutor reply with `POST /tts`; record `tts_ms` and the WAV
  duration. Do not save audio unless `--audio-dir` is given.
- Read `stt.transcribe`, `intent.interpret`, `tutor.render`, and
  `vision.parse_worksheet` durations from the backend DB for the session.
- Summary: turn count, total ms, p50/p95 turn ms, audio seconds. Milestones as
  in text mode.
- `--mode both` runs text with `TUTOR_RENDERER=template` and voice with the
  configured renderer; compare status/capture/exercise/milestones and report a
  `text_diff_count`.

- [ ] **Step 3: Docs**

- README: hybrid config (`TUTOR_FLOW`, `TUTOR_RENDERER`), scenario command,
  result path.
- DEMO-RUNBOOK: guided behavior, renderer fallback, warm-up, and the scenario
  JSON check.
- Note that text mode uses a fixture and voice mode uses the real vision path.

- [ ] **Step 4: Compile and report**

Run: `py -3.10 -m py_compile scripts/run_scenario.py tests/test_scenario_runner.py`
Expected: exit 0.

- [ ] **Step 5: Manager verification**

Run: `py -3.10 -m pytest tests/test_scenario_runner.py -q`
Expected: PASS.

- [ ] **Step 6: Manager live run**

Start backend + TTS; prewarm TTS. Run:

```bash
py -3.10 scripts/run_scenario.py --mode text --out docs/scenarios/results/2026-11-13-ip3_homework2-text.json
py -3.10 scripts/run_scenario.py --mode voice --out docs/scenarios/results/2026-11-13-ip3_homework2-voice.json
```

Inspect: 12 exercises covered, `final_answer_leaked` false, auto-advance true,
per-stage latencies, voice STT/TTS times. Stop the services.

- [ ] **Step 7: Manager final verification and commit**

Run the full suites:

```bash
py -3.10 -m pytest tests -q -p no:cacheprovider
cd web && npm test && node node_modules/typescript/bin/tsc --noEmit && npm run build
```

Expected: all green. Commit the runner, docs, and results JSON. Open the PR for
`feature/hybrid-adaptive-tutor` after the worktree review.

---

## Self-review

- Spec coverage: number guard, renderer, guided advance, intents, idle prompt,
  scenario JSON, voice mode, docs, and live evidence all have tasks.
- Type consistency: `RenderRequest` / `RenderResult` / `CheckOutcome` names are
  used consistently across tasks 2, 4, 5, 8, and 9.
- Review focus: each listed input has a test in its owning task (word numbers
  in Task 1; intermediate/final in Task 4; forbidden answer in Task 2; B6 and
  choice in Task 4/5; renderer timeout in Task 2 and TTS fallback already
  covered by Task 34).
- Existing behavior: safe defaults `choice`/`template` keep current tests
  green; the demo `.env` opts into guided/llm.
