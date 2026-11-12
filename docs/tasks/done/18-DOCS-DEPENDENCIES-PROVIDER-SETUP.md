# Task 18: Dependencies, Provider Setup, And Documentation Hygiene

## Goal

Close the setup and documentation gaps that stop a fresh machine from running
the demo, without putting any real key or hardware detail in the repository.

## Findings Addressed

Review 2026-11-08, setup and documentation findings:

- `requirements.txt` has `livekit-api` but no `livekit-agents`, so the Task 11
  worker cannot be installed.
- Card 01 requires "self-hosted LiveKit starts successfully" but the repo has
  no server config or start command.
- iPhone Safari needs a secure context for `getUserMedia`; the Vite dev server
  on a LAN IP is plain HTTP.
- `scripts/check_providers.py --live` prints "deferred".
- `README.md` still points at `docs/tasks/01-...` after the cards moved to
  `docs/tasks/done/`.
- `.env.example` reads as if `devkey` / `change-this-local-secret` are real
  values.

## Specification

### Dependencies

- Add `livekit-agents>=1.0,<2` to `requirements.txt`; keep `livekit-api`,
  `fastapi`, `uvicorn`, `httpx`, `PyYAML`, `faster-whisper`, `silero-vad`.
- Add `@vitejs/plugin-basic-ssl` to `web/package.json` devDependencies and
  enable it in `web/vite.config.ts` so `npm run dev` serves HTTPS. Keep
  `host: true` and the `/get-token` proxy.

### Local LiveKit

- Create `infra/livekit.yaml` (allowed by architecture 02 §2 and §9: a
  self-hosted LiveKit server is the documented transport) with a local-only key
  pair `devkey: change-this-local-secret` (the same placeholders as
  `.env.example`), `room.auto_create: true`, and ports 7880/7881/7882.
- Create `infra/docker-compose.yml` running
  `livekit/livekit-server --config /etc/livekit.yaml` with 7880/tcp,
  7881/tcp, 7882/udp published.
- These are development placeholders, not secrets. No real key, certificate,
  or device serial goes into the repository.

### Provider check

- Implement `--live` in `scripts/check_providers.py`: load `docs/image.png`,
  call `VisionClient.parse_worksheet`, and print the item count or the domain
  error. Never print the API key, the request URL, or response bodies.
- Keep `--live` opt-in; the default run stays offline.

### Documentation

- `README.md`: update the Docs/Task-plan paths to `docs/tasks/done/`, add the
  worker command (`python -m agent.main dev`), the token server
  (`uvicorn server.token_server:app --host 0.0.0.0 --port 8000`), the compose
  command, and the HTTPS note for the iPhone.
- `docs/DEMO-RUNBOOK.md`: add the same four start commands and a "secure
  context" check (phone opens `https://<laptop-lan-ip>:5173` and accepts the
  self-signed certificate).
- `.env.example`: keep every key a placeholder. Add comments marking
  `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` as local development placeholders
  and `VISION_API_KEY` as required only when `VISION_PROVIDER=hosted`; leave
  the value empty. Mention `VISION_BASE_URL` (added by Task 19) as a URL, not
  a secret. Do not add a real key, IP, or device model value.
- Update the register's "Task cards" path reference if it still points at
  `docs/tasks/`.

## Files

- Modify: `requirements.txt`
- Modify: `web/package.json`, `web/vite.config.ts`, `web/package-lock.json`
- Create: `infra/livekit.yaml`, `infra/docker-compose.yml`
- Modify: `scripts/check_providers.py`
- Modify: `README.md`, `docs/DEMO-RUNBOOK.md`, `.env.example`
- Modify: `docs/tasks/TASK-REPORT.md` (path reference only; statuses are the
  register owner's job)

## Acceptance Criteria

- `python -m py_compile scripts\check_providers.py` succeeds.
- `npm run build` in `web/` succeeds after the HTTPS plugin is added.
- `docker compose -f infra/docker-compose.yml config` parses (manual; run
  when Docker is available).
- No real key, IP address, certificate, or device identifier is committed;
  every secret field in `.env.example` stays a placeholder or empty.
- Three consecutive rehearsals remain a manual acceptance item.

## Dependencies

- Tasks 11 (worker command in `agent/main.py`), 17 (browser build surface),
  and 19 (the `VISION_BASE_URL` variable documented here).

## Scope Ruling

- The HTTPS dev server is the documented way to give iPhone Safari a secure
  context (architecture 02 §8 requires camera/microphone permissions over
  HTTPS); it is a development convenience, not a production certificate.
- `infra/livekit.yaml` and `infra/docker-compose.yml` implement the self-hosted
  LiveKit server that architecture 02 §2 and §9 already require.

## Controller Rulings (2026-11-08)

- **Ruling: `requirements.txt` is already satisfied.** Card 11 added
  `livekit-agents>=1.0,<2`; verify it is present and do not add a duplicate
  line or change the other pins.
- **Ruling: the manager owns `npm install` and `npm run build`.** Add
  `@vitejs/plugin-basic-ssl` to `web/package.json` and enable it in
  `web/vite.config.ts`; do **not** run npm. The manager runs `npm install`
  (which updates `package-lock.json`) and the build. If the lockfile must be
  touched to keep the repo consistent, note it for the manager instead.
- **Ruling: the worker command is `python -m agent.main dev`** in README and
  runbook; `agent/worker.py` does not exist and must not be documented.
- **Ruling: `.env.example` stays placeholder-only.** `VISION_BASE_URL` is
  already present from card 19; `VISION_API_KEY` stays empty.
- **Ruling: `infra/livekit.yaml` and `infra/docker-compose.yml` are allowed**
  by architecture 02 §2/§9 (self-hosted LiveKit is the documented transport).
  The HTTPS dev server is the secure-context mechanism required by §8.
- **Ruling: report in the final message, no report file.** No pytest, npm, or
  docker; `python -m py_compile scripts\check_providers.py` only.

## Verification Note

Implementer runs only `py_compile` for the script; the manager runs
`npm run build` in `web/`. Docker and iPhone checks stay deferred-manual.

## Estimate

0.25 day.

## Completion Evidence (2026-11-08)

- Files: `web/package.json` (`@vitejs/plugin-basic-ssl` ^2.0.0),
  `web/vite.config.ts` (`basicSsl()`, `host: true` and the `/get-token` proxy
  kept), `web/package-lock.json` (manager `npm install`),
  `infra/livekit.yaml` (new), `infra/docker-compose.yml` (new),
  `scripts/check_providers.py`, `README.md`, `docs/DEMO-RUNBOOK.md`,
  `.env.example` (unchanged from card 19 except wording).
- Verified by the manager: `npm install` in `web/` -> completed, 0
  vulnerabilities, lockfile updated. `npm run build` ->
  `tsc --noEmit && vite build` succeeded (8 modules, `dist/` emitted; only the
  >500 kB chunk warning). `python -m py_compile scripts\check_providers.py` ->
  exit 0.
- `requirements.txt`: `livekit-agents>=1.0,<2` was already present from card 11;
  no duplicate line and no pin changed.
- `--live`: `main(live=True)` runs every configured check, then
  `_live_vision(settings)` sends `docs/image.png` to the configured provider and
  prints the parsed item count. Failures print only the exception type and the
  domain error's redacted message — never the key, base URL, or provider body.
  A failed `--live` check returns a non-zero exit code.
- Deferred-manual: `docker compose -f infra/docker-compose.yml config` (Docker is
  not installed here), a real LiveKit join, and the iPhone Safari secure-context
  run. Three consecutive rehearsals remain a manual acceptance item.
- Concerns:
  - `LIVEKIT_URL` is read by both the token server and the browser, so for the
    iPhone it must be the laptop's LAN address; `localhost` only works on the
    laptop itself. Documented in `README.md` and `docs/DEMO-RUNBOOK.md`.
  - `infra/docker-compose.yml` uses `livekit/livekit-server:latest`; the image
    should be pinned to a tested tag before the demo freeze.
  - The placeholder key pair (`devkey` / `change-this-local-secret`) is public
    and local-only; it is the same value in `.env.example`, as the card allows.
    No real key, IP, certificate, or device identifier is committed.
  - The free-tier NVIDIA vision endpoint logs requests. Before a real demo with
    a child's handwriting, use a paid/zero-retention model or local Ollama
    vision (see `docs/DEMO-RUNBOOK.md`).
