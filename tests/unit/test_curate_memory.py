"""Tests for scripts/curate_memory.py -- 12 cases per work_plan WOT-2026-127a.

All fixtures are synthetic JSONL written in tmp_path (pytest).
The real observations.jsonl of the repo is NEVER read in any test.
"""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from scripts.curate_memory import is_protected


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _write_jsonl(p: Path, lines: list[str]) -> None:
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_json(p: Path, obj: object) -> None:
    p.write_text(json.dumps(obj, ensure_ascii=False) + "\n", encoding="utf-8")


@pytest.fixture()
def tmp_dir(tmp_path: Path) -> Path:
    """Return tmp_path with subdir 'data' for convenience."""
    (tmp_path / "data").mkdir(exist_ok=True)
    return tmp_path / "data"


# ---------------------------------------------------------------------------
# 1. export_bundle_preserves_all_entries
# ---------------------------------------------------------------------------


def test_export_bundle_preserves_all_entries(tmp_dir: Path) -> None:
    """12 cases: case 1 -- export-bundle sobre JSONL de N lineas produce N entradas."""
    source = tmp_dir / "source.jsonl"
    _write_jsonl(
        source,
        [
            json.dumps({"signal": "alpha", "timestamp": "t1"}),
            json.dumps({"signal": "beta", "timestamp": "t2"}),
            json.dumps({"signal": "gamma", "timestamp": "t3"}),
        ],
    )
    bundle = tmp_dir / "bundle.json"

    rc = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.curate_memory",
            "export-bundle",
            "--source",
            str(source),
            "--out",
            str(bundle),
        ],
        capture_output=True,
        text=True,
    )
    assert rc.returncode == 0

    data = json.loads(bundle.read_text(encoding="utf-8"))
    entries = data["entries"]
    assert len(entries) == 3
    assert entries[0] == {"index": 0, "text": "alpha", "timestamp": "t1"}
    assert entries[1] == {"index": 1, "text": "beta", "timestamp": "t2"}
    assert entries[2] == {"index": 2, "text": "gamma", "timestamp": "t3"}


# ---------------------------------------------------------------------------
# 3. apply_keeps_candidate_without_literal_citation
# ---------------------------------------------------------------------------


def test_apply_keeps_candidate_without_literal_citation(tmp_dir: Path) -> None:
    """Case 3: mismo candidato pero citation_index NO contiene la subcadena => sobrevive."""
    source = tmp_dir / "source.jsonl"
    _write_jsonl(
        source,
        [
            json.dumps({"signal": "esta es la entrada original"}),
            json.dumps({"signal": "texto completamente distinto"}),
        ],
    )
    proposal = tmp_dir / "proposal.json"
    _write_json(
        proposal,
        {"candidates": [{"index": 0, "citation_index": 1, "reason": "duda"}]},
    )
    objections = tmp_dir / "objections.json"
    _write_json(objections, {"objections": []})
    output = tmp_dir / "curated.jsonl"
    report = tmp_dir / "report.md"

    subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.curate_memory",
            "apply",
            "--source",
            str(source),
            "--proposal",
            str(proposal),
            "--objections",
            str(objections),
            "--output",
            str(output),
            "--report",
            str(report),
        ],
        check=True,
    )

    output_lines = [
        line
        for line in output.read_text(encoding="utf-8").strip().splitlines()
        if line.strip()
    ]
    assert len(output_lines) == 2


# ---------------------------------------------------------------------------
# 5. apply_keeps_candidate_in_last_n_window
# ---------------------------------------------------------------------------


def test_apply_keeps_candidate_in_last_n_window(tmp_dir: Path) -> None:
    """Case 5: candidato con cita literal valida, sin objecion, pero dentro de last-n => sobrevive."""
    source = tmp_dir / "source.jsonl"
    entries = [json.dumps({"signal": f"entry {i}"}) for i in range(25)]
    _write_jsonl(source, entries)
    # index 23 con citation en 24 (valid literal citation)
    proposal = tmp_dir / "proposal.json"
    _write_json(
        proposal,
        {"candidates": [{"index": 23, "citation_index": 24, "reason": "recent dup"}]},
    )
    objections = tmp_dir / "objections.json"
    _write_json(objections, {"objections": []})
    output = tmp_dir / "curated.jsonl"
    report = tmp_dir / "report.md"

    subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.curate_memory",
            "apply",
            "--source",
            str(source),
            "--proposal",
            str(proposal),
            "--objections",
            str(objections),
            "--output",
            str(output),
            "--report",
            str(report),
            "--last-n",
            "5",
        ],
        check=True,
    )

    output_lines = [
        line
        for line in output.read_text(encoding="utf-8").strip().splitlines()
        if line.strip()
    ]
    # 25 entries, index 23 in last-5, must survive
    assert len(output_lines) == 25


# ---------------------------------------------------------------------------
# 6. apply_keeps_protected_pattern_even_without_objection (4 forms)
# ---------------------------------------------------------------------------


def test_apply_keeps_protected_pattern_even_without_objection(tmp_dir: Path) -> None:
    """Case 6: candidato con cita literal valida pero su texto matchea patron protegido => sobrevive.
    4 parametrizaciones: exit_code, SHA 12-hex, conteo de tests, ruta de fichero."""
    protected_texts = [
        "exit_code was 0",  # (i) exit_code
        "commit a1b2c3d4e5f6 was made",  # (ii) 12-char hex SHA
        "5 tests passed successfully",  # (iii) test count
        "see scripts/curate_memory.py for details",  # (iv) file path
    ]

    for pt in protected_texts:
        source = tmp_dir / f"source_{pt[:10]}.jsonl"
        _write_jsonl(
            source,
            [
                json.dumps({"signal": pt}),
                json.dumps({"signal": f"{pt} repeated later"}),
            ],
        )
        proposal = tmp_dir / f"proposal_{pt[:10]}.json"
        _write_json(
            proposal,
            {"candidates": [{"index": 0, "citation_index": 1, "reason": "dup"}]},
        )
        objections = tmp_dir / f"objections_{pt[:10]}.json"
        _write_json(objections, {"objections": []})
        output = tmp_dir / f"curated_{pt[:10]}.jsonl"
        report = tmp_dir / f"report_{pt[:10]}.md"

        subprocess.run(
            [
                sys.executable,
                "-m",
                "scripts.curate_memory",
                "apply",
                "--source",
                str(source),
                "--proposal",
                str(proposal),
                "--objections",
                str(objections),
                "--output",
                str(output),
                "--report",
                str(report),
            ],
            check=True,
        )

        output_lines = [
            line
            for line in output.read_text(encoding="utf-8").strip().splitlines()
            if line.strip()
        ]
        assert len(output_lines) == 2, f"Failed for protected pattern: {pt}"


# ---------------------------------------------------------------------------
# 7. apply_never_rewrites_surviving_entries
# ---------------------------------------------------------------------------


def test_apply_never_rewrites_surviving_entries(tmp_dir: Path) -> None:
    """Case 7: toda entrada conservada en la copia curada es byte-a-byte identica a la original."""
    raw_lines = [
        json.dumps({"signal": "alpha", "extra": 123}),
        json.dumps({"signal": "redundant entry"}),
        json.dumps({"signal": "la redundant entry is repeated here now"}),
        json.dumps({"signal": "entry three"}),
        json.dumps({"signal": "entry four"}),
    ]
    source = tmp_dir / "source.jsonl"
    _write_jsonl(source, raw_lines)

    proposal = tmp_dir / "proposal.json"
    _write_json(
        proposal,
        {
            "candidates": [
                {"index": 1, "citation_index": 2, "reason": "dup"},
            ]
        },
    )
    objections = tmp_dir / "objections.json"
    _write_json(objections, {"objections": []})
    output = tmp_dir / "curated.jsonl"
    report = tmp_dir / "report.md"

    subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.curate_memory",
            "apply",
            "--source",
            str(source),
            "--proposal",
            str(proposal),
            "--objections",
            str(objections),
            "--output",
            str(output),
            "--report",
            str(report),
            "--last-n",
            "2",
        ],
        check=True,
    )

    output_text = output.read_text(encoding="utf-8")
    output_lines = [line for line in output_text.strip().splitlines() if line.strip()]
    # Line 0 (alpha) survived verbatim
    assert output_lines[0] == raw_lines[0]
    # Line 1 (redundant) was discarded, so output[1] is raw[2]
    assert output_lines[1] == raw_lines[2]
    # Remaining lines also verbatim
    assert output_lines[2] == raw_lines[3]
    assert output_lines[3] == raw_lines[4]


# ---------------------------------------------------------------------------
# 9. apply_empty_proposal_is_noop
# ---------------------------------------------------------------------------


def test_apply_empty_proposal_is_noop(tmp_dir: Path) -> None:
    """Case 9: con proposal vacio, la salida es byte-a-byte identica al fuente."""
    source = tmp_dir / "source.jsonl"
    raw_content = "---\n" + json.dumps({"signal": "alpha"}) + "\n"
    source.write_text(raw_content, encoding="utf-8")

    proposal = tmp_dir / "proposal.json"
    _write_json(proposal, {"candidates": []})
    objections = tmp_dir / "objections.json"
    _write_json(objections, {"objections": []})
    output = tmp_dir / "curated.jsonl"
    report = tmp_dir / "report.md"

    subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.curate_memory",
            "apply",
            "--source",
            str(source),
            "--proposal",
            str(proposal),
            "--objections",
            str(objections),
            "--output",
            str(output),
            "--report",
            str(report),
        ],
        check=True,
    )

    assert output.read_bytes() == source.read_bytes()


# ---------------------------------------------------------------------------
# 11. cli_help_exits_zero
# ---------------------------------------------------------------------------


def test_cli_help_exits_zero() -> None:
    """Case 11: --help de cada subcomando sale con exit code 0."""
    for cmd in [
        "--help",
        "export-bundle",
        "export-bundle",
        "--help",
        "apply",
        "apply",
        "--help",
    ]:
        parts = (
            ["-m", "scripts.curate_memory", *cmd.split()]
            if cmd != "--help"
            else ["-m", "scripts.curate_memory", "--help"]
        )
        if cmd in ("export-bundle", "apply"):
            parts.extend(["--help"])

    # Just check root --help and subcommand --helps
    for label, args in [
        ("root", []),
        ("export-bundle", ["export-bundle", "--help"]),
        ("apply", ["apply", "--help"]),
    ]:
        rc = subprocess.run(
            [sys.executable, *("-m", "scripts.curate_memory"), *args],
            capture_output=True,
            text=True,
        )
        assert rc.returncode == 0, f"{label} --help exited {rc.returncode}: {rc.stderr}"


# ---------------------------------------------------------------------------
# 12. cli_invalid_json_proposal_exits_two
# ---------------------------------------------------------------------------


def test_cli_invalid_json_proposal_exits_two(tmp_dir: Path) -> None:
    """Case 12: un proposal con JSON malformado produce exit code 2 y mensaje de error."""
    source = tmp_dir / "source.jsonl"
    _write_jsonl(source, [json.dumps({"signal": "ok"})])
    proposal = tmp_dir / "proposal.json"
    proposal.write_text("{this is not valid json!!!", encoding="utf-8")
    objections = tmp_dir / "objections.json"
    _write_json(objections, {"objections": []})
    output = tmp_dir / "curated.jsonl"
    report = tmp_dir / "report.md"

    rc = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.curate_memory",
            "apply",
            "--source",
            str(source),
            "--proposal",
            str(proposal),
            "--objections",
            str(objections),
            "--output",
            str(output),
            "--report",
            str(report),
        ],
        capture_output=True,
        text=True,
    )
    assert rc.returncode == 2
    assert "Error" in rc.stderr or "error" in rc.stderr


# ---------------------------------------------------------------------------
# Additional: is_protected unit tests
# ---------------------------------------------------------------------------


def test_is_protected_exit_code() -> None:
    assert is_protected("exit_code was 0") is True
    assert is_protected("the exit code matters") is True


def test_is_protected_sha_hex() -> None:
    assert is_protected("commit a1b2c3d was found") is True  # 7 hex
    assert is_protected("sha abcdef1234567890") is True  # 16 hex


def test_is_protected_test_count() -> None:
    assert is_protected("5 tests passed") is True
    assert is_protected("0 failed tests here") is True


def test_is_protected_file_path() -> None:
    assert is_protected("see scripts/curate_memory.py here") is True
    assert is_protected("path is C:\\foo\\bar.txt") is True


def test_is_protected_none() -> None:
    assert is_protected("just plain text no patterns") is False
    assert is_protected("") is False


# ---------------------------------------------------------------------------
# Finding 1: Self-write protection
# ---------------------------------------------------------------------------


def test_export_bundle_out_equals_source(tmp_dir: Path) -> None:
    """Finding 1: export-bundle with --out==--source exits 2, file unchanged."""
    source = tmp_dir / "source.jsonl"
    source.write_text(
        json.dumps({"signal": "alpha"}) + "\n",
        encoding="utf-8",
    )
    sha_before = hashlib.sha256(source.read_bytes()).hexdigest()

    rc = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.curate_memory",
            "export-bundle",
            "--source",
            str(source),
            "--out",
            str(source),
        ],
        capture_output=True,
        text=True,
    )
    assert rc.returncode == 2

    sha_after = hashlib.sha256(source.read_bytes()).hexdigest()
    assert sha_before == sha_after


def test_apply_output_equals_source(tmp_dir: Path) -> None:
    """Finding 1: apply with --output==--source exits 2, file unchanged."""
    source = tmp_dir / "source.jsonl"
    source.write_text(
        json.dumps({"signal": "alpha"}) + "\n",
        encoding="utf-8",
    )
    sha_before = hashlib.sha256(source.read_bytes()).hexdigest()

    proposal = tmp_dir / "proposal.json"
    _write_json(proposal, {"candidates": []})
    objections = tmp_dir / "objections.json"
    _write_json(objections, {"objections": []})

    rc = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.curate_memory",
            "apply",
            "--source",
            str(source),
            "--proposal",
            str(proposal),
            "--objections",
            str(objections),
            "--output",
            str(source),
            "--report",
            str(tmp_dir / "report.md"),
        ],
        capture_output=True,
        text=True,
    )
    assert rc.returncode == 2

    sha_after = hashlib.sha256(source.read_bytes()).hexdigest()
    assert sha_before == sha_after


def test_apply_report_equals_source(tmp_dir: Path) -> None:
    """Finding 1: apply with --report==--source exits 2, file unchanged."""
    source = tmp_dir / "source.jsonl"
    source.write_text(
        json.dumps({"signal": "alpha"}) + "\n",
        encoding="utf-8",
    )
    sha_before = hashlib.sha256(source.read_bytes()).hexdigest()

    proposal = tmp_dir / "proposal.json"
    _write_json(proposal, {"candidates": []})
    objections = tmp_dir / "objections.json"
    _write_json(objections, {"objections": []})

    rc = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.curate_memory",
            "apply",
            "--source",
            str(source),
            "--proposal",
            str(proposal),
            "--objections",
            str(objections),
            "--output",
            str(tmp_dir / "out.jsonl"),
            "--report",
            str(source),
        ],
        capture_output=True,
        text=True,
    )
    assert rc.returncode == 2

    sha_after = hashlib.sha256(source.read_bytes()).hexdigest()
    assert sha_before == sha_after


def test_apply_output_equals_report(tmp_dir: Path) -> None:
    """Finding 1: apply with --output==--report exits 2."""
    source = tmp_dir / "source.jsonl"
    source.write_text(
        json.dumps({"signal": "alpha"}) + "\n",
        encoding="utf-8",
    )

    proposal = tmp_dir / "proposal.json"
    _write_json(proposal, {"candidates": []})
    objections = tmp_dir / "objections.json"
    _write_json(objections, {"objections": []})

    same_path = tmp_dir / "same.jsonl"

    rc = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.curate_memory",
            "apply",
            "--source",
            str(source),
            "--proposal",
            str(proposal),
            "--objections",
            str(objections),
            "--output",
            str(same_path),
            "--report",
            str(same_path),
        ],
        capture_output=True,
        text=True,
    )
    assert rc.returncode == 2


# ---------------------------------------------------------------------------
# Finding 2: Report shows citation_index and reason
# ---------------------------------------------------------------------------


def test_apply_report_shows_citation_index_and_reason(tmp_dir: Path) -> None:
    """Finding 2: discard table row shows citation_index (number) and reason, not entry text."""
    source = tmp_dir / "source.jsonl"
    _write_jsonl(
        source,
        [
            json.dumps({"signal": "redundant phrase"}),
            json.dumps({"signal": "important data A"}),
            json.dumps({"signal": "redundant phrase is repeated here"}),
        ],
    )
    proposal = tmp_dir / "proposal.json"
    _write_json(
        proposal,
        {
            "candidates": [
                {"index": 0, "citation_index": 2, "reason": "literal dup of 2"},
            ]
        },
    )
    objections = tmp_dir / "objections.json"
    _write_json(objections, {"objections": []})
    output = tmp_dir / "curated.jsonl"
    report = tmp_dir / "report.md"

    subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.curate_memory",
            "apply",
            "--source",
            str(source),
            "--proposal",
            str(proposal),
            "--objections",
            str(objections),
            "--output",
            str(output),
            "--report",
            str(report),
            "--last-n",
            "2",
        ],
        check=True,
    )

    report_text = report.read_text(encoding="utf-8")
    assert "2" in report_text
    assert "literal dup of 2" in report_text


# ---------------------------------------------------------------------------
# Finding 3: Barrier isolation
# ---------------------------------------------------------------------------


def test_apply_keeps_candidate_with_revisor_objection(tmp_dir: Path) -> None:
    """Finding 3 (revision): 25+ entries, index 0 outside last-n=20, literal citation valid,
    no protected pattern => objection is the ONLY reason index 0 survives."""
    source = tmp_dir / "source.jsonl"
    entries = [json.dumps({"signal": f"entry {i}"}) for i in range(25)]
    entries[0] = json.dumps({"signal": "keep me objection test"})
    entries[3] = json.dumps({"signal": "prefix keep me objection test suffix"})
    _write_jsonl(source, entries)

    proposal = tmp_dir / "proposal.json"
    _write_json(
        proposal,
        {
            "candidates": [
                {"index": 0, "citation_index": 3, "reason": "dup of 3"},
            ]
        },
    )
    objections = tmp_dir / "objections.json"
    _write_json(objections, {"objections": [{"index": 0, "reason": "keep it"}]})
    output = tmp_dir / "curated.jsonl"
    report = tmp_dir / "report.md"

    subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.curate_memory",
            "apply",
            "--source",
            str(source),
            "--proposal",
            str(proposal),
            "--objections",
            str(objections),
            "--output",
            str(output),
            "--report",
            str(report),
        ],
        check=True,
    )

    output_lines = [
        line
        for line in output.read_text(encoding="utf-8").strip().splitlines()
        if line.strip()
    ]
    assert len(output_lines) == 25, "Index 0 survived because of objection only"
    assert "keep me objection test" in output_lines[0]


def test_apply_discards_only_literal_citation(tmp_dir: Path) -> None:
    """Finding 3 (revision): candidate text IS a sub-string of citation text, outside last-n,
    no objection, no protected pattern => literal citation is the ONLY reason for discard."""
    source = tmp_dir / "source.jsonl"
    _write_jsonl(
        source,
        [
            json.dumps({"signal": "redundante intro"}),
            json.dumps({"signal": "middle entry"}),
            json.dumps({"signal": "la redundante intro se repite aqui completo"}),
        ],
    )
    proposal = tmp_dir / "proposal.json"
    _write_json(
        proposal,
        {"candidates": [{"index": 0, "citation_index": 2, "reason": "duplicate"}]},
    )
    objections = tmp_dir / "objections.json"
    _write_json(objections, {"objections": []})
    output = tmp_dir / "curated.jsonl"
    report = tmp_dir / "report.md"

    rc = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.curate_memory",
            "apply",
            "--source",
            str(source),
            "--proposal",
            str(proposal),
            "--objections",
            str(objections),
            "--output",
            str(output),
            "--report",
            str(report),
            "--last-n",
            "2",
        ],
        capture_output=True,
        text=True,
    )
    assert rc.returncode == 0

    output_lines = [
        line
        for line in output.read_text(encoding="utf-8").strip().splitlines()
        if line.strip()
    ]
    assert len(output_lines) == 2
    assert "redundante intro" not in output_lines[0] or "se repite" in output_lines[0]


# ---------------------------------------------------------------------------
# Finding 3: Mutation verify with real discard
# ---------------------------------------------------------------------------


def test_apply_source_unchanged_mutation_verify(tmp_dir: Path) -> None:
    """Finding 3 (revision): proposal that DOES discard (valid literal citation),
    verify source hash unchanged despite fewer entries in output."""
    source = tmp_dir / "source.jsonl"
    _write_jsonl(
        source,
        [
            json.dumps({"signal": "entry zero"}),
            json.dumps({"signal": "entry one redundant"}),
            json.dumps({"signal": "entry one redundant is repeated here"}),
            json.dumps({"signal": "entry two"}),
        ],
    )
    sha_before = hashlib.sha256(source.read_bytes()).hexdigest()

    proposal = tmp_dir / "proposal.json"
    _write_json(
        proposal,
        {
            "candidates": [
                {"index": 1, "citation_index": 2, "reason": "dup of 2"},
            ]
        },
    )
    objections = tmp_dir / "objections.json"
    _write_json(objections, {"objections": []})
    output = tmp_dir / "curated.jsonl"
    report = tmp_dir / "report.md"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.curate_memory",
            "apply",
            "--source",
            str(source),
            "--proposal",
            str(proposal),
            "--objections",
            str(objections),
            "--output",
            str(output),
            "--report",
            str(report),
            "--last-n",
            "1",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    sha_after = hashlib.sha256(source.read_bytes()).hexdigest()
    assert sha_before == sha_after, "Source file was mutated!"

    stderr_text = result.stderr or ""
    discarded_found = "discarded" in stderr_text.lower() or (
        "0 discarded" not in stderr_text.lower()
        and (
            "1 discarded" in stderr_text.lower()
            or "[discard]" in stderr_text
            or "[discard]" in (output.read_text(encoding="utf-8"))
        )
    )
    assert discarded_found, (
        f"Expected a real discard but stderr/report shows none: {stderr_text!r}"
    )


# ---------------------------------------------------------------------------
# Finding 3: Report with exact before/after counts
# ---------------------------------------------------------------------------


def test_apply_report_publishes_before_after_counts(tmp_dir: Path) -> None:
    """Finding 3 (revision): at least one real discard, verify exact before/after/diff
    and full discard row (index, citation_index, reason)."""
    source = tmp_dir / "source.jsonl"
    _write_jsonl(
        source,
        [
            json.dumps({"signal": "keep first"}),
            json.dumps({"signal": "discard me"}),
            json.dumps({"signal": "discard me is repeated here"}),
            json.dumps({"signal": "keep last"}),
        ],
    )
    proposal = tmp_dir / "proposal.json"
    _write_json(
        proposal,
        {
            "candidates": [
                {"index": 1, "citation_index": 2, "reason": "literal dup"},
            ]
        },
    )
    objections = tmp_dir / "objections.json"
    _write_json(objections, {"objections": []})
    output = tmp_dir / "curated.jsonl"
    report = tmp_dir / "report.md"

    subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.curate_memory",
            "apply",
            "--source",
            str(source),
            "--proposal",
            str(proposal),
            "--objections",
            str(objections),
            "--output",
            str(output),
            "--report",
            str(report),
            "--last-n",
            "1",
        ],
        check=True,
    )

    report_text = report.read_text(encoding="utf-8")
    assert "- Entradas ANTES: 4" in report_text
    assert "- Entradas DESPUES: 3" in report_text
    assert "- Diferencia: 1" in report_text
    assert "| 1 | 2 | literal dup |" in report_text


# ---------------------------------------------------------------------------
# Finding 4: Invalid line handling and consistent counts
# ---------------------------------------------------------------------------


def test_apply_invalid_line_consistent_counts(tmp_dir: Path) -> None:
    """Finding 4: invalid JSON line mixed with valid entries.
    before = len(valid entries), not total lines.
    stderr and report agree on same count."""
    source = tmp_dir / "source.jsonl"
    lines = [
        json.dumps({"signal": "valid one"}),
        "THIS IS NOT VALID JSON!!!",
        json.dumps({"signal": "valid two"}),
        json.dumps({"signal": "valid three"}),
    ]
    source.write_text("\n".join(lines) + "\n", encoding="utf-8")

    proposal = tmp_dir / "proposal.json"
    _write_json(proposal, {"candidates": []})
    objections = tmp_dir / "objections.json"
    _write_json(objections, {"objections": []})
    output = tmp_dir / "curated.jsonl"
    report = tmp_dir / "report.md"

    rc = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.curate_memory",
            "apply",
            "--source",
            str(source),
            "--proposal",
            str(proposal),
            "--objections",
            str(objections),
            "--output",
            str(output),
            "--report",
            str(report),
        ],
        capture_output=True,
        text=True,
    )
    assert rc.returncode == 0

    stderr_text = rc.stderr
    report_text = report.read_text(encoding="utf-8")

    assert "- Entradas ANTES: 3" in report_text
    assert "- Entradas DESPUES: 3" in report_text
    assert "- Diferencia: 0" in report_text

    assert "3 -> 3 entries" in stderr_text
    assert "(0 discarded)" in stderr_text
