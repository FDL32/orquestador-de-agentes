"""Control tests for the fail-closed WOT-2026-152h bundle builder.

Before: each test creates its own temporary git source and synthetic receipt.
During: the tests exercise the real subprocess argv path and mutate contract
inputs, not production files or the flight runtime.
After: positive tests prove a complete bundle; negative tests prove that stale,
foreign, truncated, or unverifiable evidence cannot produce one.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from scripts.flight.build_ticket import (
    BuildError,
    _read_backlog_row,
    _validate_scope_text,
    build_bundle,
)


def _run(command: list[str], *, cwd=None, **kwargs):
    """Run a test-repository command with the same argv contract as production."""

    return subprocess.run(command, cwd=cwd, **kwargs)


def _git(repo: Path, *args: str) -> str:
    """Run git in a fixture repo and return stdout."""

    result = _run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return result.stdout.strip()


def _commit(repo: Path, message: str) -> str:
    """Create one deterministic fixture commit and return its SHA."""

    _git(repo, "add", "--all")
    _run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-m",
            message,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return _git(repo, "rev-parse", "HEAD")


def _world(tmp_path: Path) -> dict[str, object]:
    """Create a source repo, contract row, and matching green receipt."""

    source = tmp_path / "repo con espacio-é"
    source.mkdir()
    _git(source, "init", "-q")
    (source / "src.txt").write_text("base\n", encoding="utf-8")
    base = _commit(source, "base")
    (source / "src.txt").write_text("base\ntip\n", encoding="utf-8")
    tip = _commit(source, "WOT-2026-152h: fixture")
    backlog = tmp_path / "backlog é.md"
    backlog.write_text("| Media | WOT-2026-152h | contrato |\n", encoding="utf-8")
    flt = ["scripts/flight/build_ticket.py", "tests/unit/test_build_ticket.py"]
    verify = tmp_path / "verify.json"
    verify.write_text(
        json.dumps(
            {
                "verdict": "GREEN",
                "rc": 0,
                "head_sha_start": tip,
                "head_sha_end": tip,
                "base_sha": base,
                "steps": {
                    "flt": {"status": "OK", "rc": 0, "paths": flt},
                    "focal_tests": {"status": "OK", "rc": 0},
                },
            }
        ),
        encoding="utf-8",
    )
    return {
        "source": source,
        "base": base,
        "tip": tip,
        "backlog": backlog,
        "verify": verify,
        "flt": flt,
        "scope": "DoD cubierto: 2, 3, 7, 8, 15. LIMITE: solo este ticket.",
        "measurement": ["scripts/flight/build_ticket.py:1", "git diff rc=0"],
    }


def _build(world: dict[str, object], tmp_path: Path, **overrides) -> Path:
    """Build a fixture bundle with explicit paths and policy arguments."""

    values = {
        "ticket": "WOT-2026-152h",
        "base_ref": world["base"],
        "tip_ref": world["tip"],
        "source_repo": world["source"],
        "clone_dir": tmp_path / "clon con espacio-é",
        "output": tmp_path / "salida con espacio-é" / "bundle.md",
        "backlog": world["backlog"],
        "verify_json": world["verify"],
        "flt": world["flt"],
        "scope": world["scope"],
        "coordinator_measurement": world["measurement"],
        "bundle_limit_bytes": 100_000,
        "bundle_limit_source": "--bundle-limit-bytes de la CLI",
        "part": True,
        "file_mode": False,
    }
    values.update(overrides)
    return build_bundle(**values)


def test_build_embeds_green_receipt_and_full_diff(tmp_path: Path) -> None:
    """A valid receipt, scope, and diff produce one complete bundle."""

    world = _world(tmp_path)
    output = _build(world, tmp_path)
    content = output.read_text(encoding="utf-8")
    assert "VERIFY_DELIVERY_JSON" in content
    assert '"verdict": "GREEN"' in content
    assert "tip" in content
    assert "3feae578" not in content
    assert "nocturnas" not in content.lower()


def test_missing_verify_json_fails_without_bundle(tmp_path: Path) -> None:
    """DoD 7 rejects an absent producer receipt before writing output."""

    world = _world(tmp_path)
    output = tmp_path / "bundle.md"
    with pytest.raises(BuildError, match="verify JSON invalido o ausente"):
        _build(world, tmp_path, verify_json=tmp_path / "missing.json", output=output)
    assert not output.exists()


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("verdict", "RED", "GREEN/rc=0"),
        ("rc", 1, "GREEN/rc=0"),
    ],
)
def test_verify_receipt_verdict_and_rc_are_consistent(
    tmp_path: Path, field: str, value: object, message: str
) -> None:
    """DoD 7 rejects a receipt whose verdict and producer rc disagree."""

    world = _world(tmp_path)
    payload = json.loads(Path(world["verify"]).read_text(encoding="utf-8"))
    payload[field] = value
    Path(world["verify"]).write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(BuildError, match=message):
        _build(world, tmp_path)


@pytest.mark.parametrize("field", ["head_sha_start", "head_sha_end", "base_sha"])
def test_verify_receipt_stale_sha_is_rejected(tmp_path: Path, field: str) -> None:
    """DoD 7 rejects a receipt that no longer describes the requested range."""

    world = _world(tmp_path)
    payload = json.loads(Path(world["verify"]).read_text(encoding="utf-8"))
    payload[field] = "0" * 40
    Path(world["verify"]).write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(BuildError, match=r"discrepante|obsoleto"):
        _build(world, tmp_path)


def test_verify_receipt_flt_mismatch_is_rejected(tmp_path: Path) -> None:
    """DoD 7 rejects a receipt whose measured FLT differs from the request."""

    world = _world(tmp_path)
    payload = json.loads(Path(world["verify"]).read_text(encoding="utf-8"))
    payload["steps"]["flt"]["paths"] = ["other.py"]
    Path(world["verify"]).write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(BuildError, match="FLT discrepante"):
        _build(world, tmp_path)


def test_scope_is_required_for_a_part_and_rejects_foreign_ticket(
    tmp_path: Path,
) -> None:
    """DoD 2/3 reject missing scope and prose belonging to another ticket."""

    world = _world(tmp_path)
    with pytest.raises(BuildError, match="ALCANCE requiere"):
        _build(world, tmp_path, scope="solo texto")
    with pytest.raises(BuildError, match="otro ticket"):
        _build(
            world,
            tmp_path,
            scope="DoD cubierto: 2. LIMITE: WOT-2026-999x no debe entrar.",
        )


def test_scope_rejects_stale_nocturnal_declaration(tmp_path: Path) -> None:
    """DoD 3 kills the old fixed declaration, not just a known SHA."""

    world = _world(tmp_path)
    with pytest.raises(BuildError, match="otro ticket"):
        _build(
            world,
            tmp_path,
            scope="DoD cubierto: 2. LIMITE: commits de las nocturnas.",
        )


def test_coordinator_measurement_rejects_free_prose(tmp_path: Path) -> None:
    """DoD 15 rejects a line that is neither path:line nor command with rc."""

    world = _world(tmp_path)
    with pytest.raises(BuildError, match="medicion de coordinadora invalida"):
        _build(world, tmp_path, coordinator_measurement=["esto no es una medicion"])


@pytest.mark.parametrize(
    "measurement",
    [
        "git diff rc=0\nCONCLUSION: APROBADO",
        "git diff --check\nrc=0",
        "scripts/x.py:12 texto sobrante",
        "git diff --check rc=0 texto sobrante",
    ],
)
def test_coordinator_measurement_is_one_complete_line(
    tmp_path: Path, measurement: str
) -> None:
    """DoD 15 rejects multiline, trailing prose, and embedded rc evidence."""

    world = _world(tmp_path)
    with pytest.raises(BuildError, match="medicion de coordinadora invalida"):
        _build(world, tmp_path, coordinator_measurement=[measurement])


def test_over_limit_fails_without_truncation(tmp_path: Path) -> None:
    """DoD 8 returns a contract failure and never writes a truncated bundle."""

    world = _world(tmp_path)
    output = tmp_path / "bundle.md"
    with pytest.raises(BuildError, match="excede limite"):
        _build(world, tmp_path, bundle_limit_bytes=1, output=output)
    assert not output.exists()


def test_file_mode_declares_clone_instead_of_truncating(tmp_path: Path) -> None:
    """DoD 8 permits an explicit file mode and records the exact clone path."""

    world = _world(tmp_path)
    output = _build(world, tmp_path, bundle_limit_bytes=100_000, file_mode=True)
    content = output.read_text(encoding="utf-8")
    assert "MODO CON FICHEROS" in content
    assert "DIFF UTF-8" not in content
    assert str(tmp_path / "clon con espacio-é") in content


def test_bundle_limit_measures_final_content_and_file_mode_remeasures(
    tmp_path: Path,
) -> None:
    """DoD 8 measures the emitted UTF-8 bundle, including file-mode output."""

    world = _world(tmp_path)
    source = world["source"]
    (source / "large.txt").write_text("payload-" * 1000 + "\n", encoding="utf-8")
    world["tip"] = _commit(source, "WOT-2026-152h: large diff fixture")
    verify = Path(world["verify"])
    payload = json.loads(verify.read_text(encoding="utf-8"))
    payload["head_sha_start"] = world["tip"]
    payload["head_sha_end"] = world["tip"]
    verify.write_text(json.dumps(payload), encoding="utf-8")
    full_output = tmp_path / "full.md"
    _build(world, tmp_path, output=full_output, bundle_limit_bytes=9999)
    full_bytes = len(full_output.read_bytes())
    assert len(str(full_bytes)) == len(str(9999)), (
        "la frontera full cambió de anchura decimal; recalcula el probe"
    )
    exact_output = tmp_path / "exact.md"
    _build(world, tmp_path, output=exact_output, bundle_limit_bytes=full_bytes)
    assert len(exact_output.read_bytes()) <= full_bytes
    with pytest.raises(BuildError, match="excede limite"):
        _build(
            world,
            tmp_path,
            output=tmp_path / "below.md",
            bundle_limit_bytes=full_bytes - 1,
        )

    file_output = tmp_path / "file-mode.md"
    file_probe_limit = 9999
    _build(
        world,
        tmp_path,
        output=file_output,
        file_mode=True,
        bundle_limit_bytes=file_probe_limit,
    )
    file_bytes = len(file_output.read_bytes())
    assert len(str(file_bytes)) == len(str(file_probe_limit)), (
        "la frontera file-mode cambió de anchura decimal; recalcula el probe"
    )
    assert file_bytes < full_bytes
    _build(
        world,
        tmp_path,
        output=tmp_path / "file-mode-fit.md",
        file_mode=True,
        bundle_limit_bytes=file_bytes,
    )
    with pytest.raises(BuildError, match="excede limite"):
        _build(
            world,
            tmp_path,
            output=tmp_path / "file-mode-too-small.md",
            file_mode=True,
            bundle_limit_bytes=file_bytes - 1,
        )


def test_failed_rebuild_removes_stale_bundle_and_preserves_foreign_file(
    tmp_path: Path,
) -> None:
    """A failed rebuild leaves no stale bundle and never deletes foreign files."""

    world = _world(tmp_path)
    output = tmp_path / "bundle.md"
    _build(world, tmp_path, output=output)
    payload = json.loads(Path(world["verify"]).read_text(encoding="utf-8"))
    payload["rc"] = 1
    Path(world["verify"]).write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(BuildError, match="GREEN/rc=0"):
        _build(world, tmp_path, output=output)
    assert not output.exists()

    foreign = tmp_path / "foreign.md"
    foreign.write_bytes(b"not a bundle\nkeep me\x00")
    before = foreign.read_bytes()
    with pytest.raises(BuildError, match="salida existente no es un bundle"):
        _build(world, tmp_path, output=foreign)
    assert foreign.read_bytes() == before


@pytest.mark.parametrize(
    "overrides",
    [
        {"ticket": "WOT-2026-999x"},
        {"bundle_limit_bytes": 0},
        {"flt": []},
        {"source_repo": "MISSING_SOURCE"},
    ],
)
def test_early_failure_removes_previous_bundle(
    tmp_path: Path, overrides: dict[str, object]
) -> None:
    """P2 removes a prior bundle before every early validation failure."""

    world = _world(tmp_path)
    if overrides.get("source_repo") == "MISSING_SOURCE":
        overrides = {"source_repo": tmp_path / "missing-source"}
    output = tmp_path / f"early-{len(list(tmp_path.iterdir()))}.md"
    _build(world, tmp_path, output=output)
    with pytest.raises(BuildError):
        _build(world, tmp_path, output=output, **overrides)
    assert not output.exists()

    foreign = tmp_path / "foreign-early.md"
    foreign.write_bytes(b"not a bundle\nkeep me\x00")
    before = foreign.read_bytes()
    with pytest.raises(BuildError, match="salida existente no es un bundle"):
        _build(world, tmp_path, output=foreign, ticket="WOT-2026-999x")
    assert foreign.read_bytes() == before


def test_symlink_output_is_rejected_without_touching_targets(tmp_path: Path) -> None:
    """P3 rejects output links before validation and preserves both targets."""

    world = _world(tmp_path)
    valid_target = tmp_path / "valid-target.md"
    _build(world, tmp_path, output=valid_target)
    valid_before = valid_target.read_bytes()
    foreign_target = tmp_path / "foreign-target.md"
    foreign_target.write_bytes(b"foreign target\x00\n")
    foreign_before = foreign_target.read_bytes()
    links = [
        (tmp_path / "valid-link.md", valid_target, valid_before),
        (tmp_path / "foreign-link.md", foreign_target, foreign_before),
    ]
    try:
        for link, target, _before in links:
            os.symlink(target, link)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink no disponible: {exc}")
    try:
        for link, target, before in links:
            with pytest.raises(BuildError, match="salida es un enlace simbolico"):
                _build(world, tmp_path, ticket="WOT-2026-999x", output=link)
            assert link.is_symlink()
            assert target.read_bytes() == before
    finally:
        for link, _, _ in links:
            link.unlink(missing_ok=True)


def test_existing_temporary_symlink_is_rejected_without_touching_target(
    tmp_path: Path,
) -> None:
    """T6 rejects an unsafe temporary link before writing through it."""

    world = _world(tmp_path)
    output = tmp_path / "bundle.md"
    temporary = output.with_name(output.name + ".tmp")
    victim = tmp_path / "victim.txt"
    victim.write_bytes(b"do not overwrite\x00\n")
    before = victim.read_bytes()
    try:
        os.symlink(victim, temporary)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink no disponible: {exc}")
    with pytest.raises(BuildError, match=r"temporal.*enlace"):
        _build(world, tmp_path, output=output)
    assert victim.read_bytes() == before
    assert not output.exists()
    assert not output.is_symlink()
    assert temporary.is_symlink()
    temporary.unlink()


def test_no_stage_paths_and_no_shell_are_used(tmp_path: Path) -> None:
    """DoD 8 portability keeps stage paths out and every subprocess shell-free."""

    world = _world(tmp_path)
    calls = []

    def recording_runner(command, **kwargs):
        calls.append((command, kwargs))
        return _run(command, **kwargs)

    values = {
        "ticket": "WOT-2026-152h",
        "base_ref": world["base"],
        "tip_ref": world["tip"],
        "source_repo": world["source"],
        "clone_dir": tmp_path / "cwd otro é",
        "output": tmp_path / "bundle.md",
        "backlog": world["backlog"],
        "verify_json": world["verify"],
        "flt": world["flt"],
        "scope": world["scope"],
        "coordinator_measurement": world["measurement"],
        "bundle_limit_bytes": 100_000,
        "bundle_limit_source": "CLI",
        "part": True,
        "file_mode": False,
        "runner": recording_runner,
    }
    build_bundle(**values)
    assert all(kwargs.get("shell") is False for _, kwargs in calls)
    assert all("C:/Temp/co17_stage" not in command for command, _ in calls)


def test_verify_no_medido_step_is_rejected_without_bundle(tmp_path: Path) -> None:
    """M05: a NO_MEDIDO producer step is fail-closed, not merely a warning."""

    world = _world(tmp_path)
    payload = json.loads(Path(world["verify"]).read_text(encoding="utf-8"))
    payload["steps"]["focal_tests"] = {"status": "NO_MEDIDO", "rc": 0}
    Path(world["verify"]).write_text(json.dumps(payload), encoding="utf-8")
    output = tmp_path / "no-medido.md"
    with pytest.raises(BuildError, match="pasos no validos"):
        _build(world, tmp_path, output=output)
    assert not output.exists()


@pytest.mark.parametrize(
    "step",
    [
        {"status": "OK", "rc": 1},
        {"rc": 7},
        {"rc": 0},
        {"status": "MAYBE", "rc": 0},
        {"status": "OK", "rc": "0"},
        {"status": "OK", "rc": False},
        {"status": "OK", "rc": True},
    ],
)
def test_verify_receipt_requires_ok_zero_steps(
    tmp_path: Path, step: dict[str, object]
) -> None:
    """DoD 7 rejects every receipt step without exact OK and integer zero."""

    world = _world(tmp_path)
    payload = json.loads(Path(world["verify"]).read_text(encoding="utf-8"))
    payload["steps"]["focal_tests"] = step
    Path(world["verify"]).write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(BuildError, match="pasos no validos: focal_tests"):
        _build(world, tmp_path)


@pytest.mark.parametrize("root_rc", [False, 0.0, True])
def test_verify_receipt_root_requires_exact_integer_zero(
    tmp_path: Path, root_rc: object
) -> None:
    """P1 rejects boolean and float root rc values as non-contract receipts."""

    world = _world(tmp_path)
    payload = json.loads(Path(world["verify"]).read_text(encoding="utf-8"))
    payload["rc"] = root_rc
    Path(world["verify"]).write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(BuildError, match="GREEN/rc=0"):
        _build(world, tmp_path)


def test_bundle_limit_boundary_accepts_exact_bytes_and_rejects_below(
    tmp_path: Path,
) -> None:
    """M07: the exact final-bundle byte boundary is accepted."""

    world = _world(tmp_path)
    probe = tmp_path / "probe.md"
    _build(world, tmp_path, output=probe, bundle_limit_bytes=9999)
    exact = len(probe.read_bytes())
    exact_output = tmp_path / "exact.md"
    _build(world, tmp_path, bundle_limit_bytes=exact, output=exact_output)
    assert len(exact_output.read_bytes()) <= exact
    with pytest.raises(BuildError, match="excede limite"):
        _build(world, tmp_path, bundle_limit_bytes=exact - 1)


def test_backlog_match_requires_the_ticket_table_cell(tmp_path: Path) -> None:
    """M09: a dependency mention is not the ticket's contract row."""

    backlog = tmp_path / "backlog.md"
    backlog.write_text(
        "| Media | WOT-2026-999x | depende de WOT-2026-152h |\n"
        "| Media | WOT-2026-152h | contrato propio |\n",
        encoding="utf-8",
    )
    assert "| Media | WOT-2026-152h |" in _read_backlog_row(backlog, "WOT-2026-152h")
    backlog.write_text(
        "| Media | WOT-2026-999x | depende de WOT-2026-152h |\n",
        encoding="utf-8",
    )
    with pytest.raises(BuildError, match="ausente o duplicada"):
        _read_backlog_row(backlog, "WOT-2026-152h")


def test_scope_requires_limit_even_when_dod_is_present() -> None:
    """M11: ALCANCE must declare both covered DoD and LIMITE."""

    with pytest.raises(BuildError, match="DoD cubierto y LIMITE"):
        _validate_scope_text(
            "DoD cubierto: 2, 3, 7, 8 y 15.",
            "WOT-2026-152h",
        )


def test_clone_head_mismatch_is_rejected_before_bundle_write(tmp_path: Path) -> None:
    """M14: a runner-reported clone HEAD mismatch blocks the build."""

    world = _world(tmp_path)
    clone = tmp_path / "clone-mismatch"

    def mismatching_runner(command, **kwargs):
        result = _run(command, **kwargs)
        if (
            len(command) >= 5
            and command[0:2] == ["git", "-C"]
            and command[-2:] == ["rev-parse", "HEAD"]
            and Path(command[2]).resolve() == clone.resolve()
        ):
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="0" * 40 + "\n",
                stderr="",
            )
        return result

    output = tmp_path / "mismatch.md"
    with pytest.raises(BuildError, match="HEAD del clon discrepante"):
        _build(
            world, tmp_path, clone_dir=clone, output=output, runner=mismatching_runner
        )
    assert not output.exists()
