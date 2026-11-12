---
name: File Task Card
description: Use when a task card's acceptance criteria are met and the card must be closed — recording evidence, moving it to docs/tasks/done/, and updating the task register and SDD ledger.
---

# File A Finished Task Card

## Core principle

A card is DONE only when evidence exists. Moving the file is the last step, not
the first.

## Preconditions

- Implementation is complete.
- The manager ran the card's primary test and saw it pass, or the card is
  explicitly manual or deferred.
- No unresolved review findings.
- The card's dependencies are already DONE.

If any precondition fails, the card stays in `docs/tasks/`.

## 1. Record evidence in the card

Append this section before moving the file:

```markdown
## Completion Evidence (YYYY-MM-DD)

- Files: <changed files>
- Verified: `<command>` → <observed result>
- Written but not run: <tests>
- Deferred/manual: <provider or device checks>
- Concerns: <known limitations or none>
```

Never write "tests pass" unless the command was run and the output was seen.
State manual checks as manual.

## 2. Move the card

- Destination: `docs/tasks/done/`
- Keep the filename unchanged.
- Use a plain move (`Move-Item` on Windows, `mv` in Git Bash).
- Do not use `git mv`; it stages the change, and this project does not stage.

## 3. Update the register

In `docs/tasks/TASK-REPORT.md`, set the card's status to `DONE` and replace the
evidence note with a one-line summary plus the date.

## 4. Update the ledger

In `.superpowers/sdd/<plan>/progress.md`, set the task's status and evidence,
and record any ruling made while closing it.

## 5. Do not

- Delete the card.
- Mark DONE with a failing or unrun test.
- Move a card whose dependency is still TODO.
- Rewrite the card's acceptance criteria to match what was built.
- Bundle several cards into one move without closing each one's evidence.

## Red flags

| Thought | Reality |
| --- | --- |
| "The code is written, so it's done." | Written is not verified. |
| "The test would obviously pass." | Run it or record it as unrun. |
| "I'll mark it DONE and fix it later." | The register is the recovery map; a false DONE loses the work. |
| "I'll git mv so history is cleaner." | `git mv` stages. Use a plain move. |
| "I'll update the register after the next card." | Update it in the same step, while the evidence is fresh. |
