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
    text = (GENERATED / "gstack-review" / "SKILL.md").read_text(encoding="utf-8", errors="replace")
    assert "name: review" in text and "Pre-landing PR review" in text
