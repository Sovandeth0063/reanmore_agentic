---
name: Verify Providers
description: Use when checking whether the demo's providers are ready — before a rehearsal, after changing .env, or when a provider error appears. Covers the snapshot session API, Ollama, faster-whisper, the browser turn detector, and the hosted vision provider.
---

# Verify Providers

## Core principle

Verify configuration and reachability separately from the full demo, and never
print, log, or commit a secret. A provider that is "probably running" is not
verified.

## Prerequisites

- `.env` exists locally and was copied from `.env.example`.
- `agent/config.py` loads and validates the settings.
- Task 20 is complete. If `scripts/check_providers.py` does not exist, stop and
  finish Task 20 first.

## One command

```bash
python scripts/check_providers.py
```

It prints a pass/fail table and exits non-zero on failure. It checks:

| Provider | Check |
| --- | --- |
| Ollama | `GET {OLLAMA_BASE_URL}/api/tags` |
| faster-whisper | import check only |
| Vision | config presence only |

Add `--live` only when you intend to call the vision provider. That call sends
a test image, may cost money, and is never part of an automated test.

## Manual checks

1. **Config** — load `Settings.from_environment()` with the local `.env`.
   Missing values must raise `ConfigurationError` without echoing secrets.
   There is no runtime mode: `TUTOR_RUNTIME` and `LIVEKIT_*` are ignored.
2. **Ollama** — `/api/tags` lists the model named by `OLLAMA_MODEL`.
3. **faster-whisper** — the package imports and the `WHISPER_MODEL` loads.
4. **Session API** — start
   `uvicorn server.session_api:app --host 0.0.0.0 --port 8000` and confirm the
   demo can create a session. The checker does not start or call the API.
5. **Browser turn detector** — in the browser client, speak one short turn and
   confirm one utterance is uploaded per turn and capture stops while the tutor
   speaks. It runs in the browser and needs no backend package.
6. **Vision** — `VISION_PROVIDER=hosted` requires both `VISION_MODEL` and
   `VISION_API_KEY`; `VISION_PROVIDER=local` does not require the key.

## Failure map

| Failure | What it blocks | Fallback |
| --- | --- | --- |
| Backend unavailable | session create, speech turns, and snapshots | backup recording; the browser reports that the session could not start |
| Ollama down | intent and guidance phrasing | fixed response catalog |
| whisper model missing | speech-to-text | typed transcript during development |
| Browser turn detector blocked | speech boundaries | manual push-to-talk in development |
| Vision provider down | worksheet and handwriting reads | fixed 12-item list; ask the student to say the answer |
| Low confidence | answer checking | clarification question, never a correction |

## Rules

- Print `set` or `missing`, never a key value.
- Never commit `.env` or paste its contents into a report.
- Do not install packages or start services as part of an implementation card;
  this is a verification procedure.
- A failed provider check is a blocked acceptance criterion, not a pass.

## Red flags

| Thought | Reality |
| --- | --- |
| "The URL looks right." | Reachability is a check, not a guess. |
| "I'll paste the key to confirm it." | Never. Print `set` or `missing`. |
| "I'll run `--live` in the test suite." | It costs money and sends an image. Manual only. |
| "Ollama is optional, the demo can improvise." | Numbers must still come from the calculator; mark the provider failure. |
| "The script is missing, I'll skip verification." | Missing script means Task 20 is incomplete. |
