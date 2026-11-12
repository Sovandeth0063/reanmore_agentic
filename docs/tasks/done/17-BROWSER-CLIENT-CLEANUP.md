# Task 17: Browser Client Cleanup And Delivery Contract

## Goal

Make the browser a correct consumer of the agent's messages, stop leaking the
camera and microphone when a connection fails, and remove dead capture code.

## Findings Addressed

Review 2026-11-08, optional browser findings:

- `web/src/room.ts:78-81` disconnects on publish failure but never calls
  `stop()` on the local tracks, so the camera and microphone stay live.
- `DataReceived` throws inside an event handler for non-`SyntaxError` errors
  and only reports invalid JSON.
- The "I'm looking" indicator is shown only during the initial connect, never
  while the agent reads a snapshot.
- Permission failures other than `NotAllowedError` get a generic message.
- The browser client has no start signal and no message types beyond `{text}`.

Scope ruling: `web/src/snapshots.ts` is listed in architecture 02 §3.6, so this
card does **not** delete it. Leave it untouched; the agent owns snapshots
(card 03) and no new import of it is added.

## Specification

### Delivery contract (matches Task 11)

Create `web/src/messages.ts`:

```ts
export type TutorMessage =
  | { type: "speech"; text: string }
  | { type: "interrupt" }
  | { type: "looking"; on: boolean };

export function parseTutorMessage(raw: string): TutorMessage | null;
```

Rules: unknown `type`, malformed JSON, or missing fields return `null`; the
parser never throws.

`room.ts` uses it:

- `speech` -> `speechSynthesis.cancel()` then `speak(new
  SpeechSynthesisUtterance(text))`.
- `interrupt` -> `speechSynthesis.cancel()`.
- `looking` -> `options.setLooking(on)`.

### Start signal

After both tracks are published, send
`room.localParticipant.publishData(encode({type:"start"}), {reliable:true})`.
The agent takes the Start snapshot only after this message (Task 11).

### Track lifecycle

- Keep `audio` and `video` in `let` bindings outside the `try`.
- On any failure: `audio?.stop()`, `video?.stop()`, `video?.detach()`,
  `await room.disconnect()`, then rethrow.
- On `beforeunload` and `RoomEvent.Disconnected`: stop both local tracks.
- Keep one Start button; no other student-facing controls.

### Errors and status

- Map `NotAllowedError`, `NotFoundError`, and `NotReadableError` to distinct
  short messages; everything else stays "Could not connect. Please try
  again.".
- `DataReceived` sets status on a parse failure; it never throws.
- Re-request the wake lock on `visibilitychange` when the page becomes visible
  again.

## Files

- Create: `web/src/messages.ts`
- Modify: `web/src/room.ts`
- Modify: `web/src/main.ts`
- Modify: `web/src/ui.ts` (only if the looking element needs a selector
  change)
- Do not modify or delete `web/src/snapshots.ts` (architecture 02 §3.6 lists
  it)
- Modify: `web/index.html` only if a module path changes (none expected)

## Tests

There is no browser test runner in this repository. Do not add one for this
card. `parseTutorMessage` stays a pure function so it can be tested later.

## Acceptance Criteria

- `npm run build` in `web/` succeeds (manager run).
- No new reference to `captureVideoFrame` is added and `snapshots.ts` is left
  untouched.
- A publish failure stops both local tracks before rethrowing.
- The three inbound message types are handled without throwing.
- The browser sends exactly one `{"type":"start"}` after publishing.
- Manual (deferred): iPhone Safari permission, start, speech playback, and
  reconnect.

## Dependencies

- Task 11 (message contract is defined there; build them against the same
  JSON).

## Verification Note

Implementer runs no commands beyond `npm run build` if asked; the manager runs
`npm run build` in `web/`.

## Estimate

0.5 day.

## Completion Evidence (2026-11-08)

- Files: `web/src/messages.ts` (new), `web/src/room.ts`, `web/src/main.ts`.
  `web/src/snapshots.ts`, `web/src/ui.ts`, `web/index.html` untouched.
- Verified: `npm run build` in `web/` -> `tsc --noEmit && vite build`
  succeeded (8 modules, `dist/` emitted; only the >500 kB chunk warning).
- Written but not run: no browser test runner exists; `parseTutorMessage`
  stays pure for a future runner.
- Concerns / accepted rulings:
  - `parseTutorMessage` returns `null` for malformed JSON, non-objects, unknown
    or missing `type`, missing/non-string `speech.text`, and missing/non-boolean
    `looking.on`; it never throws. Extra fields are ignored.
  - `stopLocalTracks()` stops audio, stops and detaches video; called in the
    connect catch before `room.disconnect()`, on `RoomEvent.Disconnected`, and
    on `beforeunload`.
  - Exactly one `{"type":"start"}` is published after both tracks, with
    `reliable: true`.
  - Permission mapping: `NotAllowedError`, `NotFoundError`, `NotReadableError`
    get distinct messages; everything else keeps the generic message.
  - Wake lock is re-requested on `visibilitychange` when the page is visible.
  - `web/src/snapshots.ts` was left as-is per the architecture scope ruling.
  - Deferred-manual: iPhone Safari permission, start, speech playback, and
    reconnect.
