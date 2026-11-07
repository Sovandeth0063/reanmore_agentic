# PRD: Real-Time AI Math Tutor (MVP)

| Field | Value |
| --- | --- |
| Product | Interactive voice + vision math tutor for young learners |
| Audience | Grade 3 students (about 8-9 years old) |
| Subject | Fixed worksheet-based math demo: addition and making 100 |
| Language | English only |
| Stage | MVP / proof of concept |
| Companion doc | `02-Architecture-ai-math-tutor.md` |

---

## Demo Scope Update (2026-11-07)

This PRD describes the broader MVP. The current five-minute demo is narrower and
supersedes the MVP scope for this build:

- One worksheet (`docs/image.png`), 12 fixed items.
- Camera sees the whole sheet and the student's handwriting.
- Student chooses the exercise by voice.
- No hint ladder; natural step-by-step guidance.
- Handwriting answer checking with low-confidence clarification.
- Hosted vision model by default; audio, STT, and intent stay local.
- Deterministic calculation module for every spoken number.
- Session memory for the chosen exercise, step, and attempts.
- Target latency relaxed to about 2.5 s per turn.
- Two papers, 10-15 exercises, and the hint ladder are deferred.

The rest of this document remains the long-term product context.

---

## 1. Overview

### 1.1 Problem
Young children learning math often get stuck with no one available to guide them in the moment. Existing chatbots are passive: the child must type, describe their problem, and read long answers. That does not work well for an 8-9 year old working on paper.

### 1.2 Solution
A **virtual tutor the child talks to**. The child places a phone or tablet camera anywhere it can see the exercise and their handwriting. The tutor watches and listens, then explains and guides **by voice in real time**, like a person sitting next to them.

### 1.3 Vision
Move from a passive conversational chatbot to an **interactive, real-time AI tutor agent** that tells the student what to write and do next, without overloading or distracting them.

## 2. Goals and Non-Goals

### Goals (MVP)
1. Natural, low-latency, two-way voice conversation between child and tutor.
2. Tutor can see the exercise and handwriting through the camera and react to it.
3. Tutor guides step by step following a defined lesson script, not improvising.
4. All arithmetic the tutor states or checks is correct.
5. A near-empty screen so the child's attention stays on the paper.
6. A live camera preview with microphone and camera tracks published through LiveKit, while AI vision uses low-rate sampled frames.
7. Fixed parts of the tutor's speech come from an approved response catalog; natural guidance is anchored to verified calculation steps.
8. The demo supports one fixed worksheet containing 12 exercises.

### Non-Goals (explicitly out of scope)
- Teacher or parent dashboards and reports
- Student accounts, login, progress tracking over time
- Curriculum ingestion pipeline (RAG); lesson content is placed directly in the prompt
- Dynamic exercise generation or broad curriculum coverage
- Settings, menus, or configuration screens for the student
- Multiple languages, multiple subjects, or content outside Grade 3 math
- Offline mode

## 3. Users and Context

### 3.1 Primary user: the student
- Age 8-9, developing reader, short attention span
- Speaks English, possibly as a second language, possibly with accent
- Works on paper with a pencil; device is a helper, not the focus
- Should be able to complete a session without touching the device after setup
- May interrupt, go silent, talk to siblings, or get frustrated

### 3.2 Helper (secondary, incidental)
- A parent or older sibling may set up the device and position the camera
- No dedicated interface; they use the same single screen

### 3.3 Usage environment
- Home or classroom, variable lighting, background noise
- Phone or tablet on a stand, or propped against an object
- Camera angle and distance vary per session

## 4. User Flow

1. **Set up (adult or helper).** An adult grants permissions and positions the device so the paper is visible.
2. **Start.** The student or adult presses the single Start button. The app captures one worksheet snapshot and the tutor begins speaking.
3. **Check view.** The tutor confirms it can see the worksheet. If not, it asks for an adjustment and automatically captures another setup snapshot.
4. **Exercise loop.**
   - Tutor reads the 12 items and asks which exercise the student would like to start with.
   - Student writes on paper and talks.
   - Student writes an answer and says "I'm done" or "check my answer".
   - The app automatically captures an answer snapshot; no second button is shown.
   - Tutor responds in real time with an approved encouragement, hint, correction, or confirmation.
   - Tutor moves to the next step or exercise when the current one is complete.
5. **Wrap up.** Tutor praises effort, summarizes briefly, and ends the session by voice. An adult can end the session from the setup control.

## 5. Functional Requirements

Priority: **P0** = must have for MVP, **P1** = should have, **P2** = nice to have.

### 5.1 Live Preview and Camera

| ID | Requirement | Priority |
| --- | --- | --- |
| CAM-1 | Show a live camera preview locally, full-screen or near full-screen, before and during the session | P0 |
| CAM-2 | Use the rear camera by default on phones; allow switching only via a hidden or adult-oriented control | P1 |
| CAM-3 | Display a simple framing guide to help place the paper | P1 |
| CAM-4 | Tutor can detect poor framing (paper not visible, too dark, too far) and ask the student to adjust by voice | P0 |
| CAM-5 | Camera permissions requested once with clear, simple wording | P0 |
| CAM-6 | Publish the camera track through LiveKit and sample frames on Start and after the student says "I'm done" or "check my answer"; do not send every frame to the reasoning provider | P0 |

### 5.2 Real-Time Voice Interaction

| ID | Requirement | Priority |
| --- | --- | --- |
| VOI-1 | Full-duplex audio: student can speak while tutor is speaking and the tutor stops (barge-in) | P0 |
| VOI-2 | Voice-to-voice response latency target under about 1.5 seconds in typical conditions | P0 |
| VOI-3 | Tutor voice is warm, clear, and paced slowly enough for a young child | P0 |
| VOI-4 | Tutor handles silence: after a pause, it gently checks in ("Take your time. Do you need a hint?") | P0 |
| VOI-5 | Tutor ignores speech clearly not addressed to it (side conversations, noise) and does not respond to background chatter | P1 |
| VOI-6 | Student can ask the tutor to repeat or slow down at any time | P0 |

### 5.3 Visual Understanding of Work

| ID | Requirement | Priority |
| --- | --- | --- |
| VIS-1 | Tutor reads the printed exercise from event-triggered snapshots of the paper | P0 |
| VIS-2 | Tutor reads the student's handwritten digits and simple working from event-triggered snapshots | P0 |
| VIS-3 | When handwriting is unclear or low confidence, tutor asks ("Is that a 7?") instead of assuming | P0 |
| VIS-4 | Tutor can trigger an automatic answer snapshot after the student says "I'm done" or asks to check the answer, without showing another button | P0 |
| VIS-5 | Tutor never marks an answer wrong based on an uncertain read | P0 |

### 5.4 Math Correctness

| ID | Requirement | Priority |
| --- | --- | --- |
| MATH-1 | A deterministic calculator tool verifies every answer and intermediate step before the tutor confirms or corrects | P0 |
| MATH-2 | The tutor must not state an arithmetic result that was not produced or verified by the tool | P0 |
| MATH-3 | The tool returns not only correct or incorrect but the likely error type (e.g. counting error, missed carry/borrow, wrong operation) to drive guidance | P1 |

### 5.5 Lesson Flow and Pedagogy

| ID | Requirement | Priority |
| --- | --- | --- |
| LES-1 | Tutor follows a structured lesson script: ordered exercises, hints, milestones | P0 |
| LES-1A | Demo contains one fixed worksheet with 12 exercises; no exercise is generated dynamically | P0 |
| LES-2 | Hint ladder is deferred for the current demo; guidance is natural and anchored to verified steps | Deferred |
| LES-3 | Tutor never gives the final answer immediately, even if the student asks "just tell me" | P0 |
| LES-4 | Tutor gives one instruction at a time and waits | P0 |
| LES-5 | Tutor praises effort and specific progress, not just correct answers | P1 |
| LES-6 | Tutor stays on topic and politely redirects off-topic talk | P0 |
| LES-7 | For the same exercise and student state, the tutor's math content is deterministic; phrasing may vary within the persona | P0 |
| LES-8 | Student speech is mapped to a limited intent set (for example: answer, hint, repeat, slow down, or off-topic) before lesson logic runs | P0 |

### 5.6 Interface

| ID | Requirement | Priority |
| --- | --- | --- |
| UI-1 | Single screen with one prominent Start button, local camera preview, and a minimal status indicator; session ending is voice-controlled or adult-controlled | P0 |
| UI-2 | No settings, menus, or text-heavy elements visible to the student | P0 |
| UI-3 | After the single Start press, the student can pause, repeat, request a hint, submit an answer, and end the lesson by voice; no additional buttons are required | P0 |
| UI-4 | Optional on-screen display of the current exercise in large clear text | P1 |

### 5.7 Logging

| ID | Requirement | Priority |
| --- | --- | --- |
| LOG-1 | Save speech transcripts (student and tutor) per session with timestamps | P0 |
| LOG-2 | Log tool calls (calculator inputs and outputs) for debugging | P1 |
| LOG-3 | Raw audio and video are **not stored** by default | P0 |

## 6. Tutor Behavior Specification

### 6.1 Persona
A kind, patient, upbeat helper. Speaks in short, simple sentences. Never sarcastic, never impatient, never scary.

### 6.2 Rules
- Use simple English vocabulary appropriate for Grade 3; adjust examples and pacing to the student's level.
- One step at a time. Then wait.
- Ask before assuming when handwriting or speech is unclear.
- Use the calculator tool for all math checks.
- Guide step by step without a hint ladder in the current demo; never give the final answer first.
- Use only the approved response for the current exercise state and hint level; do not invent new explanations.
- Celebrate effort ("Great try!") and specific wins ("You carried the one, nice!").
- Redirect off-topic requests kindly.
- Do not discuss personal information, and do not ask the child for personal information.

### 6.3 Sample exchange

> **Tutor:** Hi! I'm ready to help with your math. I can see your worksheet. Let's start with 4 plus 5 plus 6. What should we do first?
> **Student:** Add them?
> **Tutor:** Yes. Add the numbers from left to right, then tell me your answer.
> *(Student says 15.)*
> **Tutor:** Great. I'll verify 4 plus 5 plus 6 before we move on.

### 6.4 Lesson script format (content, not code)
Each exercise defines: the problem, the expected answer, the steps, hints at each ladder level, common mistakes with specific responses, and a success message. Example fields: `problem`, `answer`, `steps`, `hints[1..5]`, `common_errors`, `praise`.

## 7. Non-Functional Requirements

| Area | Requirement |
| --- | --- |
| Latency | Voice response begins within about 1.5 s; barge-in stops tutor speech within about 300 ms |
| Reliability | Session survives brief network drops; auto-reconnect; tutor says "I lost you for a second, are you there?" |
| Compatibility | Modern mobile browsers (iOS Safari, Android Chrome) and desktop Chrome |
| Performance | Runs on mid-range phones; low bandwidth tolerant (video resolution adapted) |
| Accessibility | No reading required; clear English audio; voice-first interaction; adult-accessible setup controls |
| Safety | Age-appropriate content only; strict topic guardrails |
| Privacy | See Section 9 |

## 8. Edge Cases

| Situation | Expected behavior |
| --- | --- |
| Student silent for a long time | Gentle check-in, offer hint, offer to repeat |
| Student says "just tell me the answer" | Acknowledge, encourage, give next hint level instead |
| Handwriting unreadable | Ask the student to say or rewrite the number |
| Paper not in frame | Ask student to adjust camera; describe what is wrong simply |
| Poor lighting | Ask student to turn on a light or move closer to a window |
| Background voices or TV | Ignore non-addressed speech; if confusion, ask "Were you talking to me?" |
| Student gets frustrated or upset | Respond with calm encouragement; offer an easier step or a short break |
| Student asks off-topic question | Brief friendly answer or redirect back to math |
| Student leaves the camera view | Detect absence; wait, then check in |
| Network drop | Reconnect, resume from the last exercise state |
| Student writes an unexpected but valid method | Verify with calculator; accept if correct |

## 9. Privacy, Safety, and Compliance

- **Data minimization:** send live audio and camera tracks only for session processing; sample video frames at low rate for AI vision; store transcripts, not raw media.
- **Consent:** a parent or guardian must accept consent before use with children. Define wording and flow before any public pilot.
- **Retention:** define transcript retention period and deletion process.
- **No personal data collection:** no names, addresses, or contact details requested from the child.
- **Content safety:** system-level guardrails keep responses age-appropriate and on math.
- **Third-party processing:** audio and video are sent to the AI provider; review that provider's data-use and children's-data terms before launch.
- **Compliance:** review applicable child-privacy regulations for target markets before deployment beyond internal testing.

## 10. Success Metrics

| Metric | Target (initial) |
| --- | --- |
| Voice response latency (p50 / p95) | under 1.5 s / under 2.5 s |
| Math correctness of tutor statements | 100% on tested exercises |
| Handwriting read accuracy on real child worksheets | Measure baseline; aim for 90%+ on Grade 3 numbers and symbols, with clarification fallback for the rest |
| Session completion rate | 80%+ of started demo sessions reach the end of the fixed 12-exercise sheet |
| "Gave away answer too early" incidents | Zero in scripted test scenarios |
| Camera setup time with adult help | Measure; improve via guide and voice prompts |
| Child engagement | Qualitative observation: stays focused, enjoys the tutor |
| Pilot satisfaction | Positive feedback from testers (parents, teachers) |

## 11. Risks

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Child speech recognition errors | Tutor misunderstands, child frustrated | Test with real children early; confirm unclear inputs |
| Messy handwriting | Wrong feedback | Confidence-based clarification; never mark wrong on uncertain read |
| Variable camera setup | Tutor cannot see work | Framing guide, voice-guided adjustment, test many setups |
| Latency too high | Feels broken to a child | Measure continuously; choose region and architecture accordingly |
| Tutor hallucinates math | Teaches wrong answers | Mandatory calculator tool, strict prompt rules |
| Tutor gives away answers | Defeats learning | Natural guidance anchored to verified steps, scripted tests |
| Privacy concerns with children's data | Legal and trust risk | Minimize storage, consent flow, provider review |
| Child distracted by device | Poor outcomes | Minimal UI, tutor directs attention to paper |

## 12. Milestones

| Milestone | Deliverable | Exit criteria |
| --- | --- | --- |
| M1: Voice demo | Browser to tutor voice conversation | Natural turn-taking, latency under about 1.5 s |
| M2: Camera + vision | LiveKit camera track plus low-rate sampled frames | Reads printed and handwritten digits on sample sheets |
| M3: Fixed worksheet demo | Verified math, one fixed sheet with 12 exercises, response catalog, natural guidance | Passes scripted tests incl. "just tell me the answer" |
| M4: Child testing | Sessions with real Grade 3 children | Demo completed; top issues fixed |

## 13. Open Questions

1. Demo content: finalize the one worksheet file and its 12 fixed exercise records.
2. What device will students use (phone, tablet, laptop), and is a stand available?
3. Who provides English lesson content, and does it need to align to a specific standard?
4. What is the consent and data-retention policy for pilots?
5. What is the acceptable cost per session?
6. Should the exercise also appear on screen, or only on paper?
