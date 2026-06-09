#!/usr/bin/env python
"""
Ticket Prose Validator - Valida la calidad de redaccion de work_plan.md

Este validador detecta patrones de prosa problematicos en tickets de trabajo
y emite warnings con regla, evidencia y sugerencia. No bloquea el flujo,
solo advierte para mejorar la calidad antes del handoff.

Uso:
    python scripts/validate_ticket_prose.py [--work-plan PATH] [--json]

Salida:
    - Por defecto: warnings legibles en consola
    - Con --json: salida estructurada para consumo programatico
    - Exit code: 0 siempre (los warnings no bloquean)
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import TypedDict


class ProseWarning(TypedDict):
    """Estructura de un warning de prosa."""

    rule_id: str
    rule_name: str
    evidence: str
    suggestion: str


class ValidationResult(TypedDict):
    """Estructura del resultado de validacion."""

    warnings: list[ProseWarning]
    warning_count: int


# ============================================================================
# REGLAS DE PROSA - CATALOGO DE DETECCION
# ============================================================================


def detect_throat_clearing(content: str) -> list[ProseWarning]:
    """Detecta throat-clearing (preambulos redundantes).

    Before: Requiere contenido de work_plan.md como string.
    During: Busca frases de relleno como 'Este ticket tiene como objetivo',
            'En este documento vamos a', 'El proposito de este plan es'.
    After: Retorna lista de warnings con regla TP-PROSE-01.
    """
    warnings = []
    patterns = [
        r"Este\s+ticket\s+tien[e|e] como objetivo",
        r"En\s+este\s+documento\s+vamos\s+a",
        r"El\s+proposito\s+de\s+este\s+plan\s+es",
        r"A\s+continuacion\s+se\s+describe",
        r"El\s+presente\s+documento\s+tiene\s+por\s+objeto",
    ]
    for pattern in patterns:
        matches = re.finditer(pattern, content, re.IGNORECASE)
        warnings.extend(
            [
                ProseWarning(
                    rule_id="TP-PROSE-01",
                    rule_name="throat-clearing",
                    evidence=match.group(0)[:80],
                    suggestion="Ve directo al grano. Elimina el preambulo y empieza con el objetivo concreto.",
                )
                for match in matches
            ]
        )
    return warnings


def detect_vague_declarative(content: str) -> list[ProseWarning]:
    """Detecta declarativo vago (verbos debiles sin accion concreta).

    Before: Requiere contenido de work_plan.md como string.
    During: Busca verbos como 'mejorar', 'optimizar', 'reforzar' sin metrica.
    After: Retorna lista de warnings con regla TP-PROSE-02.
    """
    warnings = []
    # Patrones de verbos vagos sin metrica asociada
    vague_patterns = [
        r"\b(mejorar|optimizar|reforzar|fortalecer|consolidar|pulir)\b(?!.*(?:%|numero|cantidad|tiempo|segundos|ms|metrica|criterio))",
    ]
    for pattern in vague_patterns:
        matches = re.finditer(pattern, content, re.IGNORECASE)
        for match in matches:
            # Verificar que no haya una metrica cerca (en la misma linea)
            line = content[match.start() : content.find("\n", match.end())]
            if not any(
                m in line.lower()
                for m in ["%", "numero", "cantidad", "tiempo", "segundos", "ms"]
            ):
                warnings.append(
                    ProseWarning(
                        rule_id="TP-PROSE-02",
                        rule_name="declarativo-vago",
                        evidence=match.group(0)[:80],
                        suggestion="Especifica que significa concretamente: que metrica cambia, cuanto, como se mide.",
                    )
                )
    return warnings


def detect_imprecise_passive(content: str) -> list[ProseWarning]:
    """Detecta pasivo impreciso (voz pasiva sin agente claro).

    Before: Requiere contenido de work_plan.md como string.
    During: Busca construcciones pasivas como 'sera realizado', 'debe ser hecho'.
    After: Retorna lista de warnings con regla TP-PROSE-03.
    """
    warnings = []
    patterns = [
        r"\bsera\s+(realizado|hecho|ejecutado|llevado\s+a\s+cabo)\b",
        r"\bdebe\s+ser\s+(hecho|realizado|ejecutado)\b",
        r"\bse\s+debe\s+(hacer|realizar|ejecutar)\b",
        r"\bse\s+realizara\s+un[a|a]\s+",
    ]
    for pattern in patterns:
        matches = re.finditer(pattern, content, re.IGNORECASE)
        warnings.extend(
            [
                ProseWarning(
                    rule_id="TP-PROSE-03",
                    rule_name="pasivo-impreciso",
                    evidence=match.group(0)[:80],
                    suggestion="Usa voz activa y especifica el agente: 'Builder implementa X', 'Manager revisa Y'.",
                )
                for match in matches
            ]
        )
    return warnings


def detect_lazy_extremes(content: str) -> list[ProseWarning]:
    """Detecta extremos lazy (absolutos o vaguedad extrema).

    Before: Requiere contenido de work_plan.md como string.
    During: Busca palabras como 'todo', 'nada', 'algo', 'cosas', 'varios'.
    After: Retorna lista de warnings con regla TP-PROSE-04.
    """
    warnings = []
    patterns = [
        r"\b(todo|todos|todas)\b(?!.*(?:archivo|fase|etapa|paso|caso|test|warning|criterio|error))",
        r"\b(algo|algo\s+de)\b",
        r"\b(cosas|varias\s+cosas)\b",
        r"\b(varios|varias)\b(?!.*(?:archivo|fase|etapa|paso|test))",
        r"\b(muchas?|demasiadas?)\b",
    ]
    for pattern in patterns:
        matches = re.finditer(pattern, content, re.IGNORECASE)
        warnings.extend(
            [
                ProseWarning(
                    rule_id="TP-PROSE-04",
                    rule_name="extremos-lazy",
                    evidence=match.group(0)[:80],
                    suggestion="Se especifico: enumera los elementos concretos en lugar de usar terminos vagos.",
                )
                for match in matches
            ]
        )
    return warnings


def detect_diffuse_objective(content: str) -> list[ProseWarning]:
    """Detecta objetivo difuso (seccion Objetivo sin criterio verificable).

    Before: Requiere contenido de work_plan.md como string.
    During: Verifica que la seccion Objetivo exista y tenga criterios medibles.
    After: Retorna lista de warnings con regla TP-PROSE-05.
    """
    warnings = []
    # Buscar seccion Objetivo
    objective_match = re.search(r"##\s*Objetivo\s*\n(.*?)(?=##|\Z)", content, re.DOTALL)
    if objective_match:
        objective_text = objective_match.group(1)
        # Verificar si hay criterios verificables (comandos, tests, metricas)
        has_verifiable = any(
            pattern in objective_text.lower()
            for pattern in [
                "python",
                "test",
                "assert",
                "exit code",
                "%",
                "numero",
                "cantidad",
                "archivo",
                "ruta",
                "`",
            ]
        )
        if not has_verifiable and len(objective_text.strip()) > 20:
            warnings.append(
                ProseWarning(
                    rule_id="TP-PROSE-05",
                    rule_name="objetivo-difuso",
                    evidence=objective_text.strip()[:80],
                    suggestion="Anade criterios verificables: que comando/test demuestra que el objetivo se cumplio.",
                )
            )
    return warnings


def detect_missing_nongoals(content: str) -> list[ProseWarning]:
    """Detecta non-goals ausentes (seccion Non-goals vacia o inexistente).

    Before: Requiere contenido de work_plan.md como string.
    During: Verifica existencia y contenido de seccion Non-goals.
    After: Retorna lista de warnings con regla TP-PROSE-06.
    """
    warnings = []
    nongoals_match = re.search(
        r"##\s*Non-goals?\s*\n(.*?)(?=##|\Z)", content, re.DOTALL
    )
    if not nongoals_match:
        warnings.append(
            ProseWarning(
                rule_id="TP-PROSE-06",
                rule_name="non-goals-ausentes",
                evidence="Seccion Non-goals no encontrada",
                suggestion="Anade una seccion Non-goals con al menos 3 items explicitos de lo que NO haras.",
            )
        )
    elif len(nongoals_match.group(1).strip()) < 30:
        warnings.append(
            ProseWarning(
                rule_id="TP-PROSE-06",
                rule_name="non-goals-ausentes",
                evidence="Seccion Non-goals con contenido insuficiente",
                suggestion="Expande Non-goals: enumera claramente que queda fuera del alcance.",
            )
        )
    return warnings


def detect_nonverifiable_criteria(content: str) -> list[ProseWarning]:
    """Detecta criterio no verificable (Criterios de aceptacion sin comando/test).

    Before: Requiere contenido de work_plan.md como string.
    During: Verifica que Criterios de aceptacion cite comandos o tests literales.
    After: Retorna lista de warnings con regla TP-PROSE-07.
    """
    warnings = []
    criteria_match = re.search(
        r"##\s*Criterios?\s+de\s+aceptacion\s*\n(.*?)(?=##|\Z)", content, re.DOTALL
    )
    if criteria_match:
        criteria_text = criteria_match.group(1)
        # Verificar si hay comandos o tests citados
        has_command = any(
            pattern in criteria_text
            for pattern in ["python", "pytest", "ruff", "```", "`"]
        )
        if not has_command and len(criteria_text.strip()) > 20:
            warnings.append(
                ProseWarning(
                    rule_id="TP-PROSE-07",
                    rule_name="criterio-no-verificable",
                    evidence=criteria_text.strip()[:80],
                    suggestion="Cita comandos o tests literales: 'python script.py', 'pytest test_x.py -q'.",
                )
            )
    return warnings


def _extract_section(content: str, heading: str) -> str:
    """Extrae el contenido de una seccion por su heading exacto."""

    match = re.search(
        rf"##\s*{re.escape(heading)}\s*\n(.*?)(?=\n##|\Z)",
        content,
        re.DOTALL | re.IGNORECASE,
    )
    return match.group(1) if match else ""


def detect_scope_conditional(content: str) -> list[ProseWarning]:
    """Detecta alcance condicional en secciones criticas del plan.

    Before: Requiere contenido de work_plan.md como string.
    During: Busca clausulas como 'si existe', 'si se anade', 'si aplica' o 'si procede'
            en Objetivo, Fases, Criterios de aceptacion y Decision Arquitectonica.
    After: Retorna lista de warnings con regla TP-PROSE-12.
    """
    warnings = []
    conditional_pattern = re.compile(
        r"\bsi\s+(?:existe|se\s+a[nñ]ade|aplica|procede)\b",
        re.IGNORECASE,
    )
    sections = [
        "Objetivo",
        "Fases",
        "Criterios de aceptacion",
        "Decision Arquitectonica",
    ]
    for section_name in sections:
        section_text = _extract_section(content, section_name)
        if not section_text:
            continue
        match = conditional_pattern.search(section_text)
        if match:
            warnings.append(
                ProseWarning(
                    rule_id="TP-PROSE-12",
                    rule_name="scope-condicional",
                    evidence=f"{section_name}: {match.group(0)[:80]}",
                    suggestion=(
                        "Cierra la decision de alcance en el plan; no delegues a una clausula condicional."
                    ),
                )
            )
    return warnings


def detect_imprecise_files_touched(content: str) -> list[ProseWarning]:
    """Detecta Files Likely Touched imprecisos (comodines o rutas vagas).

    Before: Requiere contenido de work_plan.md como string.
    During: Verifica que Files Likely Touched no use comodines ambiguos.
    After: Retorna lista de warnings con regla TP-PROSE-08.
    """
    warnings = []
    files_match = re.search(
        r"##\s*Files\s+Likely\s+Touched\s*\n(.*?)(?=##|\Z)", content, re.DOTALL
    )
    if files_match:
        files_text = files_match.group(1)
        # Detectar comodines ambiguos: **, *.py, o directorios completos sin archivos
        if re.search(r"\*\*|\*\.py|src/\*|tests/\*", files_text):
            warnings.append(
                ProseWarning(
                    rule_id="TP-PROSE-08",
                    rule_name="files-likely-touched-imprecisos",
                    evidence="Uso de comodines o rutas genericas en Files Likely Touched",
                    suggestion="Enumera archivos concretos: 'scripts/x.py', no 'scripts/**/*.py'.",
                )
            )
    return warnings


def detect_oversized_ticket(content: str) -> list[ProseWarning]:
    """Detecta ticket sobredimensionado (mas de 10 archivos o 5 fases).

    Before: Requiere contenido de work_plan.md como string.
    During: Cuenta archivos en Files Likely Touched y fases.
    After: Retorna lista de warnings con regla TP-PROSE-09.
    """
    warnings = []
    # Contar archivos
    files_match = re.search(
        r"##\s*Files\s+Likely\s+Touched\s*\n(.*?)(?=##|\Z)", content, re.DOTALL
    )
    if files_match:
        files_text = files_match.group(1)
        # Contar lineas que parecen archivos (empiezan con - y contienen ruta)
        file_count = len(
            [
                line
                for line in files_text.split("\n")
                if line.strip().startswith("-") and "`" in line
            ]
        )
        if file_count > 10:
            warnings.append(
                ProseWarning(
                    rule_id="TP-PROSE-09",
                    rule_name="ticket-sobredimensionado",
                    evidence=f"{file_count} archivos declarados (limite recomendado: 10)",
                    suggestion="Divide el ticket en 2+ tickets mas pequenos con alcance acotado.",
                )
            )

    # Contar fases
    phase_count = len(re.findall(r"###\s*Fase\s+\d+", content))
    if phase_count > 5:
        warnings.append(
            ProseWarning(
                rule_id="TP-PROSE-09",
                rule_name="ticket-sobredimensionado",
                evidence=f"{phase_count} fases declaradas (limite recomendado: 5)",
                suggestion="Divide el ticket en tickets mas pequenos con 2-3 fases cada uno.",
            )
        )
    return warnings


def detect_missing_architectural_decision(content: str) -> list[ProseWarning]:
    """Detecta decision arquitectonica ausente.

    Before: Requiere contenido de work_plan.md como string.
    During: Verifica existencia de seccion Decision Arquitectonica.
    After: Retorna lista de warnings con regla TP-PROSE-10.
    """
    warnings = []
    decision_match = re.search(
        r"##\s*Decision\s+Arquitectonica\s*\n", content, re.IGNORECASE
    )
    if not decision_match:
        warnings.append(
            ProseWarning(
                rule_id="TP-PROSE-10",
                rule_name="decision-arquitectonica-ausente",
                evidence="Seccion Decision Arquitectonica no encontrada",
                suggestion="Anade una seccion Decision Arquitectonica explicando el 'por que' del enfoque.",
            )
        )
    return warnings


def detect_ghost_dependency(content: str) -> list[ProseWarning]:
    """Detecta dependencia fantasma (menciona lib sin agregar a pyproject.toml).

    Before: Requiere contenido de work_plan.md como string.
    During: Busca menciones de librerias externas y verifica si son dependencias nuevas.
    After: Retorna lista de warnings con regla TP-PROSE-11.
    """
    warnings = []
    # Patrones de mencion de librerias
    lib_patterns = [
        r"\b(nuevo|nueva|agregar|anadir|instalar)\s+(?:libreria|paquete|dependencia)\s+(\w+)",
        r"\busar\s+la\s+libreria\s+(\w+)",
        r"\bimport\s+(\w+)\s+#\s*nuevo",
    ]
    for pattern in lib_patterns:
        matches = re.finditer(pattern, content, re.IGNORECASE)
        for match in matches:
            lib_name = match.group(1) if match.lastindex else "desconocida"
            warnings.append(
                ProseWarning(
                    rule_id="TP-PROSE-11",
                    rule_name="dependencia-fantasma",
                    evidence=f"Menciona libreria '{lib_name}' sin verificar si esta en pyproject.toml",
                    suggestion="Verifica que la dependencia este en pyproject.toml o agregala con 'uv add'.",
                )
            )
    return warnings


def detect_audit_missing_tp_check(collab_dir: Path) -> list[ProseWarning]:
    """Detecta AUDIT sin seccion TP Check (verificacion estructural).

    Before: Requiere directorio de colaboracion con archivos AUDIT_WP-*.md.
    During: Busca AUDIT del ticket activo y verifica seccion TP Check.
    After: Retorna lista de warnings con regla TP-STRUCT-01.
    """
    warnings = []
    # Buscar AUDIT del ticket activo
    audit_files = (
        list(collab_dir.glob("AUDIT_WP-*.md"))
        + list(collab_dir.glob("AUDIT_WT-*.md"))
        + list(collab_dir.glob("AUDIT_[A-Z][A-Z][A-Z]-*.md"))
    )
    if not audit_files:
        warnings.append(
            ProseWarning(
                rule_id="TP-STRUCT-01",
                rule_name="audit-missing-tp-check",
                evidence="No se encontro AUDIT_WP-*.md, AUDIT_WT-*.md ni AUDIT_<XXX>-*.md en .agent/collaboration/",
                suggestion="Crea un AUDIT_WP-*.md, AUDIT_WT-*.md o AUDIT_<XXX>-*.md con seccion '## TP Check' que verifique los 5 TP-P.",
            )
        )
        return warnings

    # Verificar que al menos un AUDIT tenga TP Check
    has_tp_check = False
    for audit_file in audit_files:
        content = audit_file.read_text(encoding="utf-8")
        if "## TP Check" in content:
            has_tp_check = True
            break

    if not has_tp_check:
        warnings.append(
            ProseWarning(
                rule_id="TP-STRUCT-01",
                rule_name="audit-missing-tp-check",
                evidence="AUDIT_WP-*.md, AUDIT_WT-*.md o AUDIT_<XXX>-*.md existe pero no contiene seccion '## TP Check'",
                suggestion="Anade '## TP Check' al AUDIT con verificacion de TP-01 a TP-05.",
            )
        )
    return warnings


def _extract_tp_check_section(content: str) -> str | None:
    """Extrae la seccion TP Check de un AUDIT.

    Before: Requiere contenido completo del AUDIT.
    During: Busca la seccion `## TP Check` y devuelve su contenido.
    After: Retorna el texto de la seccion o None si no existe.
    """
    match = re.search(
        r"##\s*TP\s*Check\s*\n(.*?)(?=\n##|\Z)", content, re.DOTALL | re.IGNORECASE
    )
    if not match:
        return None
    return match.group(1)


def detect_audit_malformed_tp_check(collab_dir: Path) -> list[ProseWarning]:
    """Detecta TP Check no canonico en el AUDIT.

    Before: Requiere directorio de colaboracion con archivos AUDIT_WP-*.md.
    During: Verifica que el TP Check use los items TP-01..TP-05 en formato canonico.
    After: Retorna lista de warnings con regla TP-STRUCT-02.
    """
    warnings = []
    audit_files = (
        list(collab_dir.glob("AUDIT_WP-*.md"))
        + list(collab_dir.glob("AUDIT_WT-*.md"))
        + list(collab_dir.glob("AUDIT_[A-Z][A-Z][A-Z]-*.md"))
    )
    if not audit_files:
        return warnings

    required_prefixes = [
        "TP-01:",
        "TP-02:",
        "TP-03:",
        "TP-04:",
        "TP-05:",
    ]

    for audit_file in audit_files:
        content = audit_file.read_text(encoding="utf-8")
        tp_check = _extract_tp_check_section(content)
        if tp_check is None:
            continue

        missing_prefixes = [
            prefix for prefix in required_prefixes if prefix not in tp_check
        ]
        if missing_prefixes:
            warnings.append(
                ProseWarning(
                    rule_id="TP-STRUCT-02",
                    rule_name="audit-malformed-tp-check",
                    evidence=f"{audit_file.name}: faltan {', '.join(missing_prefixes)} en la seccion TP Check",
                    suggestion="Redacta el TP Check con el formato canonico TP-01..TP-05 y una linea de verificacion por cada TP.",
                )
            )
    return warnings


# ============================================================================
# VALIDADOR PRINCIPAL
# ============================================================================


def validate_ticket_prose(work_plan_path: Path, collab_dir: Path) -> ValidationResult:
    """
    Valida la prosa de un work_plan.md.

    Before: Requiere ruta a work_plan.md y directorio de colaboracion.
    During: Ejecuta todas las reglas de deteccion sobre el contenido.
    After: Retorna ValidationResult con lista de warnings y contador.
    """
    if not work_plan_path.exists():
        return ValidationResult(
            warnings=[
                ProseWarning(
                    rule_id="TP-FATAL-01",
                    rule_name="work-plan-not-found",
                    evidence=str(work_plan_path),
                    suggestion="Asegurate de que work_plan.md existe en .agent/collaboration/",
                )
            ],
            warning_count=1,
        )

    content = work_plan_path.read_text(encoding="utf-8")
    is_completed_plan = bool(
        re.search(
            r"##\s*Metadata\s*\n.*?\-\s*\*\*Estado:\*\*\s*COMPLETED",
            content,
            re.DOTALL | re.IGNORECASE,
        )
    )

    all_warnings: list[ProseWarning] = []

    # Ejecutar todas las reglas de prosa
    all_warnings.extend(detect_throat_clearing(content))
    all_warnings.extend(detect_vague_declarative(content))
    all_warnings.extend(detect_imprecise_passive(content))
    all_warnings.extend(detect_lazy_extremes(content))
    all_warnings.extend(detect_diffuse_objective(content))
    all_warnings.extend(detect_missing_nongoals(content))
    all_warnings.extend(detect_nonverifiable_criteria(content))
    all_warnings.extend(detect_scope_conditional(content))
    all_warnings.extend(detect_imprecise_files_touched(content))
    all_warnings.extend(detect_oversized_ticket(content))
    all_warnings.extend(detect_missing_architectural_decision(content))
    all_warnings.extend(detect_ghost_dependency(content))

    # Verificacion estructural de AUDIT solo para planes activos.
    if not is_completed_plan:
        all_warnings.extend(detect_audit_missing_tp_check(collab_dir))
        all_warnings.extend(detect_audit_malformed_tp_check(collab_dir))

    return ValidationResult(
        warnings=all_warnings,
        warning_count=len(all_warnings),
    )


def format_output(result: ValidationResult, json_output: bool) -> str:
    """Formatea el resultado para salida.

    Before: Requiere ValidationResult y flag de JSON.
    During: Genera string legible o JSON segun flag.
    After: Retorna string formateado para impresion.
    """
    if json_output:
        return json.dumps(result, indent=2, ensure_ascii=False)

    lines = []
    lines.append(
        f"Ticket Prose Validator - {result['warning_count']} warnings encontrados"
    )
    lines.append("=" * 60)

    if not result["warnings"]:
        lines.append("[OK] No se detectaron problemas de prosa.")
        return "\n".join(lines)

    for warning in result["warnings"]:
        lines.append(f"\n[{warning['rule_id']}] {warning['rule_name']}")
        lines.append(f"  Evidencia: {warning['evidence']}")
        lines.append(f"  Sugerencia: {warning['suggestion']}")

    return "\n".join(lines)


def main() -> int:
    """Punto de entrada principal.

    Before: Argumentos de linea de comandos parseados.
    During: Carga work_plan.md, ejecuta validacion, formatea salida.
    After: Imprime resultado y retorna 0 (warnings no bloquean).
    """
    parser = argparse.ArgumentParser(
        description="Valida la calidad de prosa de work_plan.md"
    )
    parser.add_argument(
        "--work-plan",
        type=Path,
        default=None,
        help="Ruta a work_plan.md (default: .agent/collaboration/work_plan.md)",
    )
    parser.add_argument(
        "--collab-dir",
        type=Path,
        default=None,
        help="Directorio de colaboracion (default: .agent/collaboration/)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Salida en formato JSON",
    )

    args = parser.parse_args()

    # Rutas por defecto
    if args.work_plan is None:
        args.work_plan = Path(".agent/collaboration/work_plan.md")
    if args.collab_dir is None:
        args.collab_dir = Path(".agent/collaboration/")

    # Validar
    result = validate_ticket_prose(args.work_plan, args.collab_dir)

    # Imprimir
    print(format_output(result, args.json))

    # Exit code 0 siempre (warnings no bloquean)
    return 0


if __name__ == "__main__":
    sys.exit(main())
