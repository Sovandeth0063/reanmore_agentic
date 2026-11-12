# UI Brief: Laptop Tutor Dashboard with Webcam

This file previously described a student-facing phone UI. The 2026-11-12
direction moves the screen to the **laptop**: the child speaks to the laptop,
an external webcam shows the worksheet, and the laptop displays a three-pane
tutor console. The iPhone and LiveKit are no longer part of the demo.

## Screen

- The laptop opens `https://localhost:5173`; one **Start** button, then one
  discreet **End** action for the adult helper.
- A light, neutral dashboard with three columns under a slim header:
  - **Question Paper:** the fixed `docs/image.png` at readable scale. Outline
    the selected exercise when one is chosen.
  - **Answer Sheet:** the live webcam preview with a framing guide. Show the
    last captured still and its time after a review or check.
  - **Review:** the current status, the latest tutor message, the selected
    section/item and step, and the last few tutor messages.
- The webcam preview is local. Only requested still images are uploaded.
- The laptop microphone and speaker carry the conversation.
- Keep the text readable for an adult helper; the child follows the tutor by
  speech.

## Interaction states

| State | What the student hears | What the laptop shows |
| --- | --- | --- |
| Ready | "Ask me to review your worksheet." | Start panel, camera placeholders, framing hint |
| Camera blocked | Permission/setup guidance | "Camera blocked" pill and a retry instruction |
| Sheet missing or unclear | "Please place the whole sheet..." | Live preview, adjustment status |
| Sheet confirmed | A/B operation summary, then "Which section and number?" | Question Paper and a brief summary |
| Exercise chosen | The chosen problem and first step | Selected item outlined, Review message |
| Checking writing | "Let me look at your answer." | Last capture thumbnail, reading status |
| Read uncertain | Clarification question | Clarification message, no grade |
| Answer checked | Calculator-verified praise or guidance | Verified feedback in Review |
| Ended | "You worked hard today..." | Start panel restored, camera stopped |

The browser captures a frame when the student requests review, says "Ready"
after a placement prompt, or asks to check written work. Ordinary spoken
questions do not capture. A poor image produces a specific adjustment.

## Data needed by the UI

```json
{
  "status": "ready | listening | checking_sheet | adjust_sheet | reading_work | speaking",
  "tutor_text": "Which section and number would you like to start with?",
  "capture_request": null,
  "exercise_id": null
}
```

For a requested capture, `capture_request` identifies `review` or `check`. The
laptop sends the image with the session id and, for a check, the chosen
exercise id. The backend decides whether the read is ready, uncertain, or
needs a retake.

## Layout and accessibility

- Three columns at 1024 px and wider; stack Question Paper, Answer Sheet, then
  Review below that. The Start panel stays usable at 320 px.
- Use `aria-live="polite"` for the status and tutor message. Buttons are real
  `<button>` elements with visible focus. Do not rely on color alone for
  camera or read state.
- Respect `100dvh`, safe-area insets, and the laptop viewport; do not let the
  webcam feed push the controls off-screen.
- The Answer Sheet pane should show a clear placeholder when the webcam is not
  ready; never a black rectangle with no explanation.

## Acceptance checklist

- [ ] Start enables the webcam and microphone and shows the live preview.
- [ ] A review request captures one still from the webcam.
- [ ] Missing or cut-off paper gets a spoken placement prompt and a retry.
- [ ] A readable sheet gets a short operation summary and choice question.
- [ ] Choosing an exercise by voice works without another image.
- [ ] Spoken back-and-forth works without camera uploads.
- [ ] Checking written work captures a fresh still of the selected exercise.
- [ ] Uncertain handwriting gets clarification, not an incorrect mark.
- [ ] End stops the camera and microphone and restores the Start panel.
- [ ] The complete one-exercise flow fits the five-minute presentation.
