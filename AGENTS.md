# Agent instructions

- **Primary workflow**: [GSTACK.md](GSTACK.md) (gstack skills under `.agents/skills/`).
- **Repository rules**: `.cursor/rules/` (architecture, tech stack, integrations).
- **Human manuals**: `docs/rules/` and `docs/CAUTIONS.md` when relevant.

If gstack skills fail to load or `/browse` breaks, run `./setup --host codex` from `.agents/skills/gstack` after ensuring `bun` and `node` are on your PATH (Windows: use Git Bash; see [GSTACK.md](GSTACK.md)).
