# Laptop Dashboard with Local Webcam

Date: 2026-11-12
Status: approved

## Intent

Move the entire demo experience to the **laptop**:

- The laptop shows a three-pane console: fixed question paper, live answer
  sheet, and tutor review.
- The child speaks to the laptop. The laptop microphone, speaker, and voice
  UI run the tutor.
- An external webcam connected to the laptop is the only camera. It shows the
  printed worksheet and the child's handwriting.
- The iPhone is no longer part of the demo. LiveKit is not used.

This supersedes the earlier student-facing phone UI and the short-lived
phone-camera/LiveKit design. The existing HTTP tutor session, lesson,
calculator, placement gate, and response rules do not change.

## User Flow

1. The adult connects an external webcam on a stand, opens the laptop app at
   `https://localhost:5173`, accepts the dev certificate once, and presses
   **Start**.
2. The browser asks for webcam and microphone permission. The Answer Sheet
   pane shows the live webcam preview with a framing guide.
3. The child says "review my worksheet." The laptop captures one JPEG from the
   webcam and uploads it to the existing snapshot endpoint.
4. The tutor confirms placement, summarizes sections A/B, and asks for an
   exercise. The child speaks; the laptop records short PCM turns and uploads
   them to the existing turn endpoint.
5. On "check my writing," the laptop captures a fresh JPEG from the same
   webcam. The existing vision/crop/calculator path reads the selected answer.
6. The laptop speaks every tutor response through `SpeechSynthesis` and updates
   the Review pane. **End** stops the camera/microphone, ends the session, and
   resets the interface.

## Goals

- Laptop dashboard with the reference layout: question paper, live answer
  sheet, review/feedback.
- Local webcam capture and laptop microphone/speaker, reusing `createCamera`,
  `captureVideoFrame`, `createRecorder`, `createTutorSession`, and the existing
  API client.
- Fixed-sheet demo only: the 12 items in `docs/image.png`, verified against the
  lesson.
- Event-driven still captures; no continuous frame analysis and no stored
  media.
- A working five-minute flow in three days.

## Non-Goals

- iPhone camera, LiveKit, WebRTC, token endpoints, Docker, or a phone page.
- General worksheets, diagrams, or automatic exercise detection outside the
  fixed sheet.
- Rich formula rendering/animation. The Question Paper image plus text
  explanations and a selected-item highlight are enough.
- Teacher accounts, per-question grading cards, or class dashboards.
- Native apps, production TLS, or multi-class operation.

## Approaches Considered

1. **Local webcam on the laptop (chosen).** The browser owns the camera, voice,
   and UI. No network media path and no third-party camera app. Trade-off: the
   laptop must sit near the child and the webcam must be mounted and focused.
2. **iPhone camera over LiveKit.** Rejected for the three-day window: Docker
   media/UDP, WSS proxy, token grants, a second browser page, and iPhone
   permission/wake-lock handling add 1-1.5 days of risk for no demo benefit.
3. **iPhone as a virtual webcam (Camo/EpocCam).** Rejected: third-party
   dependency, macOS-oriented, and still requires phone setup.
4. **Phone uploads stills only.** A fallback if the webcam is unusable; keeps
   the dashboard but loses the live preview and adds a phone page.

## Architecture

```text
Laptop browser
  webcam --getUserMedia--> live <video> --canvas JPEG--> POST /sessions/{id}/snapshot
  microphone --PCM16LE turn--> POST /sessions/{id}/turn
  SpeechSynthesis <-- tutor_text
  dashboard <-- SessionResponse
        |
        v
FastAPI session API -> controller -> STT / intent / vision / tutor / calculator / memory
```

- No backend changes. The existing `server/session_api.py` and
  `agent/controller.py` receive the same JPEG and PCM payloads.
- `web/src/camera.ts` starts the webcam (`width: 1920`, `height: 1080`,
  `facingMode` removed/ignored) and captures JPEGs.
- `web/src/session.ts` remains the orchestrator. Its injectable
  camera/recorder/speech/UI interfaces let the dashboard reuse it.
- The laptop's own microphone records turns; `SpeechSynthesis` speaks on the
  laptop.
- The question paper is served from `web/public/worksheet.png` (a copy of
  `docs/image.png`). No student media is stored.

## UI Design

Light, neutral surface so the worksheet leads. Three columns under a slim
header:

- **Header:** title, session status pill, camera status
  (`Camera ready` / `Camera blocked`), and a discreet **End** action.
- **Question Paper:** the fixed sheet at readable scale; the selected exercise
  is outlined using the fixed layout. Scroll/zoom if the pane is short.
- **Answer Sheet:** live webcam preview with the framing guide; a "Last
  capture" thumbnail and timestamp after a capture; a clear placeholder if the
  camera is not ready.
- **Review:** current status, latest tutor message in large text, selected
  section/item and step, capture activity, and the last few tutor messages.
  Never show a fabricated grade; uncertain reads show the clarification text.

Start state: a centered panel with **Start**, a short "place the whole sheet in
the webcam view" instruction, and a camera-permission hint. After Start, the
header shows End and the live status.

Responsive: three columns at >= 1024 px; stack below that. Keep text readable
at 320 px for the fallback view.

## Device Setup

- External 1080p webcam on a stand above/beside the sheet, autofocus, decent
  low light. Built-in laptop cameras are the fallback, not the target.
- Laptop within cable length; USB extension if needed.
- Laptop microphone and speaker. Use headphones or speaker placement to reduce
  tutor-voice feedback into the microphone; the recorder already enables echo
  cancellation and raises its speech-onset threshold while the tutor speaks.
- The sheet is printed blank (no child name/signature) and fills most of the
  webcam frame.

## Decisions

- Webcam only; iPhone/LiveKit removed from the active demo.
- Laptop microphone and speaker.
- Light dashboard, phone no longer has a UI.
- Fixed room/sheet model dropped with LiveKit; the fixed 12-item sheet remains.
- Reuse the existing session orchestrator and API; no backend rewrite.
- 3-day slice: Day 1 dashboard/camera; Day 2 voice/capture/review; Day 3
  handwriting flow, polish, rehearsal.

## Risks

1. **Webcam resolution and framing.** A 720p or badly angled webcam may not
   give a readable handwriting crop. Test a real frame before polishing the UI;
   use an external 1080p camera on a stand.
2. **Audio feedback.** The laptop speaker can enter the microphone; keep echo
   cancellation, use headphones, or place the speaker away from the child.
3. **Permission/secure context.** `https://localhost:5173` is a secure context;
   accept the self-signed certificate once. Camera/mic prompts need a user
   gesture on Start.
4. **Latency.** Full-sheet vision is ~6 s with Claude Haiku; the UI must show a
   clear "Checking the sheet" state rather than appearing frozen.
5. **Scope creep.** Continuous frame analysis, general worksheets, and rich
   formula rendering are out.

## Testing and Acceptance

- `tsc --noEmit`, `npm test`, and `npm run build` pass.
- Dashboard state/render helpers and webcam capture are unit-tested with fakes.
- Manual: on the laptop, Start → webcam/mic permission → review → placement →
  A2 → spoken step → check writing → feedback → End.
- One 1080p webcam frame of the printed sheet yields a readable handwriting
  crop; Task 27 repeats the five-minute script three times.
- No iPhone, LiveKit, Docker, token endpoint, or phone page is required.
- No raw media is stored.

## Approval

Approved by the human partner on 2026-11-12: webcam-only laptop dashboard,
iPhone/LiveKit removed, three-day scope.
