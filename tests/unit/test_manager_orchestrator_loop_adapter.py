"""Contract test for the motor adapter + profile of the portable process (WOT-2026-093e).

The adapter (``prompts/manager_orchestrator_loop.adapter_motor.md``) translates every
capability of the portable nucleo (``prompts/manager_orchestrator_loop.md``) to a REAL
command or file of this repo; the profile (``...profile_motor.json``) declares each
capability for the nucleus ``SCHEMA: perfil`` check.

This test REUSES the nucleo validator (``tests.unit.test_manager_orchestrator_loop_contract``)
instead of copying it: the schema has ONE executable definition, and a mutation only
counts if it crosses that same validator. The two mutations below run on COPIES in tmp.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest
from scripts.check_loop_execution import (
    DEFAULT_MIN_DISTINCT_BACKENDS,
    min_distinct_for,
)

from tests.unit.test_manager_orchestrator_loop_contract import _extract, _validate


ROOT = Path(__file__).resolve().parents[2]
NUCLEO = ROOT / "prompts" / "manager_orchestrator_loop.md"
ADAPTER = ROOT / "prompts" / "manager_orchestrator_loop.adapter_motor.md"
PROFILE = ROOT / "prompts" / "manager_orchestrator_loop.profile_motor.json"

CONTRACT_ID = "cid-manager-orchestrator-loop-adapter-motor-v1"
IMPLEMENTS = "cid-manager-orchestrator-loop-v1"
_SHA_RE = re.compile(r"[0-9a-f]{64}")

_REPO_PREFIXES = ("scripts/", "prompts/", "docs/", "tests/", ".agent/", "skills/")
_PATH_SUFFIXES = (".py", ".md", ".json", ".jsonl")
_CODE_SPAN_RE = re.compile(r"`([^`]+)`")
_SCRIPT_RE = re.compile(r"scripts/[A-Za-z0-9_./-]+\.py\Z")
_SUBCOMMAND_RE = re.compile(r"[a-z][a-z0-9-]*\Z")

# Paths that live in the DESTINO, not in the motor worktree: they CANNOT exist here.
# Declared with their motive so a NEW destino path in the table must be added here.
DESTINO_PATHS = {
    "<destino>/.agent/collaboration/backlog.md": "backlog vivo del DESTINO (estado operativo)",
    "<destino>/.agent/runtime/ensemble/scorecard.jsonl": "scorecard de rondas del DESTINO (runtime)",
    "<destino>/.agent/collaboration/backlog_inbox/": "buzon de tareas del DESTINO (estado operativo)",
}


def _perfil_schema() -> dict:
    """The ``SCHEMA: perfil`` block of the nucleo (single source via the contract test)."""
    schemas, _goods, _bads = _extract(NUCLEO)
    return schemas["perfil"]


def _capabilities() -> set[str]:
    """The capabilities the nucleo declares (its schema properties = its section 3)."""
    return set(_perfil_schema()["properties"]["capacidades"]["properties"])


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _adapter_rows(path: Path) -> dict[str, list[str]]:
    """capability -> its markdown table cells, for rows whose first cell is a capability."""
    caps = _capabilities()
    rows: dict[str, list[str]] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if cells and cells[0] in caps:
            rows[cells[0]] = cells
    return rows


def _assert_profile_valid(path: Path) -> None:
    errors = _validate(_load_json(path), _perfil_schema())
    assert not errors, f"perfil invalido contra SCHEMA: perfil: {errors}"


def _assert_one_row_per_capability(path: Path) -> None:
    caps = _capabilities()
    rows = _adapter_rows(path)
    missing = sorted(caps - set(rows))
    extra = sorted(set(rows) - caps)
    assert not missing, f"capacidades del nucleo sin fila en el adaptador: {missing}"
    assert not extra, f"filas que no son capacidad del nucleo: {extra}"
    for cap, cells in rows.items():
        assert len(cells) == 4, f"fila {cap} no tiene 4 columnas: {cells}"
        assert all(cells[1:]), f"fila {cap} con celdas vacias: {cells}"


def _assert_minimos(path: Path) -> None:
    profile = _load_json(path)
    expected = {t: min_distinct_for(t) for t in DEFAULT_MIN_DISTINCT_BACKENDS}
    assert profile["minimos_por_tipo"] == expected, (
        f"minimos_por_tipo divergen de min_distinct_for: "
        f"{profile['minimos_por_tipo']} != {expected}"
    )


def _assert_nucleo_sha(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    real = hashlib.sha256(NUCLEO.read_bytes()).hexdigest()
    cited = set(_SHA_RE.findall(text))
    assert real in cited, f"el adaptador no cita el sha256 real del nucleo ({real})"


def _table_text(path: Path) -> str:
    """The adapter's markdown table rows: lines whose stripped form starts with ``|``."""
    return "\n".join(
        ln
        for ln in path.read_text(encoding="utf-8").splitlines()
        if ln.strip().startswith("|")
    )


def _cited_tokens(path: Path) -> list[tuple[str, str]]:
    """(span, token) for each token inside each backtick span of the adapter table."""
    return [
        (span, token.strip(";,()'\"[]{}"))
        for span in _CODE_SPAN_RE.findall(_table_text(path))
        for token in span.split()
    ]


def _assert_cited_paths_exist(path: Path) -> None:
    """Every source path cited in the table exists in the worktree (or is declared).

    A token ending in a source suffix that starts with a repo prefix must exist in
    THIS worktree; one that starts with ``<destino>/`` must be in ``DESTINO_PATHS``;
    any other such token is an unknown origin and fails the test.
    """
    checked = 0
    for span, token in _cited_tokens(path):
        if not token.endswith(_PATH_SUFFIXES):
            continue
        if token.startswith(_REPO_PREFIXES):
            assert (ROOT / token).exists(), (
                f"ruta citada pero inexistente en el worktree: {token!r} (span {span!r})"
            )
            checked += 1
        elif token.startswith("<destino>/"):
            assert token in DESTINO_PATHS, (
                f"ruta del DESTINO no declarada en DESTINO_PATHS: {token!r}"
            )
        else:
            raise AssertionError(
                f"ruta citada de origen desconocido: {token!r} (span {span!r})"
            )
    assert checked > 0, "el adaptador no cita ninguna ruta del repo: verde vacuo"


def _cited_subcommands(path: Path) -> list[tuple[str, str]]:
    """(script, subcommand) for scripts cited in the table as ``script.py <sub>``."""
    pairs: list[tuple[str, str]] = []
    for span, _token in _cited_tokens(path):
        parts = span.split()
        for idx, part in enumerate(parts):
            if not _SCRIPT_RE.match(part) or idx + 1 >= len(parts):
                continue
            sub = parts[idx + 1].strip(";,()'\"[]{}")
            if _SUBCOMMAND_RE.match(sub):
                pairs.append((part, sub))
    return pairs


def _assert_subcommands_in_parser(path: Path) -> None:
    """Each cited ``script.py <sub>`` must declare ``<sub>`` in its own parser."""
    seen = 0
    for script, sub in _cited_subcommands(path):
        text = (ROOT / script).read_text(encoding="utf-8")
        assert re.search(rf'add_parser\(\s*["\']{re.escape(sub)}["\']', text), (
            f"subcomando {sub!r} de {script!r} no aparece en su parser"
        )
        seen += 1
    assert seen > 0, "no se cito ningun script con subcomando: la prueba no midio nada"


def _without_line(text: str, predicate) -> str:
    """Rejoin the text without the first line matching ``predicate`` (LF-normalised)."""
    lines = text.splitlines()
    kept: list[str] = []
    dropped = False
    for line in lines:
        if not dropped and predicate(line):
            dropped = True
            continue
        kept.append(line)
    assert dropped, "la mutacion no encontro la linea a quitar"
    return "\n".join(kept) + "\n"


def test_profile_validates_against_nucleo_schema() -> None:
    _assert_profile_valid(PROFILE)


def test_profile_declares_every_capability() -> None:
    assert set(_load_json(PROFILE)["capacidades"]) == _capabilities()


def test_adapter_has_one_row_per_capability() -> None:
    _assert_one_row_per_capability(ADAPTER)


def test_adapter_declares_contract_and_implements() -> None:
    text = ADAPTER.read_text(encoding="utf-8")
    assert f"contract_id: {CONTRACT_ID}" in text
    assert IMPLEMENTS in text


def test_adapter_cites_real_nucleo_sha256() -> None:
    _assert_nucleo_sha(ADAPTER)


def test_profile_minimos_match_min_distinct_for() -> None:
    _assert_minimos(PROFILE)


def test_adapter_cited_paths_exist_in_worktree() -> None:
    _assert_cited_paths_exist(ADAPTER)


def test_adapter_cited_subcommands_exist_in_parser() -> None:
    _assert_subcommands_in_parser(ADAPTER)


def test_mutation_nonexistent_cited_path_fails(tmp_path: Path) -> None:
    text = ADAPTER.read_text(encoding="utf-8")
    target = "prompts/ensemble_loop.md"
    mutated = text.replace(target, "prompts/ensemble_loop_inexistente.md")
    assert mutated != text, "la mutacion no encontro la ruta citada"
    copy = tmp_path / ADAPTER.name
    copy.write_text(mutated, encoding="utf-8")
    with pytest.raises(AssertionError):
        _assert_cited_paths_exist(copy)


def test_mutation_dropping_a_capability_row_fails(tmp_path: Path) -> None:
    text = ADAPTER.read_text(encoding="utf-8")
    mutated = _without_line(text, lambda ln: ln.strip().startswith("| LECTOR_FS "))
    copy = tmp_path / ADAPTER.name
    copy.write_text(mutated, encoding="utf-8")
    with pytest.raises(AssertionError):
        _assert_one_row_per_capability(copy)


def test_mutation_changing_a_minimum_fails(tmp_path: Path) -> None:
    profile = _load_json(PROFILE)
    profile["minimos_por_tipo"]["code"] += 1
    copy = tmp_path / PROFILE.name
    copy.write_text(json.dumps(profile), encoding="utf-8")
    with pytest.raises(AssertionError):
        _assert_minimos(copy)
