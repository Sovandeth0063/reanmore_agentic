# Task 27: Snapshot Flow Integration Tests and Laptop Webcam Rehearsal

## Goal

Prove the complete one-worksheet flow works in code and on the demo laptop with
the external webcam before calling it demo-ready.

## Evidence

The API, controller, tutor, vision, and memory suites cover their pieces, but
there is no single end-to-end test for the five-minute script. The laptop
dashboard and webcam UI are Task 32. The earlier phone/LiveKit rehearsal path is
obsolete; the demo now runs entirely on the laptop.

## Work

- Add an integration test with fake STT, intent, vision, and calculator
  boundaries: create session -> review request -> blank photo -> placement
  prompt -> clear photo -> summary -> A2 choice -> spoken step -> written
  check -> feedback -> end.
- Test event counts: one image per review/retake/check; zero during ordinary
  conversation. Test uncertainty, provider failure, timeout, retry, session
  expiry, and a session ended mid-flow.
- Run the Python suite and web build. Resolve or document any remaining
  environmental failures without weakening assertions.
- On the laptop, rehearse the real webcam, microphone, browser speech, vision
  provider, and handwriting read with the printed blank sheet. First capture
  baseline stage timings, including cold-start and warm turns.
- Run the five-minute script three times on the final configuration, including
  one placement recovery and one uncertain-read recovery. Record actual timings
  and the fallback procedure in the runbook.
- Do not mark this card done from mocks alone.

## Files

Integration tests, `docs/DEMO-RUNBOOK.md`, `docs/tasks/TASK-REPORT.md`, and
small fixes to failing code paths found by the tests.

## Acceptance

- Automated flow tests, `tsc --noEmit`, `npm test`, and `npm run build` pass.
- Three complete laptop rehearsals finish in five minutes each.
- Each rehearsal shows a placement recovery or an uncertain-read recovery, a
  valid chosen exercise, a fresh written-work image, and verified feedback.
- The runbook includes actual timings, the webcam setup, and a backup recording
  plan.
- No iPhone, LiveKit, Docker, or phone page is required.

## Dependencies

Tasks 21-26 and Task 32.

## Estimate

1 day plus access to the laptop webcam and configured providers.
