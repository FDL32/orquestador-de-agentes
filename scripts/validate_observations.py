#!/usr/bin/env python3
"""
Validador de observations.jsonl

Verifica que cada entrada en observations.jsonl cumpla con el contrato definido
en skills/_shared/ap-schema.md.

Campos obligatorios:
- timestamp (ISO-8601)
- topic (kebab-case)
- signal (string no vacio)
- source (string)
- applies_to (code|mixed|docs|all)
- confidence (float 0.0-1.0)
- domain (string de lista permitida)

Campos opcionales:
- surface (array de strings)
- anti_pattern_id (string, obligatorio si la observacion eleva un bug a AP)

Uso:
    python scripts/validate_observations.py [--dry-run]

Salida:
- Exit 0: todas las entradas son validas
- Exit 1: al menos una entrada es invalida (se detiene en el primer error)
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


# Bootstrap repo_motor before importing sibling packages when executed by
# absolute path with cwd pointing at repo_destino.
#
# este modulo NO tenia bootstrap porque hasta ahora solo usaba
# stdlib. Al importar `bus.observation_domains` pasa a necesitarlo: la ruta
# fail-closed de `scripts/reconcile_portable_memory.py` invoca este fichero por
# RUTA ABSOLUTA del motor con el cwd apuntando al destino, y sin esto el import
# fallaria justo en la barrera que protege la memoria portable.
_MOTOR_ROOT_BOOTSTRAP = Path(__file__).resolve().parent.parent
if str(_MOTOR_ROOT_BOOTSTRAP) not in sys.path:
    sys.path.insert(0, str(_MOTOR_ROOT_BOOTSTRAP))

from bus.observation_domains import VALID_DOMAINS  # noqa: E402

# WOT-2026-047f: single source of truth for "is this record hook telemetry?".
# Defined ONCE in bus/portable_memory_archive.py and consumed by
# reconcile_portable_memory, memory_loader and now this validator. Duplicating
# the predicate would give two definitions of observation identity that would
# diverge in silence.
from bus.portable_memory_archive import is_hook_telemetry  # noqa: E402


# Valores permitidos para campos enum.
#
# OJO: `applies_to` y `deliverable_type` son vocabularios DISTINTOS. Este dice
# "docs"; el del work plan dice "documentation" y ademas tiene
# "research"/"analysis". No los unifiques: ver bus/observation_domains.py.
VALID_APPLIES_TO = {"code", "mixed", "docs", "all"}

# `VALID_DOMAINS` se importa de bus/observation_domains.py (fuente unica,
# origen: LEA-2026-002o). Era un literal duplicado en tres scripts, y ninguno estaba
# atado al enrutado de bus/review_observations.py.
VALID_IMPACTS = {"low", "medium", "high"}
VALID_CATEGORIES = {"convention", "decision", "fact", "pattern"}

# WOT-2026-045f: vigencia de una leccion. Opcional -- su AUSENCIA es la
# migracion implicita: las ~185 entradas existentes sin este campo se tratan
# como "active" (ver validate_status), nunca como error de schema. Decision
# tomada por DESIGN_REVIEW (3 lentes, loop-id EXPLORATORY-vigencia-schema-045f,
# convergencia 3/3 sin discrepancia).
VALID_STATUSES = {"active", "refined", "refuted", "superseded"}

# Patron para timestamp ISO-8601
ISO8601_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?$"
)

# Patron para topic kebab-case
KEBAB_CASE_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")

# AP-style observations declare the anti-pattern in the signal text itself.
AP_SIGNAL_PATTERN = re.compile(r"^\s*AP-\d{2}\b")


def validate_timestamp(value: Any) -> str | None:
    """Validate ISO-8601 timestamp."""
    if not isinstance(value, str):
        return "timestamp debe ser string"
    if not ISO8601_PATTERN.match(value):
        return f"timestamp '{value}' no es ISO-8601 valido"
    try:
        # Intentar parsear para verificar validez
        stamp = value.replace("Z", "+00:00")
        datetime.fromisoformat(stamp)
    except ValueError:
        return f"timestamp '{value}' no se puede parsear"
    return None


def validate_topic(value: Any) -> str | None:
    """Validate topic field (kebab-case)."""
    if not isinstance(value, str):
        return "topic debe ser string"
    if not value:
        return "topic no puede estar vacio"
    if not KEBAB_CASE_PATTERN.match(value):
        return f"topic '{value}' debe ser kebab-case (ej. 'mi-patron')"
    return None


def validate_signal(value: Any) -> str | None:
    """Validate signal field (non-empty string)."""
    if not isinstance(value, str):
        return "signal debe ser string"
    if not value.strip():
        return "signal no puede estar vacio"
    return None


def validate_source(value: Any) -> str | None:
    """Validate source field."""
    if not isinstance(value, str):
        return "source debe ser string"
    if not value.strip():
        return "source no puede estar vacio"
    return None


def validate_applies_to(value: Any) -> str | None:
    """Validate applies_to field (enum)."""
    if not isinstance(value, str):
        return "applies_to debe ser string"
    if value not in VALID_APPLIES_TO:
        return f"applies_to '{value}' debe ser uno de: {', '.join(sorted(VALID_APPLIES_TO))}"
    return None


def validate_confidence(value: Any) -> str | None:
    """Validate confidence field (float 0.0-1.0)."""
    if not isinstance(value, (int, float)):
        return "confidence debe ser numero"
    if not (0.0 <= value <= 1.0):
        return f"confidence {value} debe estar en rango [0.0, 1.0]"
    return None


def validate_domain(value: Any) -> str | None:
    """Validate domain field (enum)."""
    if not isinstance(value, str):
        return "domain debe ser string"
    if value not in VALID_DOMAINS:
        return f"domain '{value}' debe ser uno de: {', '.join(sorted(VALID_DOMAINS))}"
    return None


def validate_impact(value: Any) -> str | None:
    """Validate impact field (optional enum: low|medium|high)."""
    if value is None:
        return None
    if not isinstance(value, str):
        return "impact debe ser string"
    if value not in VALID_IMPACTS:
        return f"impact '{value}' debe ser uno de: {', '.join(sorted(VALID_IMPACTS))}"
    return None


def validate_category(value: Any) -> str | None:
    """Validate category field (legacy enum)."""
    if not isinstance(value, str):
        return "category debe ser string"
    if value not in VALID_CATEGORIES:
        return (
            f"category '{value}' debe ser uno de: {', '.join(sorted(VALID_CATEGORIES))}"
        )
    return None


def validate_source_ticket(value: Any) -> str | None:
    """Validate source_ticket field."""
    if not isinstance(value, str):
        return "source_ticket debe ser string"
    if not value.strip():
        return "source_ticket no puede estar vacio"
    return None


def validate_surface(value: Any) -> str | None:
    """Validate surface field (optional array of strings)."""
    if value is None:
        return None
    if not isinstance(value, list):
        return "surface debe ser array de strings"
    for item in value:
        if not isinstance(item, str):
            return "cada elemento de surface debe ser string"
    return None


def validate_status(value: Any) -> str | None:
    """Validate status field (optional enum: active|refined|refuted|superseded).

    WOT-2026-045f: la AUSENCIA del campo es valida (equivale a "active" por
    defecto implicito -- no rompe el archive existente). Si el campo SI esta
    presente, se valida contra el enum, igual que ya hace `validate_impact`.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return "status debe ser string"
    if value not in VALID_STATUSES:
        return f"status '{value}' debe ser uno de: {', '.join(sorted(VALID_STATUSES))}"
    return None


def validate_id_ref(value: Any, field_name: str) -> str | None:
    """Validate a field that references another entry's stable `id` (string).

    Used for `refuted_by` / `superseded_by` (WOT-2026-045f): a single `id`
    naming the newer entry that invalidates this one.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return f"{field_name} debe ser string"
    if not value.strip():
        return f"{field_name} no puede estar vacio"
    return None


def validate_id_ref_array(value: Any, field_name: str) -> str | None:
    """Validate a field that is an array of `id` references (strings).

    Used for `supersedes` / `refines` / `related` (WOT-2026-045f): declared on
    the NEW entry pointing at older entries it relates to -- the archive stays
    append-only, so the old entry is never edited to carry the reverse link.
    """
    if value is None:
        return None
    if not isinstance(value, list):
        return f"{field_name} debe ser array de strings"
    for item in value:
        if not isinstance(item, str) or not item.strip():
            return f"cada elemento de {field_name} debe ser un id (string no vacio)"
    return None


def validate_anti_pattern_id(value: Any, has_anti_pattern_ref: bool) -> str | None:
    """
    Validate anti_pattern_id field (optional, but required if elevating bug to AP).

    For now, we only validate format (AP-NN pattern) since we don't cross-reference
    with anti-patterns.md in this lightweight validator.
    """
    if value is None:
        if has_anti_pattern_ref:
            return (
                "falta anti_pattern_id para una observacion que escala a AP; "
                "debe referenciar un ID canonico existente"
            )
        return None

    if not isinstance(value, str):
        return "anti_pattern_id debe ser string"

    # Validate AP-NN format
    if not re.match(r"^AP-\d{2}$", value):
        return f"anti_pattern_id '{value}' debe tener formato AP-NN (ej. AP-09)"

    known_ids = _load_known_anti_pattern_ids()
    if value not in known_ids:
        return f"anti_pattern_id '{value}' no existe en skills/_shared/anti-patterns.md"

    return None


def _load_known_anti_pattern_ids() -> set[str]:
    """Load canonical AP ids from skills/_shared/anti-patterns.md."""
    anti_patterns_path = (
        Path(__file__).resolve().parent.parent
        / "skills"
        / "_shared"
        / "anti-patterns.md"
    )
    if not anti_patterns_path.exists():
        return set()

    ids: set[str] = set()
    try:
        for line in anti_patterns_path.read_text(encoding="utf-8").splitlines():
            match = re.match(r"^##\s+(AP-\d{2})\s+-\s+", line.strip())
            if match:
                ids.add(match.group(1))
    except OSError:
        return set()
    return ids


def _requires_anti_pattern_id(record: dict[str, Any]) -> bool:
    """Return True when the observation is explicitly an AP-style finding."""
    topic = str(record.get("topic", ""))
    signal = str(record.get("signal", ""))
    return bool(AP_SIGNAL_PATTERN.match(topic) or AP_SIGNAL_PATTERN.match(signal))


def _validate_vigency_fields(
    record: dict[str, Any], line_num: int, errors: list[str]
) -> None:
    """Validate the WOT-2026-045f vigency fields (all optional).

    Extracted out of `_validate_optional_schema_fields` to keep that
    function's branch count under the ruff C901 threshold -- this group of
    fields is one cohesive concern (vigency/relations), not six unrelated
    checks bolted onto the same function.
    """
    if "status" in record:
        error = validate_status(record["status"])
        if error:
            errors.append(f"linea {line_num}: {error}")

    for field_name in ("refuted_by", "superseded_by"):
        if field_name in record:
            error = validate_id_ref(record[field_name], field_name)
            if error:
                errors.append(f"linea {line_num}: {error}")

    for field_name in ("supersedes", "refines", "related"):
        if field_name in record:
            error = validate_id_ref_array(record[field_name], field_name)
            if error:
                errors.append(f"linea {line_num}: {error}")


def _validate_fields(
    record: dict[str, Any],
    line_num: int,
    validators: dict[str, Any],
    errors: list[str],
) -> None:
    """Validate a set of required fields and append errors in place."""
    for field_name, validator in validators.items():
        if field_name not in record:
            errors.append(f"linea {line_num}: falta campo obligatorio '{field_name}'")
            continue
        error = validator(record[field_name])
        if error:
            errors.append(f"linea {line_num}: {error}")


def _validate_optional_schema_fields(
    record: dict[str, Any], line_num: int, errors: list[str]
) -> None:
    """Validate optional schema fields used by modern observations."""
    if "surface" in record:
        error = validate_surface(record["surface"])
        if error:
            errors.append(f"linea {line_num}: {error}")

    if "impact" in record and record["impact"] is not None:
        error = validate_impact(record["impact"])
        if error:
            errors.append(f"linea {line_num}: {error}")

    _validate_vigency_fields(record, line_num, errors)

    if "anti_pattern_id" in record or _requires_anti_pattern_id(record):
        error = validate_anti_pattern_id(
            record.get("anti_pattern_id"),
            has_anti_pattern_ref=_requires_anti_pattern_id(record),
        )
        if error:
            errors.append(f"linea {line_num}: {error}")


def validate_observation(
    record: dict[str, Any],
    line_num: int,
    *,
    strict: bool = True,
) -> list[str]:
    """
    Validate a single observation record.

    Accepts both canonical schema (domain-based) and legacy schema
    (category-based) entries. Returns list of error messages (empty if valid).
    """
    errors = []

    _validate_fields(
        record,
        line_num,
        {
            "timestamp": validate_timestamp,
            "signal": validate_signal,
            "source": validate_source,
        },
        errors,
    )

    if strict:
        has_domain = "domain" in record
        has_category = "category" in record

        if has_domain:
            _validate_fields(
                record,
                line_num,
                {
                    "topic": validate_topic,
                    "domain": validate_domain,
                    "confidence": validate_confidence,
                    "applies_to": validate_applies_to,
                    "source_ticket": validate_source_ticket,
                },
                errors,
            )
        elif has_category:
            _validate_fields(
                record,
                line_num,
                {
                    "topic": validate_topic,
                    "category": validate_category,
                    "source_ticket": validate_source_ticket,
                },
                errors,
            )
        else:
            _validate_fields(
                record,
                line_num,
                {
                    "topic": validate_topic,
                    "domain": validate_domain,
                    "confidence": validate_confidence,
                    "applies_to": validate_applies_to,
                    "source_ticket": validate_source_ticket,
                },
                errors,
            )

        _validate_optional_schema_fields(record, line_num, errors)

    return errors


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """``object_pairs_hook`` for ``json.loads``: raise on a duplicate key.

    Before: ``pairs`` is the raw list of (key, value) tuples json.loads
    extracted from a single JSON object, IN ORDER, before building a dict.
    During: counts key occurrences; if any key appears more than once,
    raises ValueError naming the duplicated key (RFC 8259 leaves repeated
    keys as undefined behavior -- json.loads's default dict construction
    would otherwise silently keep the LAST value and drop the first).
    After: returns a plain dict identical to what json.loads would have
    built anyway, when no key repeats.
    """
    seen: dict[str, int] = {}
    for key, _value in pairs:
        seen[key] = seen.get(key, 0) + 1
    duplicated = [key for key, count in seen.items() if count > 1]
    if duplicated:
        raise ValueError(f"clave JSON duplicada: {', '.join(sorted(duplicated))}")
    return dict(pairs)


def validate_file(
    observations_path: Path, *, strict: bool = True
) -> tuple[bool, list[str]]:
    """
    Validate entire observations.jsonl file.

    Returns (success, errors) where success is True if all entries are valid.
    """
    if not observations_path.exists():
        return True, [
            f"Archivo {observations_path} no existe (no es error, es archivo opcional)"
        ]

    errors = []
    line_num = 0

    try:
        content = observations_path.read_text(encoding="utf-8")
    except OSError as e:
        return False, [f"Error leyendo archivo: {e}"]

    for raw_line in content.splitlines():
        line_num += 1
        line = raw_line.strip()

        # Skip empty lines
        if not line:
            continue

        # Parse JSON -- object_pairs_hook catches duplicate keys within a
        # single JSON object. json.loads's default dict construction keeps
        # the LAST value of a repeated key and silently drops the first
        # (undefined behavior per RFC 8259) -- a two-value applies_to or
        # domain entry would validate as if only the kept value existed.
        # WOT-2026-067p.
        try:
            record = json.loads(line, object_pairs_hook=_reject_duplicate_keys)
        except json.JSONDecodeError as e:
            errors.append(f"linea {line_num}: JSON invalido: {e}")
            continue
        except ValueError as e:
            errors.append(f"linea {line_num}: {e}")
            continue

        # Must be a dict
        if not isinstance(record, dict):
            errors.append(
                f"linea {line_num}: entrada debe ser objeto JSON, no {type(record).__name__}"
            )
            continue

        # WOT-2026-047f: skip hook telemetry by PROVENANCE, never by label.
        # The default target is the GITIGNORED BUFFER where hooks dump
        # tool-call telemetry; that telemetry legitimately lacks domain/
        # confidence/applies_to/source_ticket and is not a lesson. Reporting it
        # as 3100 schema errors made a close session diagnose "schema drift in
        # portable memory" -- a FALSE diagnosis that nearly opened a migration
        # ticket for a non-existent problem.
        #
        # is_hook_telemetry ANDs four conditions on purpose, so a hand-written
        # lesson (which carries id/source_ticket) is never skipped. Filtering by
        # `topic` alone would mask forever any legitimate lesson using that
        # topic: a false POSITIVE (noise) traded for a false NEGATIVE (a lesson
        # lost in silence), and the risk asymmetry runs the other way.
        if is_hook_telemetry(record):
            continue

        # Validate fields
        line_errors = validate_observation(record, line_num, strict=strict)
        errors.extend(line_errors)

    return len(errors) == 0, errors


def main() -> int:
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Validar observations.jsonl contra el contrato ap-schema.md"
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Aplicar el contrato AP completo en observaciones modernas",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Solo mostrar errores, no fallar (exit 0 siempre)",
    )
    parser.add_argument(
        "--file",
        type=Path,
        default=None,
        help="Ruta al archivo observations.jsonl (default: .agent/runtime/memory/observations.jsonl)",
    )

    args = parser.parse_args()

    # Resolve path
    if args.file:
        observations_path = args.file
    else:
        # Default path
        script_dir = Path(__file__).parent.parent
        observations_path = (
            script_dir / ".agent" / "runtime" / "memory" / "observations.jsonl"
        )

    # Validate
    _success, errors = validate_file(observations_path, strict=args.strict)

    # Report
    if errors:
        # WOT-2026-066r: name the ABSOLUTE path being audited before the
        # error list. Without --file, the default resolves against the
        # MOTOR root regardless of the invoker's cwd -- an agent running
        # this from a destino's root could otherwise believe it audited
        # the destino's buffer when it audited the motor's, producing a
        # false drift diagnosis (line numbers that don't exist in the real
        # destino file). Naming the path makes that misreading impossible
        # without changing the default resolution itself (deliberate
        # choice over resolving-by-invoker-root, which would silently
        # change behavior for any existing script/prose depending on it).
        print(
            f"Auditando: {observations_path.resolve()}",
            file=sys.stderr,
        )
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)

        if args.dry_run:
            print(
                "\n[DRY-RUN] Errores encontrados pero exit 0 (modo solo-informe)",
                file=sys.stderr,
            )
            return 0
        else:
            print(
                f"\nValidacion FALLIDA: {len(errors)} error(es) encontrado(s)",
                file=sys.stderr,
            )
            return 1

    # Success
    print(
        f"Validacion EXITOSA: {observations_path.relative_to(observations_path.parent.parent.parent)} es valido"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
