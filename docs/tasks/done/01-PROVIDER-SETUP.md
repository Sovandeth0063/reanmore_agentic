# Task 01: Provider Setup

## Goal

Prepare the local services, vision provider, and environment configuration
required by the interactive demo.

## Scope

- Self-hosted LiveKit server
- Local Ollama installation and a small instruction-following model
- Local faster-whisper installation and model
- Silero VAD package/model
- Hosted vision provider account and key (default)
- Optional local vision model as fallback
- Local environment file

## Specification

Use these configuration values:

- `LIVEKIT_URL=http://localhost:7880`
- Local `LIVEKIT_API_KEY` and `LIVEKIT_API_SECRET` for JWT signing
- `OLLAMA_BASE_URL=http://localhost:11434`
- `OLLAMA_MODEL`
- `WHISPER_MODEL`
- `VISION_PROVIDER` (hosted or local)
- `VISION_API_KEY` (hosted only)
- `VISION_MODEL`

Keep all secrets on the backend. Never commit a real `.env` file or API key.

The hosted vision provider is the default because handwriting accuracy is the
main demo risk. Audio, speech-to-text, and intent classification stay local.
If the hosted provider is rejected, configure a local vision model and note
that the demo must be staged for handwriting legibility.

## Acceptance Criteria

- Self-hosted LiveKit starts successfully.
- Ollama serves the selected local model.
- faster-whisper loads the selected local model.
- The vision provider can read a test snapshot and return a structured list of
  printed exercises.
- The vision provider can read a test handwritten answer and return a value
  with a confidence score.
- A local environment file can be created from `.env.example`.
- Local service health can be tested independently.
- No local secret appears in frontend code, logs, or committed files.

## Dependencies

None.

## Estimate

0.5 day.

## Closure (2026-11-07)

Status: completed for repository setup; live provider verification remains
deferred-manual until local services and a vision provider are configured.

- Implemented validated environment loading in `agent/config.py`.
- Added `.env.example` and secret exclusion in `.gitignore`.
- Added dependency declarations in `requirements.txt`.
- Added independent provider/import checks in `scripts/check_providers.py`.
- Added configuration tests in `tests/test_config.py`.
- Verified with:
  `python -m py_compile agent\config.py scripts\check_providers.py tests\test_config.py`
- Deferred-manual: LiveKit startup, Ollama model serving, faster-whisper model
  loading, Silero VAD model loading, and hosted vision worksheet/handwriting
  reads.
