# Task 32: Laptop Dashboard with Local Webcam

## Goal

Move the tutor UI, microphone, speaker, and camera to the **laptop**. The
laptop shows a three-pane dashboard (question paper, live answer sheet, tutor
review) and uses an external webcam for the sheet. The iPhone and LiveKit are
removed from the active demo.

## Evidence

The current client is phone-first: `web/src/main.ts` starts a local camera on
the phone, `web/src/ui.ts` renders a single status line, and there is no
dashboard. The session, recorder, speech, and snapshot modules are reusable.
`web/src/camera.ts` already requests 1920x1080 and captures JPEGs.
`docs/image.png` is the fixed question paper. The webcam-only design is in
`docs/superpowers/specs/2026-11-12-laptop-dashboard-webcam-design.md`.

## Work

- Replace the phone screen with a laptop dashboard:
  - Header: title, session status pill, camera status (`Camera ready` /
    `Camera blocked`), and a discreet **End** action.
  - Question Paper pane: the fixed sheet from `web/public/worksheet.png`;
    outline the selected exercise using the fixed layout.
  - Answer Sheet pane: live webcam preview with the framing guide; after a
    capture, show a small "Last capture" thumbnail and timestamp. A clear
    placeholder when the camera is not ready or permission is denied.
  - Review pane: current status, latest tutor message in large text, selected
    section/item and step, capture activity, and the last few tutor messages.
    Never show a fabricated grade.
- Start state: a centered panel with **Start**, the webcam framing instruction,
  and a permission hint. After Start, show the live dashboard and End.
- Reuse `createTutorSession`, `createSessionClient`, `createRecorder`,
  `SpeechSynthesis`, and the webcam camera. Extend the UI interface with
  `setTutorText`, `setExercise`, `addReviewMessage`, `setCameraState`, and
  `setLastCapture`; update `session.ts` to call them.
- Capture a JPEG from the webcam when a response has `capture_request`; upload
  it with `purpose` and `exercise_id` as today. No backend changes.
- End stops the webcam, recorder, and speech, deletes the session, and restores
  the Start panel. Handle start failure and permission denial without a stuck
  loading state.
- Light theme matching the reference; responsive at 1024/768/320 px; safe-area
  insets; `aria-live` for status and tutor text; real buttons with focus.
- No LiveKit, token endpoint, Docker, iPhone page, or continuous frame
  analysis.

## Files

`web/index.html`, `web/src/main.ts`, `web/src/ui.ts` or a new
`web/src/dashboard.ts`, `web/src/styles.css`, `web/src/camera.ts`,
`web/src/session.ts`, `web/src/status.ts`, `web/src/worksheet.ts`,
`web/public/worksheet.png`, and web tests. Do not change the backend, lesson,
calculator, contract, or recorder format.

## Acceptance

- On the laptop at `https://localhost:5173`, Start requests webcam and
  microphone, shows the live preview, and speaks the initial prompt.
- The three panes render and update: question paper, webcam/last capture, and
  review/status/tutor text.
- "Review my worksheet" captures one still; "check my writing" captures a
  fresh still; ordinary speech turns capture nothing.
- End stops the camera/microphone and restores the Start panel.
- No iPhone, LiveKit, Docker, or phone page is required.
- `tsc --noEmit`, `npm test`, and `npm run build` pass.
- A 1080p webcam frame of the printed sheet is sharp enough for the handwriting
  crop; Task 27 repeats the five-minute rehearsal.
- No raw media is stored.

## Dependencies

Tasks 21-26 and 30.

## Estimate

1.5-2 days, then Task 27.

## Controller Rulings (2026-11-12)

- **Webcam only.** No LiveKit, token endpoint, Docker, iPhone page, or network
  camera. The laptop browser owns the camera, microphone, and speaker.
- **Reuse, don't rewrite.** Keep `client.ts`, `recorder.ts`,
  `turnDetector.ts`, `contract.ts`, and the session API contract. Extend the
  `TutorSession` UI interface; do not create a second HTTP client.
- **Fixed sheet.** The dashboard displays `docs/image.png` only. The selected
  item highlight uses normalized boxes matching
  `agent/worksheets/grade3_layout.yaml`; copy them to a small TS module with a
  "keep in sync" comment.
- **No backend changes.** The controller already captures from any
  `TutorCamera`; the webcam is just another implementation. Do not add
  endpoints or store images.
- **Wait states.** Full-sheet vision is ~6 s. Show `Checking the sheet` and a
  disabled-looking but responsive UI; never a blank/frozen screen.
- **Tests.** Add pure tests for the dashboard view state, status/camera
  mapping, worksheet highlight boxes, and webcam capture with fakes. Keep the
  existing session tests green. The implementer runs only `tsc --noEmit`; the
  manager runs `npm test` and `npm run build`.
- **No commit, stage, or move files** by the implementer.
