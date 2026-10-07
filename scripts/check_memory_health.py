#!/usr/bin/env python3
"""Salud de la memoria por raiz: calcula los disparadores del Bloque 4.0 (WOT-2026-089e).

Por que existe
--------------
`prompts/memory_optimization.md` solo se citaba como prosa opcional en el Bloque 4.0
del cierre, sin raiz declarada: el agente calculaba los disparadores a mano sobre la
raiz que tuviera a mano (el destino, con `AGENT_PROJECT_ROOT`) y el L1 del motor, que
ningun cierre consolida, llego a 97 % de ruido sin que nada lo viera. Este script es
la medicion MECANICA y con la raiz EXPLICITA; la invoca un paso del cierre
(`closeout_steps/memory_health.py`) y la puede invocar un agente a mano.

Before: `--project-root` (y opcionalmente `--motor-root`) apuntan a raices con un
    `.agent/`; una raiz sin memoria se mide como "ausente", no como error.
During: SOLO LECTURA. Por cada raiz parsea `observations.jsonl` (L1), cuenta las
    reglas de `memory_rules.md` (L2), compara la fecha de `MEMORY.md` con la del
    archive mas reciente y, si L1 existe, ejecuta `validate_observations.py --strict`
    sobre el. Importa de `memory_consolidate` SOLO la constante `MAX_L2_RULES` y
    `is_droppable_noise` (puras); NUNCA sus rutas de modulo, que atan el proceso a UNA
    raiz (`MEMORY_DIR` sale de `get_agent_dir()` al importar). Medir dos raices en un
    proceso exige que la ruta sea un PARAMETRO: `measure_root(root)`.
After: imprime, por raiz, el denominador (lineas parseadas, malformadas, ruido) y los
    cuatro disparadores (a)-(d); con `--json` emite el mismo contenido estructurado.
    Exit 0 siempre que la medicion se complete (es informativo: el veredicto va en la
    salida); exit 2 solo por uso erroneo.

KNOBS (NO medidos)
------------------
El propio Bloque 4.0 declara que 500 y 80 % son "KNOBS, no valores medidos optimos"; el
umbral de 7 dias tampoco lo respalda ninguna medicion, y el 90 % de L2 es un porcentaje
de `MAX_L2_RULES`. Se declaran UNA vez aqui y se etiquetan asi. El proxy de (b) es la
fecha de modificacion de los ficheros (no la del contenido).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


_SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS_DIR.parent))
sys.path.insert(0, str(_SCRIPTS_DIR))

from memory_consolidate import MAX_L2_RULES, is_droppable_noise  # noqa: E402


# KNOBS a ojo (ver docstring); no son valores calibrados.
L2_TRIGGER_FRACTION = 0.90
L1_MIN_ENTRIES = 500
L1_NOISE_RATIO = 0.80
MEMORY_STALE_DAYS = 7

_SECONDS_PER_DAY = 86400

# Header lines `memory_consolidate` writes under `Total rules:` in memory_rules.md
# (WOT-2026-058b). Read one by one so a file with only one of them still degrades.
_CANDIDATES_RE = re.compile(r"^Candidates:\s*(\d+)\s*$", re.MULTILINE)
_EXPELLED_RE = re.compile(r"^Expelled by cap:\s*(\d+)\s*$", re.MULTILINE)


def _memory_dir(root: Path) -> Path:
    return root / ".agent" / "runtime" / "memory"


def _measure_l1(path: Path) -> dict[str, Any]:
    """Cuenta lineas parseadas, malformadas, ruido descartable y lecciones con `id`."""
    if not path.is_file():
        return {"present": False, "parsed": 0, "malformed": 0, "noise": 0, "with_id": 0}
    parsed = malformed = noise = with_id = 0
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                malformed += 1
                continue
            if not isinstance(entry, dict):
                malformed += 1
                continue
            parsed += 1
            if entry.get("id"):
                with_id += 1
            if is_droppable_noise(entry):
                noise += 1
    return {
        "present": True,
        "parsed": parsed,
        "malformed": malformed,
        "noise": noise,
        "with_id": with_id,
    }


def _count_l2_rules(path: Path) -> dict[str, Any]:
    """Count the L2 rules and read the cap denominator `memory_consolidate` publishes.

    Before: `path` is the L2 file (`memory_rules.md`); it may not exist or may predate
        the `Candidates:` and `Expelled by cap:` header lines (WOT-2026-058b).
    During: read-only; counts the `#### R-` lines and reads each header line alone.
    After: dict with `present`, `rules`, `candidates` and `expelled`; the last two are
        ints, or None when their line is absent (old format) or the file is missing.
    """
    if not path.is_file():
        return {"present": False, "rules": 0, "candidates": None, "expelled": None}
    text = path.read_text(encoding="utf-8", errors="replace")
    candidates = _CANDIDATES_RE.search(text)
    expelled = _EXPELLED_RE.search(text)
    return {
        "present": True,
        "rules": sum(1 for ln in text.splitlines() if ln.startswith("#### R-")),
        "candidates": int(candidates.group(1)) if candidates else None,
        "expelled": int(expelled.group(1)) if expelled else None,
    }


def _memory_md_staleness(mem: Path) -> dict[str, Any]:
    """Dias que MEMORY.md va por detras del fichero de archive mas reciente (proxy: mtime)."""
    memory_md = mem / "MEMORY.md"
    archives = sorted((mem / "archive").glob("observations.*.jsonl"))
    if not memory_md.is_file() or not archives:
        return {
            "present": memory_md.is_file(),
            "archives": len(archives),
            "stale_days": 0.0,
        }
    newest = max(a.stat().st_mtime for a in archives)
    lag = max(0.0, newest - memory_md.stat().st_mtime)
    return {
        "present": True,
        "archives": len(archives),
        "stale_days": round(lag / _SECONDS_PER_DAY, 1),
    }


def _validate_l1(path: Path) -> int | None:
    """rc de `validate_observations.py --strict` sobre L1; None si L1 no existe."""
    if not path.is_file():
        return None
    result = subprocess.run(  # noqa: S603 - script propio, argumentos controlados
        [
            sys.executable,
            str(_SCRIPTS_DIR / "validate_observations.py"),
            "--strict",
            "--file",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode


def measure_root(root: Path, *, run_validate: bool = True) -> dict[str, Any]:
    """Mide UNA raiz y evalua los disparadores (a)-(d) del Bloque 4.0.

    Before: `root` es un directorio; sin `.agent/runtime/memory` todo se mide ausente.
    During: solo lectura; la unica ejecucion externa es el validador (desactivable).
    After: dict con `root`, las mediciones con su denominador y `triggers`.
    """
    mem = _memory_dir(root)
    l1_path = mem / "observations.jsonl"
    l1 = _measure_l1(l1_path)
    l2 = _count_l2_rules(mem / "memory_rules.md")
    stale = _memory_md_staleness(mem)
    validate_rc = _validate_l1(l1_path) if run_validate else None

    ratio = (l1["noise"] / l1["parsed"]) if l1["parsed"] else 0.0
    l2_threshold = L2_TRIGGER_FRACTION * MAX_L2_RULES
    if l2["candidates"] is None or l2["expelled"] is None:
        published = "candidatas n/d"
    else:
        published = f"expulsadas {l2['expelled']} de {l2['candidates']} candidatas"
    triggers = [
        {
            "id": "a",
            "fired": l2["rules"] >= l2_threshold,
            "detail": f"L2 {l2['rules']}/{MAX_L2_RULES} reglas "
            f"(umbral {l2_threshold:g}); {published}",
        },
        {
            "id": "b",
            "fired": stale["stale_days"] > MEMORY_STALE_DAYS,
            "detail": f"MEMORY.md va {stale['stale_days']} dias por detras del archive"
            f" (umbral {MEMORY_STALE_DAYS})",
        },
        {
            "id": "c",
            "fired": validate_rc not in (None, 0),
            "detail": f"validate_observations --strict rc={validate_rc}",
        },
        {
            "id": "d",
            "fired": l1["parsed"] > L1_MIN_ENTRIES and ratio > L1_NOISE_RATIO,
            "detail": f"L1 {l1['parsed']} entradas, ruido {l1['noise']}"
            f" ({ratio:.1%}; umbral {L1_MIN_ENTRIES} y {L1_NOISE_RATIO:.0%})",
        },
    ]
    return {
        "root": str(root),
        "l1": {**l1, "noise_ratio": round(ratio, 4)},
        "l2": {**l2, "max_rules": MAX_L2_RULES},
        "memory_md": stale,
        "validate_rc": validate_rc,
        "triggers": triggers,
    }


def _format(measure: dict[str, Any], label: str) -> str:
    fired = [t for t in measure["triggers"] if t["fired"]]
    lines = [f"[memory-health] {label}: {measure['root']}"]
    l1 = measure["l1"]
    lines.append(
        f"  denominador: L1 parseadas={l1['parsed']} malformadas={l1['malformed']} "
        f"ruido={l1['noise']} con_id={l1['with_id']}"
    )
    for trig in measure["triggers"]:
        mark = "DISPARA" if trig["fired"] else "ok"
        lines.append(f"  ({trig['id']}) {mark}: {trig['detail']}")
    lines.append(
        "  -> dispara: aplicar prompts/memory_optimization.md"
        if fired
        else "  -> no dispara"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project-root", required=True, help="raiz del destino")
    parser.add_argument("--motor-root", help="raiz del motor (opcional)")
    parser.add_argument("--json", action="store_true", help="salida estructurada")
    parser.add_argument(
        "--skip-validate", action="store_true", help="no ejecutar el validador (c)"
    )
    args = parser.parse_args(argv)

    roots = {"destino": Path(args.project_root).resolve()}
    if args.motor_root:
        motor = Path(args.motor_root).resolve()
        if motor != roots["destino"]:
            roots = {"motor": motor, **roots}
    measures = {
        label: measure_root(root, run_validate=not args.skip_validate)
        for label, root in roots.items()
    }
    if args.json:
        print(json.dumps(measures, ensure_ascii=False, indent=2))
    else:
        print("\n".join(_format(m, label) for label, m in measures.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
