# Task 31: Compare Gemini for Worksheet and Handwriting Vision

## Goal

Decide from real evidence whether Gemini improves the hosted vision stage for
the fixed worksheet, and whether the available OpenCode plan is suitable for
this application.

## Evidence

`agent/vision.py` currently sends an OpenAI Chat Completions image request to
`VISION_BASE_URL`. `.env.example` mentions the OpenCode pay-as-you-go base URL.
OpenCode documents Gemini in Go and a separate Go base URL, but describes Go
as intended for coding-agent traffic. The repo has no live Gemini image test
or comparative OCR results.

## Work

- Check the current OpenCode plan and provider documentation, or obtain a
  provider answer, for use of Go with this tutor's image/OCR traffic. Record
  the applicable endpoint, model ID, image input support, limits, and data
  handling. Do not assume that a text-model API translation supports images.
- If the plan permits it, add a small provider adapter for the documented
  Gemini image endpoint. Preserve structured parsing, bounded errors, and
  the existing vision contract. Keep credentials server-side.
- Start with `docs/image.png` and synthetic or adult-written cases. Run the
  same sanitized cases through the current hosted provider and Gemini; record
  accuracy, uncertainty, latency, failures, and request usage. Repeat with
  real phone photos in Task 27 if Gemini is selected. Do not send real student
  media until the plan and data handling are confirmed.
- Choose the provider based on the measured result. Keep the existing
  provider as the default until Gemini has passed the full phone rehearsal.

## Files

Provider adapter/configuration if justified, `agent/vision.py`, provider
tests, `.env.example`, and a short comparison in the demo runbook.

## Acceptance

- Plan suitability and image-request support are confirmed from current
  provider documentation or a provider response.
- Both providers are compared on the same labeled cases with sample count,
  latency, false-correction count, and uncertainty rate reported.
- Provider errors still yield a retry or spoken-only fallback. If Gemini is
  selected for the demo, Task 27 later verifies it on the phone before the
  provider switch is considered complete.
- No API key or student image is committed or logged.

## Dependencies

None for provider research or an isolated adapter. Compare against the
existing hosted provider when both are configured. Real-device acceptance is
part of Task 27 if Gemini is selected; this evaluation does not block Task 27
with the existing hosted provider.

## Estimate

0.75-1.5 days, depending on API compatibility and provider confirmation.

## Provider Research (2026-11-11)

- **Plan/model availability.** The current `opencode-go` provider lists
  `opencode-go/gemini-4-argon` as an active chat model. The public model list
  at `https://opencode.ai/inference/v1/models` confirms
  `gemini-4-argon` accepts `text`, `image/png`, `image/jpeg`, `image/webp`,
  `image/heic`, `image/heif`, `application/pdf`, audio, and video input, with
  a 1,048,576-token context and 65,536-token output. Cost is $2/M input and
  $10/M output, with a 2x multiplier from 2026-12-01.
- **Endpoint and auth.** Native Gemini API family:
  `https://opencode.ai/inference/google/v1beta/models/gemini-4-argon:generateContent`
  for Console, or the Go base
  `https://opencode.ai/inference/go/google/v1beta/models/gemini-4-argon:generateContent`.
  `Authorization: Bearer <token>`; the key stays server-side. The request body
  is `{"contents":[{"role":"user","parts":[{"text":...},{"inline_data":
  {"mime_type":"image/jpeg","data":"<base64>"}}]}],
  "generationConfig":{"responseMimeType":"application/json"}}`. The response
  text is at `candidates[0].content.parts[*].text`.
- **Data handling.** The Go privacy table lists `gemini-4-argon` as not used
  for training with **0-day retention**. Avoid the `-contributor` variant,
  which may train on prompts and completions.
- **Suitability.** Go documentation describes the plan as tested coding
  models, and its API endpoints are documented for applications. The
  documentation does **not** explicitly address non-coding OCR/tutor traffic;
  a provider answer is still needed before calling the plan approved for this
  use. Image-request support itself is confirmed.
- **Remaining evidence.** No Go API key is present in this environment, so the
  provider comparison (accuracy, uncertainty, latency, request usage) and any
  default switch remain blocked on API access, then Task 27 device checks.

## Controller Rulings (2026-11-11)

- **Scope.** Implement an isolated Gemini adapter behind configuration, with
  fake-HTTP tests, plus the research record above. Do **not** switch the
  default provider, run a live comparison, or claim measured accuracy without
  an API key. Keep the openai path byte-for-byte compatible.
- **File set.** Edit `agent/config.py`, `agent/vision.py`,
  `tests/test_config.py`, `tests/test_vision.py`, `.env.example`,
  `scripts/check_providers.py`, and `docs/DEMO-RUNBOOK.md`. Do not touch
  `web/`, the controller, the tutor, or the contract.
- **Config.** Add `vision_api: str = "openai"` to `Settings` (`openai` or
  `gemini`), read from `VISION_API`, validated only when
  `VISION_PROVIDER=hosted`; `local` ignores it. Reject any other value with
  `ConfigurationError` naming `VISION_API`. `public_dict` may include it; it
  is not a secret.
- **Adapter.** In `VisionClient._request`, branch on `settings.vision_api`.
  The openai branch keeps the current payload, `response_format`, and 400
  retry. The gemini branch posts to
  `{vision_base_url.rstrip('/')}/models/{vision_model}:generateContent` with
  the Bearer key and the body described above, and parses
  `candidates[0].content.parts[*].text`, stripping a Markdown fence and
  raising `VisionError` on malformed JSON. Never log the key or request body.
  Detect the image MIME from the bytes (`\x89PNG` -> `image/png`, otherwise
  `image/jpeg`) and use the detected type in `inline_data` and in the openai
  data URL, so the PNG reference image is labelled correctly.
- **Checker/runbook.** `scripts/check_providers.py` reports the configured
  vision API family and still passes/fails on model/config presence. Add a
  `.env.example` block: `VISION_API=openai|gemini`, with the Go Gemini base
  URL and `VISION_MODEL=gemini-4-argon` commented as an example. Add a short
  runbook note that Gemini is implemented but not selected, the comparison is
  blocked on a Go API key, and Task 27 must verify the phone before any switch.
- **Tests.** Fake HTTP asserts: Gemini URL path and method, Bearer header,
  `contents`/`inline_data`/`mime_type`, `generationConfig.responseMimeType`,
  response parsing, fence stripping, malformed bodies, and HTTP failures
  mapped to redacted `VisionUnavailableError`. PNG and JPEG inputs produce the
  right MIME in both providers. Config tests cover default, gemini, invalid
  value, local ignoring `VISION_API`, and secret redaction. Keep all existing
  vision tests green.
- **Status.** This card stays in `docs/tasks/` and is marked `BLOCKED` on Go
  API access after the adapter work; do not file it under done. The manager
  records the work evidence and the remaining comparison steps.

## Work Evidence (2026-11-11)

- Files: `agent/config.py` (`vision_api`, `VISION_API` validation),
  `agent/vision.py` (Gemini `generateContent` branch, MIME detection from
  bytes, multi-part text parsing), `tests/test_config.py`,
  `tests/test_vision.py`, `.env.example`, `scripts/check_providers.py`,
  `docs/DEMO-RUNBOOK.md`.
- Verified: `python -m pytest tests -q -p no:cacheprovider` -> **309 passed,
  739 subtests passed**. `python -m py_compile` on every touched Python file
  -> **exit 0**. Fake-HTTP tests cover the Gemini URL, Bearer auth, body
  shape, `responseMimeType`, multi-part parsing, fence stripping, malformed
  bodies, redacted failures, no `response_format` retry, and PNG/JPEG MIME
  selection. `python scripts/check_providers.py` still reports missing
  provider configuration, as expected without a real `.env`.
- Deliberately not done: no default provider switch, no live request, no
  comparison numbers, no accuracy claims.
- Remaining, in order:
  1. Get a provider answer on whether Go may carry non-coding OCR/tutor
     traffic under the current plan.
  2. With a Go API key, run the same sanitized `docs/image.png` + synthetic
     cases through the existing hosted provider and
     `gemini-4-argon`; record sample count, accuracy, uncertainty rate,
     false-correction count, latency, and request usage.
  3. Only if Gemini wins, switch the default after Task 27 verifies it on the
     phone; keep the existing provider until then.
- Concerns:
  - The adapter has never called the live endpoint; the request shape follows
    the documented native Gemini API and the live model metadata.
  - `VISION_BASE_URL` and `VISION_MODEL` must be set together for Gemini; the
    model path is appended by the client.
  - JSON mode relies on `generationConfig.responseMimeType`; no response
    schema is sent, so malformed JSON still maps to `VisionError`.
  - MIME detection handles PNG and JPEG only (the browser sends JPEG and the
    reference sheet is PNG).
  - Gemini pricing has a 2x multiplier from 2026-12-01; Go plan limits and
    suitability still need confirmation.
