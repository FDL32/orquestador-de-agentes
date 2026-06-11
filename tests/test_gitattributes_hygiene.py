"""WT-2026-248b: Git EOL hygiene for portable text surfaces."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
GITATTRIBUTES = REPO_ROOT / ".gitattributes"


def test_portable_text_surfaces_force_lf() -> None:
    """Portable docs/config/memory surfaces must normalize to LF in Git."""
    content = GITATTRIBUTES.read_text(encoding="utf-8")

    expected_rules = [
        "*.py text eol=lf",
        "*.md text eol=lf",
        "*.json text eol=lf",
        "*.jsonl text eol=lf",
        "*.toml text eol=lf",
        "*.yaml text eol=lf",
        "*.yml text eol=lf",
        "*.sh text eol=lf",
    ]

    for rule in expected_rules:
        assert rule in content, f"Missing LF normalization rule: {rule}"
