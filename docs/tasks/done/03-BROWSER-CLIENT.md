# Task 03: Browser Client

## Goal

Build the minimal student-facing browser experience for a voice-first,
camera-visible worksheet session.

## Specification

- Show one prominent Start button.
- Request camera and microphone permission after Start.
- Use the iPhone 16 Pro Max as the selected demo device.
- Prefer the iPhone's rear camera (`facingMode: "environment"`); the laptop
  webcam is not required.
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
- The UI works on Safari on the selected iPhone 16 Pro Max.
- The laptop can host the web app while the iPhone publishes its camera and
  microphone tracks through LiveKit.

## Dependencies

- Task 02

## Estimate

0.5 day.

## Closure (2026-11-07)

Status: implemented; physical iPhone and browser build verification remain
deferred-manual.

- Implemented one-button LiveKit start flow for Safari on the iPhone 16 Pro Max.
- Publishes microphone and rear-camera tracks with mobile-friendly constraints.
- Added framing guide, status/reconnect handling, permission errors, wake-lock
  handling, and camera cleanup on failed connection.
- Verified indirectly through source inspection; no frontend package manifest or
  build command is present in this repository.
- Deferred-manual: iPhone Safari permission, LAN reachability, LiveKit join,
  tutor audio playback, and camera framing rehearsal.
