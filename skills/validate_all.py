#!/usr/bin/env python3
"""Validator for the project micro-skills catalog.

Checks that every SKILL.md has valid frontmatter with the required fields:
- name: skill name
- version: semantic version
- description: short description
- author: skill author
- tags: list of tags
- role: operational role
- stage: lifecycle stage
- writes_memory: boolean memory flag
- quality_gate: boolean quality-gate flag
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


REQUIRED_FIELDS = {
    "name",
    "version",
    "description",
    "author",
    "tags",
    "role",
    "stage",
    "writes_memory",
    "quality_gate",
}

VALID_ROLES = {"builder", "manager", "shared", "user"}
VALID_STAGES = {
    "setup",
    "plan",
    "implement",
    "review",
    "quality",
    "close",
    "memory",
    "meta",
    "support",
}

SKILLS_DIR = Path(__file__).parent

AP_CANONICAL_PATH = SKILLS_DIR / "_shared" / "anti-patterns.md"

AP_REFS: dict[str, tuple[Path, str]] = {
    "code-rules": (
        SKILLS_DIR / "bui-implement-from-plan" / "references" / "code-rules.md",
        "Builder code rules",
    ),
    "review-checklist": (
        SKILLS_DIR / "man-review-implementation" / "references" / "review-checklist.md",
        "Manager review checklist",
    ),
}


def _extract_ap_ids_from_file(path: Path) -> set[str]:
    """Extract AP-NN identifiers from a text file."""
    if not path.exists():
        return set()
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    return set(re.findall(r"\bAP-\d{2}\b", content))


def check_ap_sync() -> list[str]:
    """Check that AP-NN IDs in derived files match the canonical inventory.

    Returns a list of warning messages (never errors -- this is advisory).
    """
    warnings: list[str] = []

    canonical_ids = _extract_ap_ids_from_file(AP_CANONICAL_PATH)
    if not canonical_ids:
        warnings.append(
            f"No se encontraron AP-NN en {AP_CANONICAL_PATH.relative_to(SKILLS_DIR)}"
        )
        return warnings

    for ref_path, ref_label in AP_REFS.values():
        ref_ids = _extract_ap_ids_from_file(ref_path)
        if not ref_ids:
            warnings.append(
                f"[AP-sync] {ref_label} ({ref_path.relative_to(SKILLS_DIR)}): "
                f"no contiene ningun AP-NN"
            )
            continue

        missing_in_ref = canonical_ids - ref_ids
        extra_in_ref = ref_ids - canonical_ids

        if missing_in_ref:
            warnings.append(
                f"[AP-sync] {ref_label}: faltan {', '.join(sorted(missing_in_ref))} "
                f"presentes en {AP_CANONICAL_PATH.relative_to(SKILLS_DIR)}"
            )
        if extra_in_ref:
            warnings.append(
                f"[AP-sync] {ref_label}: {', '.join(sorted(extra_in_ref))} "
                f"no existen en {AP_CANONICAL_PATH.relative_to(SKILLS_DIR)}"
            )

    return warnings


def extract_frontmatter(content: str) -> dict[str, object] | None:
    """Extract the frontmatter section from a SKILL.md file."""
    pattern = r"^---\s*\n(.*?)\n---\s*\n"
    match = re.search(pattern, content, re.DOTALL)
    if not match:
        return None

    frontmatter_text = match.group(1)
    result: dict[str, object] = {}

    for line in frontmatter_text.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        if ":" not in line:
            continue

        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()

        if value.startswith("[") and value.endswith("]"):
            value = [
                item.strip().strip('"').strip("'")
                for item in value[1:-1].split(",")
                if item.strip()
            ]
        else:
            value = value.strip('"').strip("'")
            if value.lower() in {"true", "false"}:
                value = value.lower() == "true"

        result[key] = value

    return result


def _validate_skill_file(skill_dir: Path) -> tuple[str | None, list[str]]:
    """Validate that SKILL.md exists and is readable."""
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.exists():
        return None, ["No existe SKILL.md"]

    try:
        return skill_file.read_text(encoding="utf-8-sig"), []
    except Exception as exc:
        return None, [f"Error leyendo archivo: {exc}"]


def _validate_frontmatter(content: str) -> tuple[dict[str, object] | None, list[str]]:
    """Extract and validate the frontmatter block."""
    frontmatter = extract_frontmatter(content)
    if frontmatter is None:
        return None, ["No se encontro frontmatter YAML valido (debe iniciar con ---)"]
    return frontmatter, []


def _validate_required_fields(frontmatter: dict[str, object]) -> list[str]:
    """Validate required fields are present."""
    missing_fields = REQUIRED_FIELDS - set(frontmatter.keys())
    if missing_fields:
        return [f"Faltan campos obligatorios: {', '.join(sorted(missing_fields))}"]
    return []


def _validate_field_content(frontmatter: dict[str, object]) -> list[str]:
    """Validate field types, enums and content."""
    errors: list[str] = []

    name = frontmatter.get("name")
    if not isinstance(name, str) or not name:
        errors.append("El campo 'name' debe ser un string no vacio")
    elif " " in name:
        errors.append("El campo 'name' no debe contener espacios (usar kebab-case)")

    version = frontmatter.get("version")
    if not re.match(r"^\d+\.\d+\.\d+$", str(version)):
        errors.append("El campo 'version' debe seguir formato semver (X.Y.Z)")

    tags = frontmatter.get("tags")
    if not isinstance(tags, list):
        errors.append("El campo 'tags' debe ser una lista")
    elif len(tags) == 0:
        errors.append("El campo 'tags' no debe estar vacio")

    role = frontmatter.get("role")
    if not isinstance(role, str) or role not in VALID_ROLES:
        errors.append("El campo 'role' debe ser uno de: builder, manager, shared, user")

    stage = frontmatter.get("stage")
    if not isinstance(stage, str) or stage not in VALID_STAGES:
        errors.append(
            "El campo 'stage' debe ser uno de: "
            "setup, plan, implement, review, quality, close, memory, meta, support"
        )

    writes_memory = frontmatter.get("writes_memory")
    if not isinstance(writes_memory, bool):
        errors.append("El campo 'writes_memory' debe ser booleano (true/false)")

    quality_gate = frontmatter.get("quality_gate")
    if not isinstance(quality_gate, bool):
        errors.append("El campo 'quality_gate' debe ser booleano (true/false)")

    return errors


def _validate_references_dir(skill_dir: Path) -> tuple[list[str], list[str]]:
    """Validate the references directory.

    references/ no es bloqueante: missing o .gitkeep-only become warnings.
    """
    references_dir = skill_dir / "references"
    if not references_dir.exists():
        return [], ["No existe carpeta 'references/'"]

    try:
        entries = [item for item in references_dir.iterdir() if item.name != ".gitkeep"]
    except OSError as exc:
        return [], [f"Error leyendo carpeta 'references/': {exc}"]

    if not entries:
        return [], ["Carpeta 'references/' solo contiene .gitkeep o esta vacia"]

    return [], []


def validate_skill(skill_dir: Path) -> tuple[bool, list[str], list[str]]:
    """Validate a single skill directory."""
    errors: list[str] = []
    warnings: list[str] = []

    content, file_errors = _validate_skill_file(skill_dir)
    errors.extend(file_errors)
    if not content:
        return False, errors, warnings

    frontmatter, fm_errors = _validate_frontmatter(content)
    errors.extend(fm_errors)
    if not frontmatter:
        return False, errors, warnings

    errors.extend(_validate_required_fields(frontmatter))
    errors.extend(_validate_field_content(frontmatter))
    ref_errors, ref_warnings = _validate_references_dir(skill_dir)
    errors.extend(ref_errors)
    warnings.extend(ref_warnings)

    return len(errors) == 0, errors, warnings


def validate_all_skills(verbose: bool = False) -> dict[str, object]:
    """Validate all skills in the skills directory."""
    results: dict[str, object] = {
        "total": 0,
        "valid": 0,
        "invalid": 0,
        "warnings": 0,
        "skills": [],
    }

    skill_dirs = [
        d
        for d in SKILLS_DIR.iterdir()
        if d.is_dir() and not d.name.startswith(".") and not d.name.startswith("_")
    ]

    for skill_dir in sorted(skill_dirs):
        if skill_dir.name in {"__pycache__", "scripts"}:
            continue

        results["total"] += 1
        is_valid, errors, warnings = validate_skill(skill_dir)

        skill_result = {
            "name": skill_dir.name,
            "valid": is_valid,
            "errors": errors,
            "warnings": warnings,
        }
        results["skills"].append(skill_result)

        if is_valid:
            results["valid"] += 1
        else:
            results["invalid"] += 1

        results["warnings"] += len(warnings)

    return results


def print_results(results: dict[str, object], verbose: bool = False) -> None:
    """Print validation results."""
    print("=" * 60)
    print("🔍 VALIDACIÓN DE MICRO-SKILLS")
    print("=" * 60)
    print("\n📊 Resumen:")
    print(f"   Total: {results['total']}")
    print(f"   ✅ Válidas: {results['valid']}")
    print(f"   ❌ Inválidas: {results['invalid']}")
    print(f"   ⚠️ Advertencias: {results.get('warnings', 0)}")

    if verbose or results["invalid"] > 0 or results.get("warnings", 0) > 0:
        print("\n[*] Detalles por skill:")
        for skill in results["skills"]:
            status = "✅" if skill["valid"] else "❌"
            print(f"\n   {status} {skill['name']}")

            if not skill["valid"]:
                for error in skill["errors"]:
                    print(f"      - {error}")
            elif verbose:
                print("      - OK")

            for warning in skill.get("warnings", []):
                print(f"      [!] {warning}")

    print("\n" + "=" * 60)

    if results["invalid"] == 0:
        print("[OK] ¡Todas las skills son válidas!")
    else:
        print(f"[X]  {results['invalid']} skill(s) con errores")

    print("=" * 60)


def main() -> int:
    """CLI entrypoint."""
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    verbose = "--verbose" in sys.argv
    json_output = "--json" in sys.argv
    check_ap = "--check-ap-sync" in sys.argv

    results = validate_all_skills(verbose=verbose)

    if check_ap:
        ap_warnings = check_ap_sync()
        results["ap_sync_warnings"] = ap_warnings
        results["warnings"] = results.get("warnings", 0) + len(ap_warnings)

    if json_output:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        print_results(results, verbose=verbose)

        if check_ap:
            ap_warnings = results.get("ap_sync_warnings", [])
            if ap_warnings:
                print("\n--- AP-NN Sync Check ---")
                for w in ap_warnings:
                    print(f"   [!] {w}")
            else:
                print("\n--- AP-NN Sync Check ---")
                print("   [OK] Todos los AP-NN estan sincronizados")

    exit_code = 0 if results["invalid"] == 0 else 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
