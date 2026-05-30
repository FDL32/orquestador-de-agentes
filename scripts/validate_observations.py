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


# Valores permitidos para campos enum
VALID_APPLIES_TO = {"code", "mixed", "docs", "all"}
VALID_DOMAINS = {
    "security-gates",
    "integration-tests",
    "protocol-handlers",
    "bus-architecture",
    "review-quality",
    "config-schema",
    "testing",
    "delivery-hygiene",
    "builder-contract",
}
VALID_IMPACTS = {"low", "medium", "high"}
VALID_CATEGORIES = {"convention", "decision", "fact", "pattern"}

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

        # Parse JSON
        try:
            record = json.loads(line)
        except json.JSONDecodeError as e:
            errors.append(f"linea {line_num}: JSON invalido: {e}")
            continue

        # Must be a dict
        if not isinstance(record, dict):
            errors.append(
                f"linea {line_num}: entrada debe ser objeto JSON, no {type(record).__name__}"
            )
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
