# Task 03: Browser Client

## Goal

Build the minimal student-facing browser experience for a voice-first,
camera-visible worksheet session.

## Specification

- Show one prominent Start button.
- Request camera and microphone permission after Start.
- Prefer the rear camera on mobile devices.
- Show a local camera preview and a small connection/listening status.
- Include a framing guide that shows where the whole sheet and the writing area
  should sit. The guide must make it easy to keep the sheet in frame at an
  angle.
- Join LiveKit using the token endpoint.
- Publish microphone and camera tracks.
- Play tutor audio automatically after the Start interaction.
- Do not show hint, submit, pause, or end buttons during tutoring.
- Student commands are voice-based: "check my answer", "I'm done", "repeat",
  "next", and "which exercises are there".
- Show a small "I'm looking" indicator while the agent reads a snapshot.
- Keep the screen awake while in session.
- Handle reconnect and permission failure states clearly.
- Camera preview is required. Snapshot capture is driven by the agent; the
  browser does not need its own snapshot button.

## Acceptance Criteria

- A student can start a session with one button.
- Camera and microphone tracks are published to LiveKit.
- The framing guide helps position the sheet and the writing area.
- Tutor audio is audible in the browser.
- The student can complete the flow without another button.
- The UI works on the selected demo phone or tablet.

## Dependencies

- Task 02

## Estimate

0.5 day.
