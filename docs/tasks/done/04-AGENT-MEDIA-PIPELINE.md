# Task 04: Agent Media Pipeline

## Goal

Receive LiveKit media and turn speech and snapshots into structured data the
tutor can act on.

## Specification

### Audio

- Subscribe to the student's microphone and camera tracks.
- Run Silero VAD on microphone audio.
- Transcribe speech segments locally with faster-whisper.
- Log transcript text and confidence without storing raw audio.
- Stop or interrupt tutor audio when the student begins speaking.

### Worksheet snapshot at Start

- Sample one camera frame after the agent joins and the student presses Start.
- Send the frame to the vision provider with a structured-output request.
- Extract the 12 printed items as `{item, section, problem, expression}`.
- Validate every parsed expression with the calculation module.
- If parsing fails, fall back to the fixed 12-item list for this worksheet and
  say so once, without blocking the session.

### Handwriting snapshot on check

- Sample a fresh frame when the student says "check my answer", asks to check,
  or pauses in writing.
- Send the frame plus the current exercise context to the vision provider.
- Extract the handwritten answer, any visible intermediate work, and a
  confidence score.
- Low confidence must produce a clarification question, never a correction.

### Reasoning

- Send the transcript, the current exercise, the session state, and the vision
  result to the local Ollama model.
- Require structured output: intent, chosen exercise, candidate answer,
  confidence, and a guidance step reference.
- The model may phrase guidance, but every number it speaks must come from the
  calculation module's verified output for the current turn.

### Output

- Send only approved response text back to the browser.
- Use browser `SpeechSynthesis` to speak the response.
- Update session memory after every turn.

## Acceptance Criteria

- Speech becomes a usable transcript.
- One Start snapshot produces a validated list of 12 exercises.
- A check snapshot produces a handwritten answer and confidence score.
- Low-confidence reads produce a clarification question.
- Ollama returns valid structured output for the current exercise.
- Response text reaches the browser and is spoken by `SpeechSynthesis`.
- Barge-in stops or interrupts tutor speech.
- A vision or parse failure does not block the session.
- Local service failures return a controlled retry response.

## Dependencies

- Tasks 01 and 02

## Estimate

1.5 days.

## Closure (2026-11-07)

Status: implemented; live provider and LiveKit media verification remain
deferred-manual.

- Added event-driven `MediaPipeline` coordination for Start and handwriting
  checks.
- Added safe frame-stream cleanup without storing raw media.
- Worksheet parse and handwriting reads use structured vision boundaries.
- Vision failures fall back to the fixed lesson or controlled retry response.
- Low-confidence handwriting is routed through the tutor clarification path.
- Added `tests/test_pipeline.py` covering worksheet start, snapshot failure
  fallback, and handwriting checks.
- Verified with:
  `python -m py_compile agent\snapshots.py agent\tutor.py agent\vision.py tests\test_pipeline.py`
- Deferred-manual: LiveKit track subscription, Silero VAD, faster-whisper,
  Ollama, hosted vision, barge-in, and browser SpeechSynthesis.
