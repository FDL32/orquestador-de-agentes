"""Contract test for the portable Manager-Builder process nucleo (WOT-2026-093c).

``prompts/manager_orchestrator_loop.md`` is a PORTABLE, general specification:
four JSON schemas that use a MINIMAL subset of JSON Schema (``type``,
``required``, ``properties``, ``enum``, ``items``, ``minItems``, ``minLength``)
plus at least a GOOD and a BAD example each; a portability grep; and the
``contract_id`` with the eleven phases of the user's pattern.

No ``jsonschema`` dependency: ``_validate`` implements ONLY that subset, and the
mutation tests below prove the checks have teeth (they exercise the same
validator production-facing structure uses).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from scripts.discover_skills import PROMPT_SUMMARY_SCAN_LINES, read_prompt_parts


ROOT = Path(__file__).resolve().parents[2]
NUCLEO = ROOT / "prompts" / "manager_orchestrator_loop.md"

CONTRACT_ID = "cid-manager-orchestrator-loop-v1"
SCHEMA_NAMES = {"perfil", "adjudicacion", "ronda_ficheros", "ronda_texto"}

_SCHEMA_RE = re.compile(r"SCHEMA: ([a-z_]+)")
_GOOD_RE = re.compile(r"EJEMPLO BUENO: ([a-z_]+)")
_BAD_RE = re.compile(r"EJEMPLO MALO: ([a-z_]+) -- (.+)")

PHASES = (
    "objetivo",
    "analisis",
    "estrategia",
    "bucle sobre la estrategia",
    "division en planes",
    "bucle sobre cada plan",
    "implantacion por riesgo ascendente",
    "bucle sobre el prompt del ejecutor",
    "ejecucion y revision por un modelo distinto",
    "mejora continua medible",
    "limites de autoridad",
)

FORBIDDEN = (
    (re.compile(r"WOT-"), "prefijo de ticket"),
    (re.compile(r"WP-"), "prefijo de ticket"),
    (re.compile(r"WT-"), "prefijo de ticket"),
    (re.compile(r"CTL-"), "prefijo de ticket"),
    (re.compile(r"EXF-"), "prefijo de ticket"),
    (re.compile(r"BA\d"), "clave de backend"),
    (re.compile(r"C:\\"), "ruta absoluta"),
    (re.compile(r"/c/"), "ruta absoluta"),
    (re.compile(r"/Users/"), "ruta absoluta"),
    (re.compile(r"\.py\b"), "nombre de script"),
    (re.compile(r"\bscripts/"), "ruta relativa del motor"),
    (re.compile(r"\bprompts/"), "ruta relativa del motor"),
)


def _validate(instance: object, schema: dict, path: str = "$") -> list[str]:
    """Minimal validator of the JSON Schema subset the nucleo uses."""
    errors: list[str] = []
    enum = schema.get("enum")
    if enum is not None and instance not in enum:
        errors.append(f"{path}: valor fuera del enum {enum}")
    errors.extend(_validate_typed(instance, schema, path))
    return errors


def _validate_typed(instance: object, schema: dict, path: str) -> list[str]:
    """Dispatch one instance to the check of its declared ``type``."""
    kind = schema.get("type")
    if kind == "object":
        return _validate_object(instance, schema, path)
    if kind == "array":
        return _validate_array(instance, schema, path)
    if kind == "string":
        return _validate_string(instance, schema, path)
    if kind == "integer":
        if not isinstance(instance, int) or isinstance(instance, bool):
            return [f"{path}: se esperaba entero"]
        return []
    if kind == "boolean" and not isinstance(instance, bool):
        return [f"{path}: se esperaba booleano"]
    return []


def _validate_object(instance: object, schema: dict, path: str) -> list[str]:
    if not isinstance(instance, dict):
        return [f"{path}: se esperaba objeto"]
    errors = [
        f"{path}: falta '{key}'"
        for key in schema.get("required", [])
        if key not in instance
    ]
    for key, sub in schema.get("properties", {}).items():
        if key in instance:
            errors.extend(_validate(instance[key], sub, f"{path}.{key}"))
    return errors


def _validate_array(instance: object, schema: dict, path: str) -> list[str]:
    if not isinstance(instance, list):
        return [f"{path}: se esperaba lista"]
    errors: list[str] = []
    min_items = schema.get("minItems", 0)
    if len(instance) < min_items:
        errors.append(f"{path}: menos de {min_items} elementos")
    items = schema.get("items")
    if items is not None:
        for idx, item in enumerate(instance):
            errors.extend(_validate(item, items, f"{path}[{idx}]"))
    return errors


def _validate_string(instance: object, schema: dict, path: str) -> list[str]:
    if not isinstance(instance, str):
        return [f"{path}: se esperaba cadena"]
    if len(instance) < schema.get("minLength", 0):
        return [f"{path}: mas corta que minLength"]
    return []


def _next_json_block(lines: list[str], start: int) -> dict | None:
    """The first ```json fenced block at or after ``start``."""
    j = start
    while j < len(lines) and lines[j].strip() != "```json":
        j += 1
    if j >= len(lines):
        return None
    j += 1
    buf: list[str] = []
    while j < len(lines) and lines[j].strip() != "```":
        buf.append(lines[j])
        j += 1
    return json.loads("\n".join(buf))


def _extract(path: Path) -> tuple[dict, dict, list[tuple[str, str, dict]]]:
    """Return (schemas, good examples, bad examples) keyed by schema name.

    ``bads`` is a LIST of ``(schema_name, reason, instance)`` so a schema may
    carry more than one bad example (the perfil keeps two).
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    schemas: dict[str, dict] = {}
    goods: dict[str, dict] = {}
    bads: list[tuple[str, str, dict]] = []
    for i, raw in enumerate(lines):
        line = raw.strip()
        if not line.startswith("**"):
            continue
        schema_match = _SCHEMA_RE.search(line)
        good_match = _GOOD_RE.search(line)
        bad_match = _BAD_RE.search(line)
        if schema_match:
            block = _next_json_block(lines, i + 1)
            assert block is not None, f"sin bloque json tras {line!r}"
            schemas[schema_match.group(1)] = block
        elif good_match:
            block = _next_json_block(lines, i + 1)
            assert block is not None, f"sin bloque json tras {line!r}"
            goods[good_match.group(1)] = block
        elif bad_match:
            block = _next_json_block(lines, i + 1)
            assert block is not None, f"sin bloque json tras {line!r}"
            bads.append((bad_match.group(1), bad_match.group(2), block))
    return schemas, goods, bads


def _assert_examples(path: Path) -> None:
    """Every GOOD example validates; every BAD example does NOT (>= 1 per schema)."""
    schemas, goods, bads = _extract(path)
    assert set(schemas) == SCHEMA_NAMES, f"esquemas hallados: {sorted(schemas)}"
    for name, instance in goods.items():
        errors = _validate(instance, schemas[name])
        assert not errors, f"EJEMPLO BUENO {name} no valida: {errors}"
    bad_names = {name for name, _reason, _instance in bads}
    for name in SCHEMA_NAMES:
        assert name in bad_names, f"se exige al menos un EJEMPLO MALO para {name}"
    for name, reason, instance in bads:
        errors = _validate(instance, schemas[name])
        assert errors, f"EJEMPLO MALO {name} ({reason}) valida y no deberia"


def _strip_summary(body: str) -> str:
    """Remove the PROMPT-SUMMARY block (same window the production parser uses)."""
    lines = body.splitlines(keepends=True)
    start = next((i for i, ln in enumerate(lines) if "<!-- PROMPT-SUMMARY" in ln), None)
    if start is None:
        return body
    window = range(start, min(len(lines), start + PROMPT_SUMMARY_SCAN_LINES))
    end = next((i for i in window if lines[i].strip() == "-->"), None)
    if end is None:
        return body
    return "".join(lines[:start] + lines[end + 1 :])


def _assert_portability(path: Path) -> None:
    """No repo-specific token in the body outside frontmatter and PROMPT-SUMMARY."""
    _fm, error, body, _offset = read_prompt_parts(path)
    assert error is None, error
    text = _strip_summary(body)
    hits: list[tuple[str, str]] = []
    for pattern, label in FORBIDDEN:
        for match in pattern.finditer(text):
            context = text[max(0, match.start() - 30) : match.end() + 30]
            hits.append((label, context.replace("\n", " ")))
    assert not hits, f"tokens no portables en el cuerpo: {hits}"


def _assert_contract_metadata(path: Path) -> None:
    """The nucleo declares the contract_id and the eleven phases."""
    body = path.read_text(encoding="utf-8")
    assert f"contract_id: {CONTRACT_ID}" in body
    lowered = body.lower()
    assert "once fases" in lowered, "el nucleo no menciona las once fases"
    missing = [token for token in PHASES if token not in lowered]
    assert not missing, f"fases del patron ausentes: {missing}"


def _write_copy(tmp_path: Path, text: str) -> Path:
    copy = tmp_path / "manager_orchestrator_loop.md"
    copy.write_text(text, encoding="utf-8")
    return copy


def _mutate_perfil_required(text: str) -> str:
    """Rename every ``"required"`` inside the perfil schema block (mutation i)."""
    lines = text.splitlines(keepends=True)
    start = next(i for i, ln in enumerate(lines) if "SCHEMA: perfil" in ln)
    j = start + 1
    while lines[j].strip() != "```json":
        j += 1
    j += 1
    while lines[j].strip() != "```":
        lines[j] = lines[j].replace('"required"', '"exigido"')
        j += 1
    return "".join(lines)


@pytest.mark.parametrize("nucleo", [NUCLEO])
def test_good_examples_validate_and_bad_examples_are_rejected(nucleo: Path) -> None:
    _assert_examples(nucleo)


@pytest.mark.parametrize("nucleo", [NUCLEO])
def test_body_is_portable(nucleo: Path) -> None:
    _assert_portability(nucleo)


@pytest.mark.parametrize("nucleo", [NUCLEO])
def test_contract_id_and_eleven_phases(nucleo: Path) -> None:
    _assert_contract_metadata(nucleo)


def test_mutation_removing_required_breaks_the_schema_rejection(tmp_path: Path) -> None:
    mutated = _mutate_perfil_required(NUCLEO.read_text(encoding="utf-8"))
    copy = _write_copy(tmp_path, mutated)
    with pytest.raises(AssertionError):
        _assert_examples(copy)


def test_mutation_ticket_token_breaks_the_portability_grep(tmp_path: Path) -> None:
    text = NUCLEO.read_text(encoding="utf-8") + "\nReferencia WOT-2026-000a.\n"
    copy = _write_copy(tmp_path, text)
    with pytest.raises(AssertionError):
        _assert_portability(copy)
