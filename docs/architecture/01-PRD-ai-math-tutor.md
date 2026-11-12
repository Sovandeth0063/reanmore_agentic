# PRD: Laptop Webcam Worksheet Tutor Demo

| Field | Decision |
| --- | --- |
| Audience | Grade 3 student, with an adult setting up the laptop and webcam |
| Demo length | Five minutes |
| Worksheet | One fixed printed sheet: `docs/image.png`, items A1-A6 and B1-B6 |
| Interaction | Spoken turns; still images captured only when the paper needs interpreting |
| Devices | Laptop for UI, microphone, speaker, and AI; external 1080p webcam for the sheet |
| Status | Snapshot API and tutor backend implemented; laptop dashboard is Task 32; no iPhone or LiveKit |

## Purpose

The student asks the tutor to review a worksheet. The tutor first establishes
that the paper is visible, summarizes its exercise types, asks where the student
wants to start, and explains that exercise through a spoken conversation. It
takes another photo when the student wants feedback on written work. The tutor
does not claim to see writing between photos.

The laptop is the whole experience. The child speaks to it, hears it, and
watches the three-pane console. The webcam sits on a stand and provides the
worksheet image; it does no processing.

## Five-minute demo outcome

Show one complete interaction with the fixed sheet: placement recovery if
needed, sheet summary, unambiguous exercise choice, short explanation, one
written-answer check, and feedback grounded in deterministic arithmetic. The
12 items are available for choice; completing all 12 is not a five-minute goal.

## Student journey

1. An adult connects the external webcam on a stand, opens the laptop app, and
   presses **Start**. The browser grants webcam and microphone access and shows
   the live Answer Sheet preview with a framing guide.
2. The student says, "Review my worksheet." The laptop captures one still image
   and sends it for inspection. There is no continuous image upload.
3. If the sheet is missing, cut off, too dark, or too small to read, the tutor
   asks the student to place or adjust it in the webcam view. The student says
   "Ready" and the laptop takes a new still image. No exercise is inferred from
   a failed image.
4. Once the sheet is readable, the tutor gives a short summary: section A has
   addition and subtraction; section B has multiplication and division.
5. The tutor asks where to start. The student says a section and item, such as
   "A2" or "section A, number two." "Number two" alone is ambiguous because
   both sections have one; the tutor asks which section.
6. The tutor names that exercise and explains one step at a time. The student
   can ask questions, repeat a step, or give a spoken answer. Speech turns do
   not cause camera captures.
7. When the student asks to check written work, the laptop takes a **fresh
   still image**. The tutor reads only the selected exercise's answer area,
   verifies the answer with the calculator, then praises or guides. If the
   handwriting is uncertain, it asks the student to say or rewrite the answer
   and does not mark it wrong.
8. The student may choose another item or finish with **End**. The five-minute
   script wraps after one completed item.

## Requirements

| ID | Requirement | Demo priority |
| --- | --- | --- |
| R1 | One Start control on the laptop enables the webcam preview, microphone, and spoken interaction. No student-facing settings. | Must |
| R2 | Capture a still image on a review request and on an explicit written-work check or retry. Do not send continuous video. | Must |
| R3 | Detect missing, incomplete, or unreadable paper and ask for repositioning before summarizing. | Must |
| R4 | Summarize the visible operation types briefly, then ask for an exercise choice. | Must |
| R5 | Resolve choices to A1-A6 or B1-B6; ask for the section when a number is ambiguous. | Must |
| R6 | Use the fixed lesson record for the chosen problem and verified step data for explanations. | Must |
| R7 | Use OCR/vision to confirm the sheet and read handwriting; never treat OCR as the source of arithmetic truth. | Must |
| R8 | Ask for clarification on uncertain or mismatched handwriting; never mark an uncertain read wrong. | Must |
| R9 | Check each answer and every arithmetic result stated in feedback with the deterministic calculator. | Must |
| R10 | Keep the chosen item, step, and recent turns for the current session. | Must |
| R11 | Speak short, warm English sentences and wait for the student's reply after each step. | Must |
| R12 | Avoid storing raw images and audio by default; define session-data retention before any pilot with children. | Must |
| R13 | The laptop dashboard shows the question paper, live webcam, and tutor review in one screen. | Must |
| R14 | End stops camera, microphone, and speech, ends the session, and restores the Start state. | Must |

## Snapshot policy

- The preview stays on the laptop. It is for positioning, not AI analysis.
- Initial review: capture once; retry only after the student indicates the
  camera or paper has been adjusted.
- Written-work check: capture a new image even if the student also says a
  number. If the student asks to check only a spoken answer, the tutor can
  verify the number but must not claim it read the writing.
- No image is needed for exercise selection, explanation, repetition, or
  ordinary spoken questions.
- The vision result records visibility, worksheet match, extracted text,
  answer location when available, and uncertainty. An unsupported confidence
  number alone is not proof that a read is correct.

## Teaching and safety rules

- Do not reveal the final answer before the student has tried a step.
- Explain one step at a time, using the fixed exercise and calculator output.
- Accept a different valid method when the arithmetic verifies.
- If OCR and the known sheet disagree, ask for a clearer photo; do not silently
  switch to another exercise.
- Keep the conversation on the worksheet. Do not request personal details.
- Use an unfilled copy of the sheet for the demo: it has Name, Date, Score, and
  signature fields that should not contain a child's personal data.

## Out of scope for this demo

iPhone or phone-camera capture, LiveKit/media rooms, continuous frame
interpretation, general worksheets or diagrams, completing all 12 items,
automatic class grading, teacher/student accounts, hint ladders, rich formula
rendering, native apps, and production deployment.

## Demo acceptance

The demo is ready when the laptop completes the journey above three times in a
row within five minutes, including one low-confidence or poor-framing recovery.
Measure actual time to first spoken response and time for each snapshot result
on the demo laptop. The previous 2.5-second target is not a proven guarantee for
hosted OCR and should not be presented as one.

## Related documents

- [Detailed architecture](02-Architecture-ai-math-tutor.md)
- [Stack overview](03-Tech-Stack-and-Architecture-Links.md)
- [Laptop UI brief](ui-brief-snapshot-review.md)
- [Webcam dashboard design](../superpowers/specs/2026-11-12-laptop-dashboard-webcam-design.md)
- [Demo runbook](../DEMO-RUNBOOK.md)
