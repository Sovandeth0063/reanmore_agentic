# Task 26: Remove Legacy LiveKit Runtime from the Snapshot Demo

## Goal

Make the snapshot API the sole documented demo path and remove unused
LiveKit-specific startup, configuration, and browser dependencies.

## Evidence

`agent/main.py`, `server/token_server.py`, `web/src/room.ts`,
`requirements.txt`, `web/package.json`, `infra/`, `README.md`, and
`docs/DEMO-RUNBOOK.md` describe the old room-based runtime. Keeping both
paths as active demo instructions would make setup and testing ambiguous.

## Work

- Retire the LiveKit worker/token endpoint from the active app after the new
  end-to-end path passes. Remove unused SDK packages and settings, or isolate
  legacy code clearly outside the demo runtime if retention is needed.
- Update `README.md`, `.env.example`, `docs/DEMO-RUNBOOK.md`,
  `scripts/check_providers.py`, and `docs/tasks/00-DEMO-SPEC.md` to match
  snapshot uploads and short speech turns.
- Replace the four-terminal LiveKit run command with the actual API and web
  startup commands. Keep secure-context and iPhone camera guidance.
- Preserve the fixed worksheet and calculator invariants. Do not present
  provider/device checks as completed until they have been run.

## Files

Legacy entrypoints, dependency manifests, setup files, README, demo spec,
provider checker, and runbook.

## Acceptance

- A fresh install and startup following the README does not require LiveKit.
- No active UI or API path publishes a camera or microphone track to a room.
- The runbook matches the new code and five-minute single-exercise script.
- Package builds and Python imports succeed after dependency cleanup.

## Dependencies

Tasks 21-25.

## Estimate

0.75 day.

## Controller Rulings (2026-11-10)

- **Ruling: delete, do not isolate.** Delete `agent/main.py`,
  `agent/snapshots.py`, `server/token_server.py`, `web/src/room.ts`,
  `web/src/messages.ts`, the whole `infra/` directory, and
  `tests/test_main.py`, `tests/test_pipeline.py`, `tests/test_token_server.py`.
  No compatibility shim and no legacy folder. `server/session_api.py` and
  `agent/controller.py` are the only runtime.
- **Ruling: remove the dead VAD layer.** `index.html`/`web/src/main.ts` and
  the server never use `SpeechSegmenter` or `SileroVad`; the browser turn
  detector owns speech boundaries. Delete both classes from `agent/stt.py`,
  keep `STTError`, `Transcript`, `decode_pcm16le`, and `Transcriber`, and
  delete the VAD/segmenter tests from `tests/test_stt.py` (keep the PCM and
  transcriber tests).
- **Ruling: config cleanup.** In `agent/config.py` remove `RUNTIME_MODES`,
  `TUTOR_RUNTIME`, the `mode` argument, all `livekit_*` fields, and their
  validation. `Settings.from_environment(require_secrets=...)` has no mode.
  `PRIVATE_SETTING_FIELDS = ("vision_api_key",)`. Rewrite
  `tests/test_config.py`: keep snapshot vision validation, missing-variable
  naming, `repr`/`public_dict` redaction, and `DB_URL`; delete every
  LiveKit/livekit-mode test; add a test that `LIVEKIT_*` env vars are ignored
  and never appear in `public_dict`. Drop the `livekit_*` kwargs from every
  `Settings(...)` construction in the tests.
- **Ruling: dependencies.** `requirements.txt` drops `livekit-agents`,
  `livekit-api`, and `silero-vad`; keep FastAPI, faster-whisper, httpx,
  PyYAML, python-dotenv, python-multipart, and uvicorn. `web/package.json`
  drops `livekit-client`; leave `package-lock.json` for the next
  `npm install` to refresh. `vite.config.ts` drops the `/get-token` proxy and
  keeps `/sessions`.
- **Ruling: tests that used the legacy runtime.** Remove the `TutorRuntime`
  import and its test from `tests/test_tutor.py`; direct tutor coverage in
  `test_check_uses_guidance_step` and the controller coverage in
  `tests/test_conversation.py` replace it. Rewrite
  `tests/test_lesson_flow.py::test_next_done_and_list_intents` with direct
  tutor calls (or a placed controller) and remove the `agent.main` import.
  No test may import a deleted module.
- **Ruling: active docs.** Update `.env.example` (no `TUTOR_RUNTIME`, no
  LiveKit block), `README.md`, `docs/DEMO-RUNBOOK.md`, and
  `docs/tasks/00-DEMO-SPEC.md` to the snapshot path. The runbook and README
  startup is two terminals: `uvicorn server.session_api:app --host 0.0.0.0
  --port 8000` from the repository root and `cd web && npm install &&
  npm run dev`. Keep the HTTPS/self-signed-certificate and iPhone camera
  guidance. Replace "joins LiveKit / publishes tracks" with the review
  request, placement retry, A/B summary, and fresh written-work capture.
  Replace "Silero VAD" with the browser turn detector. Remove LiveKit from
  the environment-variable lists, layout, risks, and recovery steps; use the
  backend-unavailable fallback instead. In `00-DEMO-SPEC.md`, update the
  scope note to "Tasks 20-26 implemented, 27-31 follow-ups" and remove the
  stale "current repository still implements LiveKit" and track-publishing
  claims, while leaving older historical sections labelled as history.
- **Ruling: provider checker and skills.** `scripts/check_providers.py`
  drops `_check_livekit`, the `socket` import, the LiveKit check, and the
  Silero import check; keep Ollama, faster-whisper import, vision
  configuration, and `--live`. Update `.agent/verify-providers/SKILL.md` and
  the token/room row in `.agent/demo-invariants/SKILL.md` to the snapshot API.
  Do not rewrite historical `docs/tasks/done/` cards.
- **Ruling: no pytest.** Run only `python -m py_compile` on touched Python
  files. Return status, files, compile results, acceptance status, and
  concerns. Do not commit, stage, or move files. The manager runs the whole
  suite, `tsc --noEmit`, `npm test`, `npm run build`, and a grep proving no
  active path imports `livekit`.

## Completion Evidence (2026-11-10)

- Deleted: `agent/main.py`, `agent/snapshots.py`, `server/token_server.py`,
  `web/src/room.ts`, `web/src/messages.ts`, `infra/`, `tests/test_main.py`,
  `tests/test_pipeline.py`, `tests/test_token_server.py`.
- Changed: `agent/config.py` (no runtime mode or LiveKit fields),
  `agent/stt.py` (no Silero VAD or segmenter), `requirements.txt`,
  `web/package.json`, `web/package-lock.json` (refreshed; LiveKit removed),
  `web/vite.config.ts`, `.env.example`, `scripts/check_providers.py`;
  `tests/test_config.py`, `test_stt.py`, `test_tutor.py`,
  `test_lesson_flow.py`, `test_handwriting.py`, `test_vision.py`,
  `test_conversation.py`, `test_llm.py`; `README.md`,
  `docs/DEMO-RUNBOOK.md`, `docs/tasks/00-DEMO-SPEC.md`;
  `.agent/verify-providers/SKILL.md`, `.agent/demo-invariants/SKILL.md`,
  `.agent/implement-task-card/SKILL.md` (module-boundary block only),
  `.agent/docs/README.md`.
- Verified: `python -m pytest tests -q -p no:cacheprovider` -> **241 passed,
  538 subtests passed**; the previous LiveKit/`ssl` failure is gone with the
  deleted token test. `python -m py_compile` on every touched Python file ->
  **exit 0**. `import server.session_api, agent.config, agent.controller,
  agent.stt, scripts.check_providers` -> **ok**. `node
  node_modules/typescript/bin/tsc --noEmit` -> **exit 0**; `npm test` ->
  **40 passed**; `npm run build` -> **13 modules transformed, built in 106 ms**
  (esbuild ran; the earlier `spawn EPERM` no longer occurs). A grep of
  `agent/`, `server/`, `web/src/`, `web/index.html`, `scripts/`, and
  `web/vite.config.ts` for LiveKit, `/get-token`, Silero, or the deleted
  classes -> **no matches**. `python scripts/check_providers.py` -> reports
  missing provider configuration, as expected without a real `.env`.
- Manager fixes during review: the README architecture-status and test-status
  rows now match the snapshot path; the runbook's vision recovery no longer
  refers to a parsed exercise list. `npm install` was run to refresh
  `package-lock.json` so a fresh install no longer carries `livekit-client`.
- Written but not run: none; the Python and web suites and the web build were
  run.
- Deferred/manual: a clean-machine install, a real `.env` provider run, and
  iPhone/Safari verification (Task 27).
- Concerns:
  - `docs/architecture/` and historical cards still describe LiveKit; they are
    labelled history and were outside this card.
  - `tests/test_session_api.py` still greps for absence of LiveKit imports;
    those are negative assertions, not dependencies.
  - `web/dist/` was rebuilt locally and is gitignored; a stale prebuilt bundle
    must not be deployed.
  - `silero-vad` was removed from requirements; the browser turn detector is
    the only speech-boundary implementation now.
