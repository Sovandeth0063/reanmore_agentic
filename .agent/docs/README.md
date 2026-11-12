# Project skills (`.agent/`)

Project-local skills for the Grade 3 math tutor demo.

OpenCode does not scan `.agent/` by default, so the project root
`opencode.json` registers it:

```json
{ "skills": ["./.agent"] }
```

Each directory containing a `SKILL.md` is one skill. The directory name is the
skill ID (exact, case-sensitive):

| Directory | ID | Use when |
| --- | --- | --- |
| `implement-task-card/` | `implement-task-card` | implementing or resuming a card under `docs/tasks/` |
| `demo-invariants/` | `demo-invariants` | changing anything that affects what the tutor says or which exercises exist |
| `verify-providers/` | `verify-providers` | checking the session API, Ollama, faster-whisper, the browser turn detector, or vision readiness |
| `file-task-card/` | `file-task-card` | closing a finished card into `docs/tasks/done/` |

Keep supporting files beside each `SKILL.md`; paths inside a skill are relative
to that directory. Do not add loose `*.md` files at the `.agent/` root — OpenCode
treats root-level Markdown files as skills too.

These skills do not replace `docs/tasks/00-DEMO-SPEC.md` or the global
`AGENTS.md` policy. The spec and controller rulings win on any conflict.
