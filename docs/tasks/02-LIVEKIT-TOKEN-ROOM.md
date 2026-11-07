# Task 02: LiveKit Token And Room

## Goal

Allow the browser to join a private LiveKit room and allow the Python agent to be dispatched.

## Specification

- Implement `GET /get-token`.
- Generate a unique room name per demo session.
- Issue a short-lived JWT.
- Grant the browser publish and subscribe permissions for microphone and camera tracks.
- Configure agent dispatch when the room opens.
- Reject missing or invalid configuration.
- Do not expose LiveKit secrets to the browser.
- One room per demo session is enough; no multi-room routing or room reuse is
  required.
- The agent must be in the room before the Start snapshot is taken.

## Acceptance Criteria

- Browser receives a valid token from `GET /get-token`.
- Browser can join a unique room.
- Agent dispatch occurs after room creation.
- Token expiration and room cleanup are handled.
- A failed token request returns a clear non-secret error.

## Dependencies

- Task 01

## Estimate

0.25 day.
