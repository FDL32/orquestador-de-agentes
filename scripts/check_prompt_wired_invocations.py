#!/usr/bin/env python3
"""Detector de INSTRUCCION SIN INVOCADOR (WOT-2026-042m).

Para cada scripts/check_*.py / validate_*.py / guard_*.py CITADO en prompts/*
o skills/*/SKILL.md, consulta el veredicto de `check_guard_wiring.audit()`: si el
script NO esta WIRED, es una INSTRUCCION SIN INVOCADOR AUTOMATICO -- una norma que
vive donde deberia vivir una barrera.

POR QUE ESTA ES LA HUELLA Y NO UN GATE DE CUMPLIMIENTO (ficha, literal): este
detector mide la HUELLA, no el cumplimiento. La ficha es explicita: "NO es un
'gate de instruccion cableada' y no debe venderse asi: es un DETECTOR DE SCRIPTS
CITADOS COMO OBLIGATORIOS EN UN PROMPT/SKILL Y NO CABLEADOS". NO analiza prosa
(ese muro no converge: 8 versiones fallidas de la ruta python-sink, WOT-2026-025c);
cruza dos objetos DISCRETOS: (a) una cita de fichero en prompts/skills, y (b) un
veredicto que el motor YA calcula (`collect_evidence` / `audit` de
check_guard_wiring).

El cruce es por NOMBRE DE FICHERO, no por semantica de la oracion: si un guard
aparece citado en `prompts/*.md` o `skills/*/SKILL.md` y check_guard_wiring lo
clasifica UNWIRED (o no lo encuentra en el denominador), la instruccion existe y
su invocador automatico NO. Excepciones declarables:
  - `known_unwired` / `wired_via` del policy de check_guard_wiring: el guard
    declarado como deuda con dueno ya tiene un contrato explicito -> INFO, no
    hallazgo (la deuda esta ACOTADA, que es lo que el contrato pide).
  - `extra_guards`: guards sin prefijo declarados para el denominador.
  - un guard NO-PREFIJO citado sin estar en el denominador -> se reporta como
    "fuera de denominador" (INFO, no bloqueante: puede ser un guard declarado
    via `wired_via` que este veredicto no ve quieto).

LIMITE DECLARADO (ficha, medida): de 628 lineas normativas censadas en 77
ficheros de prompts/+skills/ solo 92 (15%) nombran un artefacto comprobable. El
85% restante no admite gate de CONTENIDO; parte admitiria gate de RECIBO (esa
frontera NO esta medida y este ticket no la cierra). Por eso el detector NO
emite un veredicto de cumplimiento global: emite la lista de scripts citados y
su estado WIRED, para que la instruccion sin invocador sea VISIBLE.

Portabilidad: corre desde cualquier cwd y resuelve el motor desde la ruta del
fichero. exit 0 = todo lo citado esta WIRED o declarado; exit 1 = existe un
script citado en prompts/skills sin invocador automatico y SIN declaracion.

Before: el repo del motor tiene prompts/ y skills/ legibles y scripts/
  check_guard_wiring.py operable (importable).
During: escanea `prompts/*.md` y `skills/*/SKILL.md` (rglob) extrayendo nombres
  de scripts-check de los patrones `scripts/<check|validate|guard>_<x>.py` y
  `<check|validate|guard>_<x>.py`; acumula el set de enunciados; consulta
  `check_guard_wiring.audit()` y su policy. Read-only: nunca muta el arbol.
After: imprime la lista por fichero de origen con el veredicto; exit 0/1 segun
  existan instrucciones sin invocador no declaradas. Sin red.
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from pathlib import Path


MOTOR_ROOT = Path(__file__).resolve().parent.parent

_GUARD_SCRIPT_RE = re.compile(
    r"\b(?P<name>(?:check|validate|guard)_[a-zA-Z0-9_]+)\.py\b"
)
_PROMPT_DIRS = (MOTOR_ROOT / "prompts", MOTOR_ROOT / "skills")


def _load_guard_wiring():
    path = MOTOR_ROOT / "scripts" / "check_guard_wiring.py"
    spec = importlib.util.spec_from_file_location("check_guard_wiring", path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensivo
        raise ImportError(f"no se puede cargar {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["check_guard_wiring"] = mod
    spec.loader.exec_module(mod)
    return mod


def _iter_normative_files(root: Path) -> list[Path]:
    """prompts/*.md + skills/*/SKILL.md (la superficie que la ficha censa)."""
    files: list[Path] = []
    prompts = root / "prompts"
    skills = root / "skills"
    if prompts.is_dir():
        files += sorted(prompts.glob("*.md"))
    if skills.is_dir():
        files += sorted(skills.glob("*/SKILL.md"))
    return files


def collect_citations(root: Path) -> dict[str, list[str]]:
    """script-name -> [fichero origen]. Solo nombres de guard con prefijo.

    La ficha cita "scripts/X.py" como el objeto, pero el cruce es por NOMBRE
    DE BASENAME con prefijo guard: `check_|validate_|guard_` FUE la heuristica
    de `find_guards`. Un `.py` sin prefijo (p.ej. un util) no es un guard y no
    tiene veredicto en check_guard_wiring -> se ignora (declarado).
    """
    out: dict[str, list[str]] = {}
    for f in _iter_normative_files(root):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        try:
            rel = str(f.relative_to(root)).replace("\\", "/")
        except ValueError:
            rel = str(f)
        for m in _GUARD_SCRIPT_RE.finditer(text):
            name = m.group("name")
            out.setdefault(name, [])
            if rel not in out[name]:
                out[name].append(rel)
    return out


def classify(
    citations: dict[str, list[str]], cgw
) -> tuple[list[tuple[str, list[str], str]], list[str]]:
    """(hallazgos, infos). Un hallazgo es un guard citado NO WIRED y NO declarado.

    `declared` = known_unwired + extra_guards + wired_via del policy. Un guard
    declarado es deuda ACOTADA con dueno: soffens la huella pero NO se reporta
    como hallazgo nuevo (la ficha: "los falsos positivos conocidos ... se
    declaran con dueno, no se silencian").
    """
    policy = cgw._load_policy()
    declared = (
        set(policy.get("known_unwired", {}))
        | set(policy.get("extra_guards", {}))
        | set(policy.get("wired_via", {}))
    )
    wired, _ = cgw.audit(MOTOR_ROOT, policy)

    hallazgos: list[tuple[str, list[str], str]] = []
    infos: list[str] = []
    for name, origins in sorted(citations.items()):
        if name in wired:
            infos.append(f"WIRED    {name} (citado en {', '.join(origins)})")
        elif name in declared:
            infos.append(
                f"DECLARADO {name} (citado en {', '.join(origins)}; deuda con dueno)"
            )
        else:
            hallazgos.append((name, origins, "instruccion sin invocador"))
    return hallazgos, infos


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Detecta scripts de guard citados en prompts/skills sin "
        "invocador automatico (WOT-2026-042m)."
    )
    ap.add_argument(
        "--motor-root",
        default=str(MOTOR_ROOT),
        help="Raiz del motor (resuelta por defecto).",
    )
    args = ap.parse_args(argv)
    root = Path(args.motor_root).resolve()

    try:
        cgw = _load_guard_wiring()
        citations = collect_citations(root)
        hallazgos, infos = classify(citations, cgw)
    except ImportError as exc:
        print(f"[prompt-wired] ERROR: {exc}", file=sys.stderr)
        return 2

    print(
        f"[prompt-wired] scripts de guard citados en prompts/skills: {len(citations)}"
    )

    for info in infos:
        print(f"[prompt-wired]   {info}")

    if hallazgos:
        print("\n[prompt-wired] ERROR: instruccion(es) sin invocador automatico:")
        for name, origins, why in hallazgos:
            print(f"    {name}  ({why}) citado en {', '.join(origins)}")
        print(
            "\n  Un script citado en un prompt/skill como si fuera barrera pero que\n"
            "  nessun camino automatico ejecuta es una NORMA, no una barrera\n"
            "  (WOT-2026-024u). Cablea el guard en un camino que corre solo, o\n"
            "  declara la deuda en scripts/guard_wiring_policy.yaml con un dueno\n"
            "  VIVO (known_unwired) -- no lo silencies."
        )
        return 1

    print(
        "[prompt-wired] OK: todo script citado como barrera esta WIRED o es deuda declarada."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
