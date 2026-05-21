#!/usr/bin/env python3
"""Validador de micro-skills del sistema multi-agente.

Verifica que cada SKILL.md tenga frontmatter YAML vÃ¡lido con los campos requeridos:
- name: nombre de la skill
- version: versiÃ³n semÃ¡ntica
- description: descripciÃ³n breve
- author: autor de la skill
- tags: lista de etiquetas

Uso:
    python validate_all.py              # Valida todas las skills
    python validate_all.py --verbose    # Muestra detalles de cada skill
    python validate_all.py --json       # Output en formato JSON
"""

import json
import re
import sys
from pathlib import Path


# Campos obligatorios en el frontmatter
REQUIRED_FIELDS = {"name", "version", "description", "author", "tags"}

# Directorio base de skills
SKILLS_DIR = Path(__file__).parent


def extract_frontmatter(content: str) -> dict[str, any] | None:
    """Extrae el frontmatter YAML del contenido de un SKILL.md.

    El frontmatter debe estar delimitado por --- al inicio y final.

    Args:
        content: Contenido completo del archivo SKILL.md

    Returns:
        Diccionario con el frontmatter parseado, o None si no existe o es invÃ¡lido
    """
    # Buscar patrÃ³n ---\n...\n---
    pattern = r"^---\s*\n(.*?)\n---\s*\n"
    match = re.search(pattern, content, re.DOTALL)

    if not match:
        return None

    frontmatter_text = match.group(1)
    result = {}

    # Parsear lÃ­neas del frontmatter
    for line in frontmatter_text.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        # Buscar patrÃ³n key: value
        if ":" in line:
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip()

            # Parsear listas (tags: [item1, item2])
            if value.startswith("[") and value.endswith("]"):
                value = [
                    v.strip().strip('"').strip("'") for v in value[1:-1].split(",")
                ]
            else:
                # Quitar comillas si existen
                value = value.strip('"').strip("'")

            result[key] = value

    return result


def _validate_skill_file(skill_dir: Path) -> tuple[str | None, list[str]]:
    """Validate SKILL.md file existence and readability."""
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.exists():
        return None, ["No existe SKILL.md"]

    try:
        content = skill_file.read_text(encoding="utf-8-sig")
        return content, []
    except Exception as e:
        return None, [f"Error leyendo archivo: {e}"]


def _validate_frontmatter(content: str) -> tuple[dict | None, list[str]]:
    """Extract and validate frontmatter."""
    frontmatter = extract_frontmatter(content)
    if frontmatter is None:
        return None, ["No se encontrÃ³ frontmatter YAML vÃ¡lido (debe iniciar con ---)"]
    return frontmatter, []


def _validate_required_fields(frontmatter: dict) -> list[str]:
    """Validate required fields are present."""
    errors = []
    missing_fields = REQUIRED_FIELDS - set(frontmatter.keys())
    if missing_fields:
        errors.append(
            f"Faltan campos obligatorios: {', '.join(sorted(missing_fields))}"
        )
    return errors


def _validate_field_content(frontmatter: dict) -> list[str]:
    """Validate field types and content."""
    errors = []

    if "name" in frontmatter:
        name = frontmatter["name"]
        if not name or not isinstance(name, str):
            errors.append("El campo 'name' debe ser un string no vacÃ­o")
        elif " " in name:
            errors.append("El campo 'name' no debe contener espacios (usar kebab-case)")

    if "version" in frontmatter:
        version = frontmatter["version"]
        # Validar formato semver simple (X.Y.Z)
        if not re.match(r"^\d+\.\d+\.\d+$", str(version)):
            errors.append("El campo 'version' debe seguir formato semver (X.Y.Z)")

    if "tags" in frontmatter:
        tags = frontmatter["tags"]
        if not isinstance(tags, list):
            errors.append("El campo 'tags' debe ser una lista")
        elif len(tags) == 0:
            errors.append("El campo 'tags' no debe estar vacÃ­o")

    return errors


def _validate_references_dir(skill_dir: Path) -> list[str]:
    """Validate references directory exists."""
    references_dir = skill_dir / "references"
    if not references_dir.exists():
        return ["No existe carpeta 'references/'"]
    return []


def validate_skill(skill_dir: Path) -> tuple[bool, list[str]]:
    """Valida una skill individual.

    Args:
        skill_dir: Ruta al directorio de la skill

    Returns:
        Tupla (es_vÃ¡lida, lista_de_errores)
    """
    errors = []

    # Validate file
    content, file_errors = _validate_skill_file(skill_dir)
    errors.extend(file_errors)
    if not content:
        return False, errors

    # Validate frontmatter
    frontmatter, fm_errors = _validate_frontmatter(content)
    errors.extend(fm_errors)
    if not frontmatter:
        return False, errors

    # Validate fields
    errors.extend(_validate_required_fields(frontmatter))
    errors.extend(_validate_field_content(frontmatter))
    errors.extend(_validate_references_dir(skill_dir))

    return len(errors) == 0, errors


def validate_all_skills(verbose: bool = False) -> dict:
    """Valida todas las skills en el directorio.

    Args:
        verbose: Si es True, muestra informaciÃ³n detallada

    Returns:
        Diccionario con resultados de la validaciÃ³n
    """
    results = {"total": 0, "valid": 0, "invalid": 0, "skills": []}

    # Encontrar todos los directorios de skills
    skill_dirs = [
        d for d in SKILLS_DIR.iterdir() if d.is_dir() and not d.name.startswith(".")
    ]

    for skill_dir in sorted(skill_dirs):
        # Ignorar directorios especiales
        if skill_dir.name in ["__pycache__", "scripts"]:
            continue

        results["total"] += 1
        is_valid, errors = validate_skill(skill_dir)

        skill_result = {"name": skill_dir.name, "valid": is_valid, "errors": errors}
        results["skills"].append(skill_result)

        if is_valid:
            results["valid"] += 1
        else:
            results["invalid"] += 1

    return results


def print_results(results: dict, verbose: bool = False) -> None:
    """Imprime los resultados de la validaciÃ³n.

    Args:
        results: Diccionario con resultados
        verbose: Si es True, muestra detalles de cada skill
    """
    print("=" * 60)
    print("ðŸ” VALIDACIÃ“N DE MICRO-SKILLS")
    print("=" * 60)
    print("\nðŸ“Š Resumen:")
    print(f"   Total: {results['total']}")
    print(f"   âœ… VÃ¡lidas: {results['valid']}")
    print(f"   âŒ InvÃ¡lidas: {results['invalid']}")

    if verbose or results["invalid"] > 0:
        print("\n[*] Detalles por skill:")
        for skill in results["skills"]:
            status = "âœ…" if skill["valid"] else "âŒ"
            print(f"\n   {status} {skill['name']}")

            if not skill["valid"]:
                for error in skill["errors"]:
                    print(f"      - {error}")
            elif verbose:
                print("      - OK")

    print("\n" + "=" * 60)

    if results["invalid"] == 0:
        print("[OK] ¡Todas las skills son válidas!")
    else:
        print(f"[X]  {results['invalid']} skill(s) con errores")

    print("=" * 60)


def main():
    """FunciÃ³n principal."""
    # Fix encoding issues on Windows
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    verbose = "--verbose" in sys.argv
    json_output = "--json" in sys.argv

    results = validate_all_skills(verbose=verbose)

    if json_output:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        print_results(results, verbose=verbose)

    # Exit code: 0 si todo vÃ¡lido, 1 si hay errores
    sys.exit(0 if results["invalid"] == 0 else 1)


if __name__ == "__main__":
    main()
