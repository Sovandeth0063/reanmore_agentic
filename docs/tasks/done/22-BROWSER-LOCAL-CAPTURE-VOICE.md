# Task 22: Browser Local Preview, Still Capture, and Speech Turns

## Goal

Make Safari use a local camera preview, upload only requested still images,
send short speech recordings, and speak responses.

## Evidence

`web/src/room.ts` publishes camera and microphone tracks to LiveKit at
Start. `web/src/snapshots.ts` can make a JPEG blob but has no caller.
`web/src/main.ts` connects only to a room; it cannot follow a capture
directive or submit an image.

## Work

- Keep the one Start button and framing guide. Start camera/microphone with
  browser permission and attach the camera to the local preview only.
- Record bounded utterances in the Task 20 format. Detect a speech turn
  without creating repeated silent uploads; send one audio request at a time.
- On `capture_request=review` or `check`, take one fresh JPEG from the
  preview and upload it with the session id and purpose. A placement retry
  occurs after the student says "Ready."
- Handle camera-not-ready, permission denial, upload timeout, retry, and
  disconnect without a stuck loading state. Do not auto-capture on every
  speech turn or pause in writing.
- Speak returned text with browser SpeechSynthesis. Cancel current speech
  before a new student utterance, and prevent tutor speech from being sent
  back as a student turn where possible.
- Provide simple statuses from the UI brief. Stop tracks and recordings at
  session end and page unload.

## Files

`web/src/main.ts`, `web/src/room.ts` or its replacement, `web/src/snapshots.ts`,
`web/src/messages.ts`, `web/src/ui.ts`, `web/src/styles.css`, and browser
tests or a small testable capture/transport module.

## Acceptance

- With a mocked API, "review my worksheet" causes exactly one JPEG upload;
  ordinary explanation and choice turns cause zero image uploads.
- "Ready" after a placement prompt takes a new JPEG.
- "Check my writing" takes a new JPEG even if the student also says an answer.
- Safari on the demo phone can record, upload, and speak a complete turn.
- Browser network inspection shows no continuous camera or microphone
  publication.

## Dependencies

Tasks 20 and 21.

## Estimate

1.25 days.

## Controller Rulings (2026-11-09)

- **Ruling: transport.** Stop using LiveKit in the browser. `web/src/main.ts`
  must not import `room.ts` or `messages.ts`. Leave `room.ts` and
  `messages.ts` untouched; Task 26 deletes the legacy pair and the
  `livekit-client` dependency. No new file may import `livekit-client`.
- **Ruling: file set.** Create `web/src/client.ts`, `web/src/session.ts`,
  `web/src/camera.ts`, `web/src/recorder.ts`, `web/src/turnDetector.ts`, and
  `web/src/status.ts`. Rewrite `web/src/main.ts`; edit `web/src/ui.ts`,
  `web/src/snapshots.ts` (only if a size-aware capture needs it),
  `web/src/styles.css` (only if the status line needs it), `web/tsconfig.json`,
  `web/package.json`, `web/vite.config.ts`. Add `web/tests/client.test.ts`,
  `web/tests/session.test.ts`, `web/tests/turnDetector.test.ts`, and
  `web/tests/status.test.ts`. Do not edit `web/src/contract.ts`; import its
  values and types.
- **Ruling: HTTP client.** `client.ts` exposes `createSessionClient({ fetch,
  baseUrl = "" })` with `createSession()`, `sendTurn(audio: Blob)`,
  `sendSnapshot(image: Blob, purpose, exerciseId?)`, and `endSession()`, all
  returning a validated `SessionResponse` from `contract.ts`. Use the
  contract paths, field names, and media types: `POST /sessions`,
  `POST /sessions/{id}/turn` with form field `audio` and type `audio/l16`,
  `POST /sessions/{id}/snapshot` with `image`, `purpose`, `exercise_id`,
  `DELETE /sessions/{id}`. Reject a payload that lacks `contract_version: 1`
  or uses an unknown status/capture. Throw one typed `SessionError` carrying
  the HTTP status and the contract `error.code`; never surface provider text.
  Abort each request after 20 seconds with `AbortController`.
- **Ruling: microphone format.** `recorder.ts` uses
  `getUserMedia({ audio: { channelCount: 1, echoCancellation: true,
  noiseSuppression: true, autoGainControl: true } })`, an `AudioContext`
  (request 16 kHz; resample linearly when the context rate differs), and a
  `ScriptProcessorNode` (deprecated but works in Safari) or an `AudioWorklet`
  with a `ScriptProcessor` fallback. Emit one `ArrayBuffer` of raw PCM16LE
  mono 16 kHz per utterance; never a container. Stop the source, processor,
  and tracks on `stop()`.
- **Ruling: turn detection.** Put the DOM-free part in `turnDetector.ts`:
  feed float frames plus a timestamp, return start/end events, and pack PCM16.
  Speech starts after ~150 ms above the RMS threshold and ends after ~700 ms
  below it, with a hard cap of 15 seconds (the contract maximum). Reset on
  `start()`, `reset()`, and after each emitted utterance so silence never
  produces an upload.
- **Ruling: one request at a time.** `session.ts` is the injectable
  orchestrator: `createTutorSession({ client, camera, recorder, speech, ui })`
  with `start()`, `handleUtterance(pcm)`, and `stop()`. While a turn or
  snapshot request is pending, drop further utterances rather than queueing
  them. Do not touch the DOM directly; `main.ts` passes the real dependencies.
- **Ruling: when to capture.** Capture exactly once when a **turn response**
  carries a non-null `capture_request`. Never auto-capture in response to a
  **snapshot response**, even when it repeats `capture_request`; that is the
  placement-retry or provider-failure case, where the tutor has asked the
  student to say "Ready" or retry. A snapshot response sets the status and
  speaks the text only. This prevents a capture loop; the server-side
  guarantee that "check my writing" always needs a fresh image is Task 25.
- **Ruling: capture quality.** One fresh JPEG per request from the live
  `<video>` via `captureVideoFrame`. If the blob exceeds
  `MAX_IMAGE_BYTES`, re-encode once at quality 0.6; if it is still too large,
  report a retry status and do not upload. Send `purpose` = `review` or
  `check` and the response's `exercise_id` when present.
- **Ruling: speech.** Speak every response's `tutor_text` with
  `SpeechSynthesisUtterance`, including service and retry text. Cancel the
  current utterance when the student starts speaking and before speaking a
  new response. While speech is active, require double the onset RMS and
  reset the turn detector when speech starts, so the tutor's own voice is not
  uploaded as a student turn. Do not cancel speech merely because a request
  is pending.
- **Ruling: status line.** Map the contract status to this exact UI text in
  `status.ts`: `ready` -> `Ready`, `listening` -> `Listening`,
  `checking_sheet` -> `Checking the sheet...`, `adjust_sheet` -> `Move the
  sheet into view`, `reading_work` -> `Reading your answer...`, `speaking` ->
  `Speaking...`. Show the looking indicator for `checking_sheet` and
  `reading_work` only.
- **Ruling: lifecycle.** `start()` creates the session, starts the camera and
  recorder, and speaks the create response. `stop()` ends the session with
  `keepalive: true` when the page hides (`pagehide`), stops all tracks and the
  audio context, and cancels speech; it must be safe to call twice. On a 404
  `invalid_session`, stop and re-enable the Start button. Any other failure
  keeps the session usable and shows a retry status; never leave the Start
  button disabled or a loading state stuck.
- **Ruling: testability.** `tsconfig.json` gains
  `"allowImportingTsExtensions": true` and `"include": ["src", "tests"]`;
  relative imports between new modules and from tests use explicit `.ts`
  specifiers so Node 24 can strip types. Add `"test": "node --test tests"` to
  `package.json`. `vite.config.ts` proxies `/sessions` to
  `http://127.0.0.1:8000` (and keeps `/get-token` until Task 26). Tests must
  drive `session.ts` with fakes and a mocked client to prove: review causes
  exactly one JPEG; ordinary explanation/choice turns cause zero; a placement
  retry waits for the next turn and then captures once; a check response
  captures one JPEG even when the utterance also names an answer; a snapshot
  response never triggers another capture; speech is spoken and cancelled;
  a transport failure does not wedge the session.
- **Ruling: no test run.** The implementer runs only
  `node node_modules/typescript/bin/tsc --noEmit` in `web/`. Do not run
  `node --test`, `npm install`, `vite build`, or start a server. Do not
  commit, stage, or move files. The manager runs the tests. Device/Safari
  checks stay deferred-manual.

## Completion Evidence (2026-11-09)

- Files: `web/src/client.ts`, `web/src/session.ts`, `web/src/camera.ts`,
  `web/src/recorder.ts`, `web/src/turnDetector.ts`, `web/src/status.ts` (new);
  `web/src/main.ts` (rewritten, no LiveKit); `web/src/ui.ts`,
  `web/src/snapshots.ts`, `web/tsconfig.json`, `web/package.json`,
  `web/vite.config.ts`; `web/tests/client.test.ts`,
  `web/tests/session.test.ts`, `web/tests/turnDetector.test.ts`,
  `web/tests/status.test.ts`, plus `web/tests/node-shims.d.ts` (hand-written
  `node:test`/`node:assert` declarations because `@types/node` is absent).
  `web/src/room.ts`, `web/src/messages.ts`, and `web/src/contract.ts` are
  untouched.
- Verified: `node node_modules/typescript/bin/tsc --noEmit` in `web/` ->
  **exit 0**. `npm test` (`node --test "tests/*.test.ts"`) -> **40 tests,
  40 passed**. The suite proves one JPEG per review, zero for ordinary or
  choice turns, a placement retry that waits for the next turn, a check image
  even when the utterance names an answer, no capture after a snapshot
  response, speech/cancel behaviour, one request in flight, and 404 recovery.
- Manager fixes during review: the package test script pointed at a directory
  and did not run; it now uses the test glob. The camera constraints now ask
  for 1920x1080 so handwriting OCR gets a usable frame. The resampler copies
  the audio-engine buffer on the equal-rate path, since that buffer may be
  reused between callbacks.
- Written but not run: none; the four browser-logic suites were run.
- Deferred/manual: Safari on the demo phone (permission, recording, upload,
  speech, network inspection), a real backend, and VAD threshold tuning with
  real room noise.
- Concerns:
  - `ScriptProcessorNode` is deprecated. It was chosen for Safari reliability;
    an AudioWorklet migration is future work.
  - The microphone runs from Start and relies on RMS thresholds plus disabled
    echo cancellation to avoid uploading the tutor's own voice. Real-device
    tuning is unverified.
  - `web/src/room.ts`, `messages.ts`, and the `livekit-client` dependency
    remain until Task 26; nothing imports them now.
  - Server-side "check my writing always needs a fresh image" is Task 25; the
    browser only follows a served `capture_request`.
  - `endSession` uses `keepalive`, but the 20-second abort timer still applies
    during page unload.
