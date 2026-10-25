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

Avisos de capa (`warnings`, aparte de los disparadores)
-------------------------------------------------------
Ademas de (a)-(d), `measure_root` publica `layers` (presencia de L1/L2/L3 y numero
de ficheros del archive) y `warnings`: un aviso informativo cuando faltan L2/L3. NO es un
disparador: no dice "aplica memory_optimization.md" ni nombra comando alguno, porque
L2/L3 se generan desde L1 viva y regenerarlas es decision manual del usuario. Lo
muestra el hook `SessionStart`; el paso de cierre (`closeout_steps/memory_health.py`)
lo IGNORA a proposito (solo lee `triggers`): en el cierre la ausencia de capas no es
una accion de optimizacion. Origen: bucle DESIGN_REVIEW EXPLORATORY-aviso-memoria,
2026-10-21 (3 lentes).

KNOBS (NO medidos)
------------------
El propio Bloque 4.0 declara que 500 y 80 % son "KNOBS, no valores medidos optimos"; el
umbral de 7 dias tampoco lo respalda ninguna medicion, y el 90 % de L2 es un porcentaje
de `MAX_L2_RULES`. Se declaran UNA vez aqui y se etiquetan asi. El metodo primario de (b)
es el contenido (sello `Regenerated:` vs timestamp maximo de las entradas del archive);
el mtime es solo fallback declarado (`metodo: "mtime"`).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


_SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS_DIR.parent))
sys.path.insert(0, str(_SCRIPTS_DIR))

from memory_consolidate import MAX_L2_RULES, is_droppable_noise  # noqa: E402


def _is_motor(root: Path) -> bool:
    """Detectar si una raiz es un motor (bus/memory_loader.py o mismo path que motor).

    Before: `root` es la raiz a verificar.
    During: chequea existencia de `bus/memory_loader.py` (señal canonica de motor).
    After: True si es motor, False si no.
    """
    return (root / "bus" / "memory_loader.py").is_file()


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


_REGENERATED_RE = re.compile(
    r"^Regenerated:\s*(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?)\s*$",
    re.MULTILINE,
)


def _max_archive_entry_timestamp(archive_dir: Path) -> datetime | None:
    """Return the max `timestamp` field from all archive/observations.*.jsonl entries.

    Before: `archive_dir` is the archive directory.
    During: reads each line, parses JSON, extracts `timestamp` (ISO-8601),
        converts Z to +00:00, naive -> UTC, and returns the maximum.
    After: datetime (UTC) or None if no parseable timestamp found.
    """
    from datetime import datetime, timezone

    max_ts: datetime | None = None
    for f in archive_dir.glob("observations.*.jsonl"):
        if not f.is_file():
            continue
        with f.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = entry.get("timestamp")
                if not ts or not isinstance(ts, str):
                    continue
                try:
                    entry_dt = ts.replace("Z", "+00:00")
                    parsed = datetime.fromisoformat(entry_dt)
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=timezone.utc)
                    if max_ts is None or parsed > max_ts:
                        max_ts = parsed
                except (ValueError, TypeError):
                    continue
    return max_ts


def _memory_md_staleness(mem: Path) -> dict[str, Any]:
    """Dias que MEMORY.md va por detras del contenido del archive mas reciente.

    Before: `mem` es `<raiz>/.agent/runtime/memory`; puede no existir MEMORY.md.
    During: busca el sello "Regenerated: <iso>" en MEMORY.md; lo compara con el
        timestamp maximo de las entradas JSON de `archive/observations.*.jsonl`
        (campo `timestamp` de cada linea).
        Sin sello o sin timestamp parseable -> fallback a mtime de fichero,
        marca `"metodo": "mtime"`.
        MEMORY.md ausente -> `"present": False`, `"stale_days": None`,
        `"metodo": "ausente"`; el disparador (b) no dispara en raices motor,
        pero dispara en un destino con detalle "MEMORY.md ausente".
    After: dict con `present`, `archives`, `stale_days`, `metodo`; si `present`
        es False, `stale_days` es None y `metodo` es "ausente".
    """
    from datetime import datetime, timezone

    memory_md = mem / "MEMORY.md"
    if not memory_md.is_file():
        archives = sorted((mem / "archive").glob("observations.*.jsonl"))
        return {
            "present": False,
            "archives": len(archives),
            "stale_days": None,
            "metodo": "ausente",
        }

    archives = sorted((mem / "archive").glob("observations.*.jsonl"))

    # Intentar leer sello Regenerated de contenido.
    text = memory_md.read_text(encoding="utf-8", errors="replace")
    reg_match = _REGENERATED_RE.search(text)
    metodo = "contenido"

    if reg_match and archives:
        # Parsear el sello Regenerated como timestamp ISO-8601.
        stamp_str = reg_match.group(1)
        stamp = stamp_str.replace("Z", "+00:00")
        try:
            reg_dt = datetime.fromisoformat(stamp)
            # Tomar el maximo timestamp de las ENTRADAS del archive,
            # no el mtime de los ficheros (un checkout reinicia mtime).
            newest_entry_time = _max_archive_entry_timestamp(mem / "archive")
            if newest_entry_time is not None:
                if reg_dt.tzinfo is None:
                    reg_dt = reg_dt.replace(tzinfo=timezone.utc)
                lag = (newest_entry_time - reg_dt).total_seconds()
                stale_days = round(max(0.0, lag / _SECONDS_PER_DAY), 1)
                return {
                    "present": True,
                    "archives": len(archives),
                    "stale_days": stale_days,
                    "metodo": metodo,
                }
        except (ValueError, TypeError):
            pass  # fallback a mtime

    # Fallback a mtime si no hay sello parseable o no hay archive.
    if not archives:
        return {
            "present": True,
            "archives": 0,
            "stale_days": 0.0,
            "metodo": "mtime",
        }
    newest = max(a.stat().st_mtime for a in archives)
    lag = max(0.0, newest - memory_md.stat().st_mtime)
    return {
        "present": True,
        "archives": len(archives),
        "stale_days": round(lag / _SECONDS_PER_DAY, 1),
        "metodo": "mtime",
    }


def _count_archive_rows(archive_dir: Path) -> int:
    """Count non-empty lines across all archive/observations.*.jsonl files.

    Before: `archive_dir` is the archive directory (`<root>/.agent/runtime/memory/archive`).
    During: reads-only; counts non-empty lines from each JSONL file.
    After: total count of non-empty lines, or 0 if no files exist.
    """
    total = 0
    for f in archive_dir.glob("observations.*.jsonl"):
        if f.is_file():
            with f.open(encoding="utf-8", errors="replace") as handle:
                total += sum(1 for line in handle if line.strip())
    return total


def _count_archive_bytes(archive_dir: Path) -> int:
    """Total size in bytes of all archive/observations.*.jsonl files.

    Before: `archive_dir` is the archive directory
        (`<root>/.agent/runtime/memory/archive`).
    During: reads-only; sums `.stat().st_size` from each file.
    After: total byte count, or 0 if no files exist.
    """
    total = 0
    for f in archive_dir.glob("observations.*.jsonl"):
        if f.is_file():
            total += f.stat().st_size
    return total


def _count_exact_dup_groups(archive_dir: Path) -> int:
    """Cuenta grupos de lineas JSON identicas (sort_keys) que se repiten >= 2 veces.

    Before: `archive_dir` es `<raiz>/.agent/runtime/memory/archive`.
    During: lee cada linea, la normaliza con sort_keys, cuenta ocurrencias.
    After: numero de grupos duplicados (solo los con >= 2 copias exactas).
    """
    counts: dict[str, int] = {}
    for f in archive_dir.glob("observations.*.jsonl"):
        if not f.is_file():
            continue
        with f.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    normalized = json.dumps(
                        json.loads(stripped), sort_keys=True, ensure_ascii=False
                    )
                    counts[normalized] = counts.get(normalized, 0) + 1
                except json.JSONDecodeError:
                    continue
    return sum(1 for c in counts.values() if c >= 2)


def _count_recall_log_lines(root: Path) -> int:
    """Lineas de .agent/runtime/memory/recall_log.jsonl, 0 si no existe.

    Before: `root` es la raiz del workspace.
    During: solo lectura del archivo de recall log si existe.
    After: numero de lineas no vacias, o 0 si no existe.
    """
    log = root / ".agent" / "runtime" / "memory" / "recall_log.jsonl"
    if not log.is_file():
        return 0
    with log.open(encoding="utf-8", errors="replace") as handle:
        return sum(1 for line in handle if line.strip())


def _measure_layers(mem: Path) -> dict[str, Any]:
    """Presencia de las capas L1/L2/L3 y numero de ficheros del archive versionado.

    Before: `mem` es `<raiz>/.agent/runtime/memory`; puede no existir.
    During: solo `is_file()`/`glob`; no lee contenido ni escribe.
    After: dict con `l1`, `l2`, `l3` (bool) y `archives` (int). Una raiz sin
        directorio de memoria se mide como todo ausente, sin lanzar.
    """
    return {
        "l1": (mem / "observations.jsonl").is_file(),
        "l2": (mem / "memory_rules.md").is_file(),
        "l3": (mem / "memory_profile.md").is_file(),
        "archives": sum(
            1 for a in (mem / "archive").glob("observations.*.jsonl") if a.is_file()
        ),
    }


def _layer_warnings(layers: dict[str, Any]) -> list[str]:
    """Avisos informativos por capa destilada (L2/L3) ausente; vacio si estan las dos.

    NO es un disparador del Bloque 4.0: un trigger hace que el cierre y el hook
    digan "aplica memory_optimization.md", que es la accion equivocada para "faltan
    capas" (esas capas se generan desde L1 y el `--apply` es decision del usuario).
    Por eso el texto no nombra ningun comando: informa, no repara. Los textos son
    ASCII y sin ";" (el hook une las raices con ";").

    Before: `layers` sale de `_measure_layers`.
    During: funcion pura; elige UNO de cuatro textos segun L1, el archive y cuantas capas faltan.
    After: lista de 0 o 1 aviso. Vacia cuando L2 y L3 existen.
    """
    missing = [name for name, key in (("L2", "l2"), ("L3", "l3")) if not layers[key]]
    if not missing:
        return []
    absent = "/".join(missing)
    plural = len(missing) > 1
    ausente = "ausentes" if plural else "ausente"
    if layers["l1"]:
        return [
            f"capa destilada {absent} {ausente} aunque L1 existe, "
            f"regenerar{'las' if plural else 'la'} es decision manual del usuario "
            "(no lo ejecutes por tu cuenta)"
        ]
    if layers["archives"]:
        return [
            f"{absent} {ausente} (gitignored, por worktree, normal en uno nuevo), "
            f"la memoria portable sale del archive versionado ({layers['archives']}"
            " ficheros)"
        ]
    if plural:
        # Solo aqui se afirma "sin memoria": con una capa presente (p.ej. L2) el
        # arranque SI tiene memoria persistente (hallazgo de la lente DeepSeek).
        return [
            f"{absent} {ausente} y sin archive versionado ni L1, "
            "este arranque no tiene memoria persistente"
        ]
    return [f"{absent} {ausente} y sin archive versionado ni L1"]


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
    is_motor = _is_motor(root)
    triggers = [
        {
            "id": "a",
            "fired": l2["rules"] >= l2_threshold,
            "detail": f"L2 {l2['rules']}/{MAX_L2_RULES} reglas "
            f"(umbral {l2_threshold:g}); {published}",
        },
        {
            "id": "b",
            "fired": (
                stale["stale_days"] is not None
                and stale["stale_days"] > MEMORY_STALE_DAYS
            )
            or (stale["stale_days"] is None and not is_motor),
            "detail": (
                f"MEMORY.md va {stale['stale_days']} dias por detras del archive"
                if stale["stale_days"] is not None
                else "MEMORY.md ausente"
            )
            + ("" if stale["stale_days"] is None else f" (umbral {MEMORY_STALE_DAYS})"),
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
    layers = _measure_layers(mem)
    archive_dir = mem / "archive"
    has_archives = archive_dir.is_dir() and any(
        f.is_file() for f in archive_dir.glob("observations.*.jsonl")
    )
    growth: dict[str, Any] = {}
    if has_archives:
        growth = {
            "archive_rows": _count_archive_rows(archive_dir),
            "archive_bytes": _count_archive_bytes(archive_dir),
            "archive_exact_dup_groups": _count_exact_dup_groups(archive_dir),
            "recall_log_lines": _count_recall_log_lines(root),
        }
    is_motor = _is_motor(root)
    return {
        "root": str(root),
        "l1": {**l1, "noise_ratio": round(ratio, 4)},
        "l2": {**l2, "max_rules": MAX_L2_RULES},
        "memory_md": stale,
        "validate_rc": validate_rc,
        "triggers": triggers,
        "layers": layers,
        "warnings": _layer_warnings(layers),
        "growth": growth,
        "is_motor": _is_motor(root),
    }


def _format(measure: dict[str, Any], label: str) -> str:
    fired = [t for t in measure["triggers"] if t["fired"]]
    is_motor = measure.get("is_motor", False)
    root_label = "motor" if is_motor and label == "motor" else label
    lines = [f"[memory-health] {root_label}: {measure['root']}"]
    l1 = measure["l1"]
    lines.append(
        f"  denominador: L1 parseadas={l1['parsed']} malformadas={l1['malformed']} "
        f"ruido={l1['noise']} con_id={l1['with_id']}"
    )
    for trig in measure["triggers"]:
        mark = "DISPARA" if trig["fired"] else "ok"
        lines.append(f"  ({trig['id']}) {mark}: {trig['detail']}")
    growth = measure.get("growth", {})
    if growth:
        lines.append(
            f"  (e) info: archive_rows={growth.get('archive_rows', 0)}"
            f" archive_bytes={growth.get('archive_bytes', 0)}"
            f" exact_dup_groups={growth.get('archive_exact_dup_groups', 0)}"
            f" recall_log_lines={growth.get('recall_log_lines', 0)}"
        )
    lines.extend(f"  AVISO: {w}" for w in measure.get("warnings", []))
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

    project_root = Path(args.project_root).resolve()
    roots: dict[str, Path] = {}
    # 1. Separate motor_root if provided and different (always first for R3)
    if args.motor_root:
        motor_root = Path(args.motor_root).resolve()
        if motor_root != project_root:
            roots["motor"] = motor_root
    # 2. Label project_root based on whether it is a motor
    if _is_motor(project_root):
        if "motor" not in roots:
            roots["motor"] = project_root
        else:
            roots["motor-proyecto"] = project_root
    else:
        roots["destino"] = project_root
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
