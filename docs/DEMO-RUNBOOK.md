# Five-Minute Demo Runbook

## Start the stack

Run these from the repository root, in two terminals:

1. Backend session API: `py -3.10 -m uvicorn server.session_api:app --host 127.0.0.1 --port 8000`
2. Browser client: `cd web && npm install && npm run dev`

The Vite dev server serves HTTPS with a self-signed development certificate and
proxies `/sessions` to the API on `127.0.0.1:8000`. Stop both terminals with
Ctrl+C after the demo.

## Laptop webcam and audio

The laptop is the whole demo: UI, microphone, speaker, and AI. An external
1080p webcam on a stand provides the worksheet image. There is no iPhone, no
LiveKit, and no network camera.

1. Connect the external webcam. Mount it above or beside the sheet so the whole
   printed page and the answer spaces fit inside the framing guide. Use
   autofocus and even lighting; a built-in laptop camera at an angle is the
   fallback, not the target.
2. Start both services as described above.
3. On the laptop, open `https://localhost:5173` and accept the self-signed
   certificate once.
4. Press **Start** and allow **Camera** and **Microphone**.
5. Check the Answer Sheet pane: the live preview should be sharp enough to read
   the printed expressions. Say "review my worksheet" to test the flow.

### If the webcam or page is blocked

- **Camera or microphone denied:** allow them in the browser's site settings,
  then reload. `getUserMedia` needs `https://localhost` (a secure context) and
  a Start tap.
- **No webcam listed:** close other apps that hold the camera, reseat the USB
  cable, and check Windows Camera privacy settings.
- **Blurry or cropped sheet:** move the webcam closer or use a higher-resolution
  camera; keep the whole sheet inside the guide.
- **Tutor voice feeds back into the microphone:** use headphones, lower the
  speaker, or move the laptop away from the child. The recorder enables echo
  cancellation and raises its speech-onset threshold while the tutor speaks.
- **Page slow or frozen:** close other browser tabs and camera apps; the
  full-sheet vision call takes several seconds, so the status should show
  "Checking the sheet" rather than appearing idle.

### Before a full turn

The webcam preview only proves the hardware and UI path. A speech turn or
worksheet check still needs the local providers:

```bash
py -3.10 scripts/check_providers.py
```

It must pass with `OLLAMA_MODEL`, `VISION_MODEL`, and `VISION_API_KEY` set in
`.env`, and with Ollama and the vision provider running.

### Debugging

Use the laptop browser's developer tools for console/network errors and the
backend terminal for request logs. There is no phone or room transport to
debug.

## Before the demo

- Copy `.env.example` to `.env` and fill provider values locally.
- For hosted vision, set `VISION_API` to `openai` (the default) or `gemini`
  and point `VISION_BASE_URL` at that family's base URL. The chosen model must
  accept the demo's images: the OpenAI-compatible path sends `image_url`
  content, the Gemini path sends `inline_data`.
- Run `python scripts/check_providers.py`; resolve every failed check. Add
  `--live` to send `docs/image.png` to the vision provider.
- Print `docs/image.png` clearly on white paper.
- Use a dark marker and even lighting.
- Mount the external webcam on a stand so the full sheet and writing area fit
  inside the framing guide. Confirm the printed expressions are readable in the
  Answer Sheet pane.
- On the laptop, open `https://localhost:5173`, accept the self-signed
  certificate once, and allow webcam and microphone on Start.
- Confirm the laptop microphone and speaker work; use headphones or speaker
  placement to avoid tutor-voice feedback.
- Keep the laptop plugged in and awake; close other camera apps.
- Prepare a backup recording or screenshots.

## Script

1. **0:00-0:45:** Open the dashboard on the laptop, show the sheet in the
   webcam, press Start, and confirm the live Answer Sheet preview. The browser
   sends one review image of the sheet.
2. **0:45-1:30:** Let the tutor review the sheet. If it asks for repositioning,
   adjust once and retry; then listen to the A/B summary (A has addition and
   subtraction, B has multiplication and division) and the choice question.
3. **1:30-2:00:** Choose a pre-tested exercise by voice.
4. **2:00-3:15:** Write while the tutor guides one step at a time.
5. **3:15-3:45:** Say “check my writing.” The laptop captures a fresh image of
   the written work; the tutor locates the selected item, reads only that
   cropped area, and verifies it with the calculator. An uncertain read asks
   for a clearer photo instead of grading.
6. **3:45-4:15:** Show the verified response and praise.
7. **4:15-5:00:** Explain the snapshot session API, laptop webcam, local
   audio/intent, hosted vision, and the deterministic calculator.

## Recovery

- Backend unavailable: the Start button stays available and the browser reports
  that the session could not start. Confirm the API is running on port 8000 and
  the dev server is up, then use the backup recording.
- Worksheet not confirmed: adjust the paper and retry the review. The tutor
  never lists exercises before placement is confirmed.
- Ollama unavailable: use the fixed response catalog and calculator.
- Vision unavailable: use the spoken-only fallback or the backup recording; the
  tutor never claims to have read the paper.
- Unclear handwriting: ask the student to repeat or rewrite; never correct it.
- Reconnect: keep the same session id so the chosen exercise and step resume.

Run at least three complete rehearsals before freezing the demo configuration.

## Vision provider choice

Hosted vision has two implemented adapters: an OpenAI-compatible
`/chat/completions` path (`VISION_API=openai`, the default) and a Gemini
`:generateContent` path (`VISION_API=gemini`). Both keep the key server-side,
label the image from its magic bytes, and return the same structured JSON
contract, so a provider error still ends in a retry or the spoken-only
fallback.

The live demo currently uses **`claude-haiku-5-5`** through the OpenCode Go
OpenAI-compatible route (`billing_source=go`). The Console pay-as-you-go
balance was $0 (HTTP 402), so the Go plan is the working choice. The live
check parses all 12 fixed expressions in about 6 s; `deepseek-v4.1-flash` also
works at 16-22 s, and local `gemma4:e4b` is the no-key fallback at about 23 s.
Task 31's suitability question for non-coding OCR traffic remains open; this is
a working demo choice, not a production approval.

## Selected-work crop accuracy

A written-work check now makes two provider calls: the locator returns the
selected item's box and the sheet's outer corners, the backend rectifies the
photo, validates the box against the fixed twelve-item layout, and sends only
the cropped item area -- label, expression, and answer space -- to the
handwriting reader. A missing, ambiguous, or wrong-item area asks for the sheet
again without reading or grading. The full photo is never stored; the crop is
transient. The Task 30 suite defines these synthetic cases on `docs/image.png`
with drawn A2/B2 marks; the manager records the suite run against this table:

| Case set | Synthetic samples | Clear | Uncertain | Wrong item | False corrections |
| --- | --- | --- | --- | --- | --- |
| Reference sheet, A2 and B2 drawn | 6 | 1 | 1 | 4 | 0 |

The counts are the asserted outcomes (one clear A2 read, one blank crop, and
four refused areas: B2 chosen for A2, an A2 id with a B2 box, a box spanning
both columns, and a collapsed quad), not a measured handwriting accuracy. Real
handwriting calibration, false-correction counts, and laptop webcam photos
belong to Task 27; do not cite an estimate as a measurement.

## Turn timing

Measure the backend on the demo laptop with one local utterance and one
worksheet photo. Run it once before and once after any latency change:

```
py -3.10 scripts/benchmark_turn.py --label before --audio <utterance.pcm> --image <worksheet.jpg> --turns 3
py -3.10 scripts/benchmark_turn.py --label after --audio <utterance.pcm> --image <worksheet.jpg> --turns 3
```

Clear commands ("repeat", "ready", "next", "done", "first step", a review or
writing check, and a complete id such as "A2") skip the local Ollama classifier
and appear as `intent.fast_path`; every other utterance still reaches Ollama.
The browser turn detector is unchanged at 700 ms of silence until Task 27
measures real laptop microphone recordings, so do not tune that window from a
synthetic-only test.

`--audio` is a raw PCM16LE, mono, 16 kHz file; `--image` is a JPEG. The script
times session creation, the requested number of speech turns, a review
snapshot, an exercise choice, and a check snapshot, and prints stage durations
from `tool_calls` plus per-step totals. It prints no audio, images, transcripts,
or student text, and it stops with the normal configuration error when the
providers are not configured.

Record the measured laptop numbers here for Task 27; it measures the full
laptop/webcam interaction. Do not fill in estimates.

| Date | Label | Cold turn total | Warm turn average | Review total | Check total |
| --- | --- | --- | --- | --- | --- |
|  | before |  |  |  |  |
|  | after |  |  |  |  |
