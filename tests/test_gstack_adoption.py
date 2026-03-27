"""Guardrail: vendored gstack layout for Cursor/Codex skill discovery."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
AGENTS_SKILLS = REPO_ROOT / ".agents" / "skills"
GSTACK_SRC = AGENTS_SKILLS / "gstack"
GENERATED = GSTACK_SRC / ".agents" / "skills"


def test_gstack_source_tree_present() -> None:
    assert GSTACK_SRC.is_dir(), "Clone gstack into .agents/skills/gstack"
    assert (GSTACK_SRC / "setup").is_file(), "Expected gstack setup script"


def test_generated_codex_skills_present() -> None:
    skill_md = GENERATED / "gstack-review" / "SKILL.md"
    assert skill_md.is_file(), "Run: cd .agents/skills/gstack && ./setup --host codex"


def test_gstack_skill_md_readable() -> None:
    """Assert generated skill looks like Codex SKILL.md, not exact copy-pasted phrases."""
    skill_md = GENERATED / "gstack-review" / "SKILL.md"
    text = skill_md.read_text(encoding="utf-8", errors="replace")
    assert len(text) >= 2048, "Generated gstack-review SKILL.md too small; run ./setup --host codex"
    stripped = text.lstrip()
    assert stripped.startswith("---"), "Expected YAML frontmatter opening"
    close = text.find("\n---\n", 1)
    assert close != -1, "Expected YAML frontmatter closing"
    frontmatter = text[:close]
    assert "name:" in frontmatter, "Expected name: in skill frontmatter"
    assert "description:" in frontmatter, "Expected description: in skill frontmatter"
