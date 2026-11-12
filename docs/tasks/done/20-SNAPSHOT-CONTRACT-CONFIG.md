# Task 20: Snapshot Session Contract and Configuration

## Goal

Define the shared request/response contract for the snapshot demo and remove
LiveKit as a required setting for the new runtime.

## Evidence

- `agent/config.py` requires `LIVEKIT_URL`, `LIVEKIT_API_KEY`, and
  `LIVEKIT_API_SECRET` for every configured run.
- `server/token_server.py` exposes only `GET /get-token`.
- `web/src/messages.ts` supports LiveKit data messages, not review, retake,
  or check-writing directives.

## Work

- Define one versioned session response shape: `session_id`, `tutor_text`,
  `status`, optional `capture_request` (`review` or `check`), and
  optional selected `exercise_id`. Use the same vocabulary in Python and
  TypeScript.
- Define `POST /sessions`, `POST /sessions/{id}/turn`,
  `POST /sessions/{id}/snapshot`, and `DELETE /sessions/{id}` as the target
  API. State which fields are multipart uploads and which are JSON.
- Separate snapshot-runtime settings from legacy LiveKit settings. Starting
  the new API must not require LiveKit credentials. Keep hosted vision
  credentials server-side.
- Decide and document a bounded audio format Safari can record and the
  server can decode. Keep size, duration, MIME type, and upload limits in the
  shared contract. Reject unsupported formats explicitly.
- Ensure non-secret configuration and response objects can be logged without
  exposing a vision key or raw media.

## Files

`agent/config.py`, a shared Python contract module under `server/`,
`web/src/messages.ts` or a new typed API module, `.env.example`,
`tests/test_config.py`, and contract tests.

## Acceptance

- A fresh snapshot-mode config validates with no LiveKit variables.
- Missing vision configuration fails with variable names only.
- Python and TypeScript use the same statuses and capture directives.
- Contract tests cover valid messages and malformed or unsupported uploads.

## Dependencies

None. This card defines the interface used by Tasks 21-27.

## Estimate

0.5 day.

## Controller Rulings (2026-11-09)

This card defines the interface that Tasks 21-25 consume. The shapes below are
binding; later cards read them from `server/contract.py` and
`web/src/contract.ts` rather than restating them.

- **Ruling: create `server/contract.py`, `web/src/contract.ts`, and
  `tests/test_contract.py`.** The card's "shared Python contract module" and
  "new typed API module" are these paths. Do not edit `web/src/messages.ts`;
  it belongs to the legacy LiveKit path removed by Task 26.
- **Ruling: exact status vocabulary.** `status` is one of `ready`,
  `listening`, `checking_sheet`, `adjust_sheet`, `reading_work`, `speaking`.
  `capture_request` is `review`, `check`, or `null`. Include
  `contract_version: 1` in every session response. `DELETE` returns
  `{contract_version, session_id, ended}`.
- **Ruling: add `server/token_server.py` to the file list.** It must call
  `Settings.from_environment(mode="livekit")`, because the default mode becomes
  `snapshot` and the legacy token endpoint still requires LiveKit. Cost if
  wrong: the legacy endpoint starts with empty credentials.
- **Ruling: `Settings` defaults.** Make `livekit_url`, `livekit_api_key`, and
  `livekit_api_secret` default to `""` so `Settings(...)` fixtures no longer
  need LiveKit values. Keep both key fields `repr=False`. Add
  `public_dict()` that omits all three LiveKit secrets and `vision_api_key`.
- **Ruling: mode selection.** `from_environment(*, require_secrets=True,
  mode=None)`. `mode` defaults to `TUTOR_RUNTIME` or `"snapshot"`. Reject any
  mode outside `{"snapshot", "livekit"}` naming `TUTOR_RUNTIME` only. In
  `snapshot` mode, missing `OLLAMA_MODEL` / vision variables fail; LiveKit
  variables are never required. In `livekit` mode add the three LiveKit
  variables to the required list.
- **Ruling: audio is raw PCM16LE, not a container.** Constants:
  `AUDIO_SAMPLE_RATE = 16000`, `AUDIO_CHANNELS = 1`, `AUDIO_SAMPLE_WIDTH = 2`,
  `MAX_AUDIO_SECONDS = 15`, `MAX_AUDIO_BYTES = 480000`. Accept `audio/l16`,
  `audio/pcm`, `audio/x-pcm` with optional parameters; reject everything else
  explicitly. Reject empty, odd-length, and over-limit payloads.
- **Ruling: images.** `MAX_IMAGE_BYTES = 4 * 1024 * 1024`; JPEG only
  (`image/jpeg`, `image/jpg`) and magic bytes `FF D8 FF`. `purpose` is exactly
  `review` or `check`.
- **Ruling: error payload.** `ContractError(code, message, status_code)` and
  `error_payload(error)` produce `{"error": {"code", "message"}}`. Codes:
  `invalid_session`, `invalid_request`, `unsupported_audio_format`,
  `unsupported_image_format`, `payload_too_large`, `audio_too_long`,
  `empty_audio`, `wrong_purpose`, `not_allowed_in_state`,
  `provider_unavailable`. No provider text, key, or media in the message.
- **Ruling: TypeScript parity is tested.** `tests/test_contract.py` reads
  `web/src/contract.ts` and asserts every Python status and capture value is
  declared there, and that `CONTRACT_VERSION` is 1 in both. Use string values
  in the TS union so the test is a simple text check.
- **Ruling: `.env.example`.** Add `TUTOR_RUNTIME=snapshot`. Label the LiveKit
  block as legacy/optional and do not remove it (Task 26 removes the runtime).
- **Ruling: do not integrate the contract into tutor/vision yet.** Task 20 only
  defines and validates it. Task 21 wires it into the API; Tasks 23-25 change
  the vision/tutor payloads.
- **Ruling: tests.** Write `tests/test_contract.py` plus the snapshot-mode
  cases in `tests/test_config.py`. Cover: snapshot config without LiveKit,
  livekit config still requiring LiveKit, missing vision names only,
  `public_dict`/`repr` redaction, invalid mode, valid `SessionResponse`, valid
  and malformed/oversized/unsupported audio, valid and malformed/oversized
  images, wrong purpose, and an error payload with no secret.
- **Ruling: no pytest.** Run only `python -m py_compile` on touched Python
  files. Return status, files, compile results, acceptance status, and
  concerns. Do not commit, stage, or move the card. The manager verifies with
  `python -m pytest tests/test_config.py tests/test_contract.py -q`.

## Completion Evidence (2026-11-09)

- Files: `agent/config.py`, `server/contract.py`, `server/token_server.py`,
  `web/src/contract.ts`, `.env.example`, `tests/test_config.py`,
  `tests/test_contract.py`.
- Verified: `python -m pytest tests/test_config.py tests/test_contract.py -q
  -p no:cacheprovider` -> **50 passed, 13 subtests passed**. `node
  node_modules/typescript/bin/tsc --noEmit` in `web/` -> **exit 0**.
  `python -m py_compile` on every touched Python file -> **exit 0**.
- Written but not run: none; the contract and configuration suites were run.
- Deferred/manual: a real `.env` provider validation and the legacy LiveKit
  token path; no provider or service was started.
- Concerns:
  - `public_dict()` omits `livekit_url` as well as the three credentials. The
    legacy endpoint is not a secret, but hiding it is safe and keeps the log
    payload small.
  - Legacy callers outside this card (`agent/main.py`,
    `scripts/check_providers.py`) now default to snapshot mode and no longer
    require LiveKit. Task 26 replaces that path; the worker itself does not read
    `settings.livekit_*`.
  - Odd-length audio reports `invalid_request`; oversized audio reports
    `audio_too_long`; oversized images report `payload_too_large`. All three are
    413/400 client errors and none echo media.
