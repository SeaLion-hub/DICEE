# gstack (primary workflow)

This repository uses [gstack](https://github.com/garrytan/gstack) as the **default delivery process**. Generated Codex/Cursor skills are committed under [`.agents/skills/gstack/.agents/skills/`](.agents/skills/gstack/.agents/skills/). After `./setup --host codex`, optional sibling folders `.agents/skills/gstack-*` appear locally for tools that only scan the skills directory root; those siblings are **gitignored** to avoid duplicating blobs.

## Sprint order

Think → Plan → Build → Review → Test → Ship → Reflect.

Typical commands (names match Cursor-discovered skills, e.g. `gstack-review`):

- `gstack-office-hours`, `gstack-plan-ceo-review`, `gstack-plan-eng-review`, `gstack-plan-design-review`
- `gstack-design-consultation`, `gstack-review`, `gstack-investigate`, `gstack-qa` / `gstack-qa-only`
- `gstack-ship`, `gstack-land-and-deploy`, `gstack-canary`, `gstack-benchmark`, `gstack-browse`
- `gstack-document-release`, `gstack-retro`, `gstack-cso`, `gstack-autoplan`
- Safety: `gstack-careful`, `gstack-freeze`, `gstack-guard`, `gstack-unfreeze`, `gstack-upgrade`

Web browsing for QA: prefer **gstack-browse**; avoid ad-hoc browser MCPs that conflict with project policy.

## Non-negotiables (override gstack suggestions)

If a gstack output conflicts with repository rules, **repository rules win**.

- **Architecture**: HTTP only in `app/api/`; business logic in `app/services/`; DB access only in `app/repositories/`. See [`.cursor/rules/architecture.mdc`](.cursor/rules/architecture.mdc).
- **Stack**: SQLAlchemy 2.0 async (`select` + `AsyncSession`), Pydantic v2. See [`.cursor/rules/tech-stack.mdc`](.cursor/rules/tech-stack.mdc).
- **Quality gate**: After code changes, run **`pytest`** (same expectations as CI: `ruff`, `mypy`, architecture tests, coverage floor).
- **Logging**: On feature/bugfix completion, add one line to [`docs/WORK_LOG.md`](docs/WORK_LOG.md). Sync roadmap when required by [`.cursor/rules/roadmap-and-worklog.mdc`](.cursor/rules/roadmap-and-worklog.mdc).
- **Manuals vs rules**: Manuals in `docs/rules/`; Cursor rules in `.cursor/rules/` only (do not mix paths).
- **Scope**: Keep PRs focused; avoid drive-by refactors. User-approved directory/scope wins over broad auto-fixes.

## First-time / new clone (Windows)

Requirements: **Git**, **Bun**, **Node.js** (Node required on Windows for Playwright; see upstream README).

From repo root, in **Git Bash** (adjust PATH if `node` is not visible inside Bash):

```bash
export PATH="/c/Program Files/nodejs:/c/Users/$USER/.bun/bin:$PATH"
cd .agents/skills/gstack && ./setup --host codex
```

This rebuilds `browse/dist` binaries and refreshes generated skills under `.agents/skills/gstack/.agents/skills/` and creates `.agents/skills/gstack-*` links for flat discovery (ignored by git).

Install Bun: see https://bun.sh

## Cursor verification (smoke)

1. Restart Cursor (or reload the window) after the first setup.
2. Confirm the agent can see skills (e.g. under `.agents/skills/gstack/.agents/skills/gstack-review`, or run setup once so flat `gstack-*` folders exist locally).
3. Run `pytest tests/test_gstack_adoption.py -q` — must pass in CI and locally.

## `todo.md` vs gstack

**Policy B**: [`todo.md`](todo.md) is optional scratch space; the canonical flow is gstack + this file. If you use `todo.md`, align its checklist with the sprint step you are in.
