from __future__ import annotations

from pathlib import Path

from scripts.check_skill_collisions import (
    _invalid_trigger_formats,
    resolve_conflict,
    scan_skills,
)


def _write_skill(
    root: Path,
    name: str,
    *,
    declared_name: str,
    triggers: list[str],
    host: bool = False,
) -> Path:
    skill_root = root / ".agent" / "skills" if host else root / "skills"
    skill_dir = skill_root / name
    skill_dir.mkdir(parents=True)
    skill = skill_dir / "SKILL.md"
    triggers_inline = ", ".join(triggers)
    skill.write_text(
        f"---\nname: {declared_name}\nversion: 1.0.0\n"
        f"description: x\ntriggers: [{triggers_inline}]\n---\n# {name}\n",
        encoding="utf-8",
    )
    return skill


def test_no_collisions(tmp_path: Path) -> None:
    _write_skill(tmp_path, "a", declared_name="A", triggers=["/a", "/aa"])
    _write_skill(tmp_path, "b", declared_name="B", triggers=["/b", "/bb"])
    names, triggers = scan_skills(tmp_path)
    assert all(len(paths) == 1 for paths in names.values())
    assert all(len(paths) == 1 for paths in triggers.values())


def test_trigger_collision_detected(tmp_path: Path) -> None:
    _write_skill(tmp_path, "a", declared_name="A", triggers=["/audit", "/local-audit"])
    _write_skill(tmp_path, "b", declared_name="B", triggers=["/secure", "/audit"])
    _, triggers = scan_skills(tmp_path)
    duplicates = {trig: paths for trig, paths in triggers.items() if len(paths) > 1}
    assert "/audit" in duplicates
    assert len(duplicates["/audit"]) == 2


def test_name_collision_detected(tmp_path: Path) -> None:
    _write_skill(tmp_path, "a", declared_name="Audit", triggers=["/x"])
    _write_skill(tmp_path, "b", declared_name="Audit", triggers=["/y"])
    names, _ = scan_skills(tmp_path)
    duplicates = {name: paths for name, paths in names.items() if len(paths) > 1}
    assert duplicates == {
        "Audit": [
            tmp_path / "skills" / "a" / "SKILL.md",
            tmp_path / "skills" / "b" / "SKILL.md",
        ]
    }


def test_file_without_frontmatter_skipped(tmp_path: Path) -> None:
    skill_dir = tmp_path / "skills" / "broken"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# no frontmatter here\n", encoding="utf-8")
    names, triggers = scan_skills(tmp_path)
    assert names == {} and triggers == {}


def test_real_repo_has_no_collisions() -> None:
    """Regression guard for the actual repo state after WP-2026-086 follow-up."""
    repo_root = Path(__file__).resolve().parent.parent
    names, triggers = scan_skills(repo_root)
    dup_names = {n: p for n, p in names.items() if len(p) > 1}
    dup_triggers = {t: p for t, p in triggers.items() if len(p) > 1}
    assert dup_names == {}, f"Skill name collisions: {dup_names}"
    assert dup_triggers == {}, f"Skill trigger collisions: {dup_triggers}"


def test_host_and_bundle_trigger_collision_detected(tmp_path: Path) -> None:
    _write_skill(tmp_path, "bundle-skill", declared_name="Bundle", triggers=["/shared"])
    _write_skill(
        tmp_path,
        "host-skill",
        declared_name="Host",
        triggers=["/shared"],
        host=True,
    )

    names, triggers = scan_skills(tmp_path)
    assert len(names["Bundle"]) == 1
    assert len(names["Host"]) == 1
    assert len(triggers["/shared"]) == 2
    assert any(
        path.parent.name == "host-skill" and ".agent" in path.parts
        for path in triggers["/shared"]
    )


def test_invalid_trigger_format_rejected(tmp_path: Path) -> None:
    """[D1] A trigger outside the closed format vocabulary is always flagged."""
    _write_skill(tmp_path, "a", declared_name="A", triggers=["Review Now", "/ok"])
    _, triggers = scan_skills(tmp_path)
    violations = _invalid_trigger_formats(triggers)
    violated_keys = {trigger for trigger, _paths in violations}
    assert "Review Now" in violated_keys
    assert "/ok" not in violated_keys


def test_conflict_policy_deny_wins_always_denies(tmp_path: Path) -> None:
    """[D2] deny-wins never resolves a duplicate, host/bundle or not."""
    _write_skill(tmp_path, "bundle-skill", declared_name="Bundle", triggers=["/shared"])
    _write_skill(
        tmp_path, "host-skill", declared_name="Host", triggers=["/shared"], host=True
    )
    _, triggers = scan_skills(tmp_path)
    paths = triggers["/shared"]
    assert resolve_conflict(paths, "deny-wins") is True


def test_conflict_policy_host_wins_resolves_bundle_host_pair(tmp_path: Path) -> None:
    """[D2]/[D3] host-wins resolves a 1:1 bundle/host pair deterministically."""
    _write_skill(tmp_path, "bundle-skill", declared_name="Bundle", triggers=["/shared"])
    _write_skill(
        tmp_path, "host-skill", declared_name="Host", triggers=["/shared"], host=True
    )
    _, triggers = scan_skills(tmp_path)
    paths = triggers["/shared"]
    assert resolve_conflict(paths, "host-wins") is False
    # Deterministic: re-running against the same path set gives the same verdict.
    assert resolve_conflict(list(reversed(paths)), "host-wins") is False


def test_conflict_policy_host_wins_does_not_rescue_same_layer_duplicate(
    tmp_path: Path,
) -> None:
    """[D2] host-wins only resolves a bundle/host pair; two bundle skills stay denied."""
    _write_skill(tmp_path, "a", declared_name="A", triggers=["/shared"])
    _write_skill(tmp_path, "b", declared_name="B", triggers=["/shared"])
    _, triggers = scan_skills(tmp_path)
    paths = triggers["/shared"]
    assert resolve_conflict(paths, "host-wins") is True
