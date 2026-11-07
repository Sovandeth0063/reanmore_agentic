# Task 07: End-To-End Integration

## Goal

Connect the browser, LiveKit, agent pipeline, worksheet parsing, student
choice, guidance, calculation module, and session memory into one working
five-minute session.

## Specification

Validate this complete path:

1. Start button is pressed.
2. Browser gets a token and joins the room.
3. Mic and camera tracks are published.
4. Agent is dispatched and joins before the snapshot.
5. Agent samples a frame and parses the 12 printed items.
6. Parsed expressions are validated by the calculation module.
7. Agent lists the items and asks which to start with.
8. Student chooses by voice; the choice maps to an exercise id.
9. Agent presents the exercise and guides step by step.
10. Student writes and says "check my answer" or pauses.
11. Agent samples a frame and reads the handwriting with a confidence score.
12. Low confidence triggers a clarification question.
13. High confidence sends the answer to the calculation module.
14. Calculator verifies the answer and returns the error type or next step.
15. Agent responds with calculator-anchored guidance.
16. Session memory records the exercise, step, attempts, and last answer.
17. Agent continues, offers the next exercise, or wraps up.

## Acceptance Criteria

- The agent lists all 12 items from the sheet.
- A spoken choice starts the correct exercise.
- The agent guides at least one exercise from presentation to correct answer.
- A wrong answer produces a calculator-anchored guiding response.
- A low-confidence handwriting read produces a clarification question.
- A frame or vision failure does not block the session.
- Session memory survives a reconnect and resumes the chosen exercise.
- Transcript, latency, vision results, provider errors, and calculator calls
  are logged.

## Dependencies

- Tasks 02 through 06 and 10

## Estimate

1 day.
