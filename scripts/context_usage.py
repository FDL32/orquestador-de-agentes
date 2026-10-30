#!/usr/bin/env python3
"""WOT-2026-136i: medidor de contexto de las sesiones de un vuelo, versionado y honesto.

Sustituye funcionalmente al `ctx_usage.py` suelto de las coordinadoras. Aquel contaba como
compactacion toda caida a usage=0 (sobrecuenta) y agrupaba por directorio-slot, que mezcla
las sesiones de varias coordinadoras. Este script SOLO LEE: no escribe ficheros, no llama a
T3 ni lanza ningun proceso.

Before: el registro de sesiones resuelve por `--registry` y, si falta, por la variable
    `FLIGHT_SESSION_REGISTRY`. Los transcripts viven en `<raiz>/<slug-del-worktree>/<id>.jsonl`;
    las raices salen de `--projects-root` (repetible), luego de `CLAUDE_PROJECTS_ROOTS`
    (separadas por `os.pathsep`) y, por convencion, de `~/.claude*/projects`. Los directorios
    repetidos (enlaces entre raices) cuentan una vez.
During: cada sesion del registro se enlaza con los directorios cuyo nombre contiene su `slot`
    como secuencia de palabras separadas por `-` (un sufijo numerico de 1 a 3 cifras indica
    otra generacion y NO casa); `--slot-dir SLOT=TEXTO` fuerza el enlace para un slot cuyo
    directorio no lo lleva en el nombre. Dentro de sus directorios, la sesion toma el
    transcript de primer `timestamp` mas cercano a su `started`, dentro de la ventana
    [started - `--lead-seconds`, started + `--max-lag-seconds`) y antes del arranque de la
    siguiente sesion del mismo directorio. El `started` del registro se anota al ACK, despues
    de que el transcript ya arranco (medido 0.5-2.8 min en las coordinadoras): con
    `--lead-seconds 0` la ventana es la estricta (primer timestamp >= started). Un transcript
    ya asignado no se reutiliza (las ventanas de sesiones que comparten directorio son
    disjuntas). Si hay varios candidatos con primer timestamp a menos de
    `--ambiguity-seconds` entre si (incluido el empate exacto) no se elige ninguno.
    De cada transcript elegido se lee: contexto actual = input +
    cache_read + cache_creation del ULTIMO mensaje assistant (se ignoran los `<synthetic>` y
    los de cadena lateral), maximo, y compactaciones = mensajes con `isCompactSummary` true.
    Una caida de uso a 0 NO es una compactacion.
After: la PRIMERA linea de stdout es el denominador: `esperados N, medidos M, sin medicion K`.
    Sigue la tabla de medidos, la lista de sesiones sin medicion con su motivo (su contexto es
    DESCONOCIDO, nunca OK) y los transcripts de los directorios enlazados que no se pudieron
    atribuir (conteo por directorio; `--list-unattributed` los lista). Exit codes: 0 informe emitido con al menos una sesion medida; 2 entrada ilegible
    o de formato desconocido (registro, timestamp, usage, JSON no reconocible), o nada medido.
    Una linea JSON truncada se salta y se cuenta; un fichero sin ninguna linea JSON valida
    es formato desconocido. Nunca devuelve rc 3 ("no aplica" en los `check_*`).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path


REGISTRY_ENV = "FLIGHT_SESSION_REGISTRY"
ROOTS_ENV = "CLAUDE_PROJECTS_ROOTS"
DEFAULT_AMBIGUITY_SECONDS = 5.0
# Medido 2026-10-30 sobre session_registry.json y los transcripts reales: el transcript de una
# coordinadora arranca 0.5-2.8 min ANTES del `started` del registro (que se anota al ACK).
DEFAULT_LEAD_SECONDS = 300.0
DEFAULT_MAX_LAG_SECONDS = 300.0
DEFAULT_COMPACT_AT = 460_000
_USAGE_KEYS = ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")


class FormatoDesconocidoError(Exception):
    """Entrada ilegible o de formato no reconocido; el mensaje se imprime y el rc es 2."""


@dataclass(frozen=True)
class Session:
    code: str
    slot: str | None
    started: datetime | None


@dataclass(frozen=True)
class Transcript:
    path: Path
    directory: str
    first_ts: datetime | None


@dataclass
class Measure:
    messages: int = 0
    ctx_now: int = 0
    ctx_max: int = 0
    compactions: int = 0
    skipped_lines: int = 0


@dataclass
class Attribution:
    chosen: dict[str, Transcript] = field(default_factory=dict)
    missing: dict[str, str] = field(default_factory=dict)
    unattributed: list[Transcript] = field(default_factory=list)


def parse_ts(value: object, where: str) -> datetime:
    """Before: `value` deberia ser un ISO-8601 con zona (`Z` u offset). During: lo parsea.
    After: un datetime con zona; cualquier otra cosa lanza FormatoDesconocidoError."""
    if not isinstance(value, str):
        raise FormatoDesconocidoError(
            f"{where}: timestamp no es texto ({type(value).__name__})"
        )
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise FormatoDesconocidoError(f"{where}: timestamp ilegible {value!r}") from exc
    if parsed.tzinfo is None:
        raise FormatoDesconocidoError(f"{where}: timestamp sin zona horaria {value!r}")
    return parsed


def load_registry(path: Path) -> list[Session]:
    """Before: `path` es un session_registry.json. During: lo lee sin escribirlo.
    After: las sesiones con `code`, `slot` y `started` (None si el registro no lo trae);
    un registro ilegible o sin lista `sessions` lanza FormatoDesconocidoError."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise FormatoDesconocidoError(f"registro ilegible {path}: {exc}") from exc
    rows = data.get("sessions") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise FormatoDesconocidoError(f"registro {path}: falta la lista `sessions`")
    sessions: list[Session] = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("code"), str):
            raise FormatoDesconocidoError(f"registro {path}: fila sin `code` de texto")
        slot = row.get("slot")
        if slot is not None and not isinstance(slot, str):
            raise FormatoDesconocidoError(
                f"registro {path}: slot de {row['code']} no es texto"
            )
        raw = row.get("started")
        started = (
            None if raw is None else parse_ts(raw, f"registro {row['code']}.started")
        )
        sessions.append(Session(row["code"], slot, started))
    return sessions


def project_roots(cli_roots: list[str]) -> list[Path]:
    """Before: `cli_roots` son los `--projects-root`. During: aplica la precedencia
    argumentos > `CLAUDE_PROJECTS_ROOTS` > `~/.claude*/projects`. After: las raices que
    existen, sin repetidas por enlace."""
    if cli_roots:
        candidates = [Path(r) for r in cli_roots]
    elif os.environ.get(ROOTS_ENV):
        candidates = [Path(r) for r in os.environ[ROOTS_ENV].split(os.pathsep) if r]
    else:
        candidates = sorted(Path.home().glob(".claude*/projects"))
    roots: list[Path] = []
    seen: set[Path] = set()
    for root in candidates:
        if root.is_dir() and root.resolve() not in seen:
            seen.add(root.resolve())
            roots.append(root)
    return roots


def discover_transcripts(roots: list[Path]) -> dict[str, list[Path]]:
    """Before: `roots` son raices de proyectos. During: lista los `*.jsonl` de primer nivel
    de cada subdirectorio. After: nombre de directorio -> sus transcripts; un directorio
    alcanzable por dos raices (mismo destino real) se lista una sola vez, y dos directorios
    distintos con el mismo nombre en raices distintas juntan sus transcripts (ninguno se
    descarta en silencio)."""
    found: dict[str, list[Path]] = {}
    seen: set[Path] = set()
    for root in roots:
        for directory in sorted(p for p in root.iterdir() if p.is_dir()):
            real = directory.resolve()
            if real in seen:
                continue
            seen.add(real)
            files = sorted(directory.glob("*.jsonl"))
            if files:
                found.setdefault(directory.name, []).extend(files)
    return found


def first_timestamp(path: Path) -> datetime | None:
    """Before: `path` es un transcript. During: lee hasta el primer registro con
    `timestamp` (las lineas truncadas se saltan). After: ese instante, o None si el
    transcript no trae ninguno; un timestamp presente pero ilegible lanza FormatoDesconocidoError."""
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if isinstance(record, dict) and "timestamp" in record:
                    return parse_ts(record["timestamp"], f"transcript {path.name}")
    except OSError as exc:
        raise FormatoDesconocidoError(f"transcript ilegible {path}: {exc}") from exc
    return None


def dirs_for_slot(
    slot: str | None, dirnames: list[str], overrides: dict[str, str]
) -> list[str]:
    """Before: `dirnames` son los directorios con transcripts. During: aplica el
    `--slot-dir` del slot o, sin el, el casamiento por palabras `-slot-` sin sufijo
    numerico de 1 a 3 cifras. After: los directorios enlazados (vacio si no hay)."""
    if not slot:
        return []
    if slot in overrides:
        return [d for d in dirnames if overrides[slot] in d]
    pattern = re.compile(
        r"(?:^|-)" + re.escape(slot) + r"(?![A-Za-z0-9])(?!-\d{1,3}(?:-|$))"
    )
    return [d for d in dirnames if pattern.search(d)]


def _ambiguity_reason(candidates: list[tuple], ambiguity: timedelta) -> str | None:
    """Motivo de sin medicion si no hay candidato o los dos primeros se pisan; None si uno gana.

    Solo se compara el candidato mas cercano a `started` con el segundo: si el primero esta
    aislado a mas de `ambiguity` del segundo, gana aunque el segundo y el tercero se pisen."""
    if not candidates:
        return "ningun transcript con primer timestamp en su ventana"
    if len(candidates) > 1:
        gap = abs(candidates[1][1] - candidates[0][1])
        if gap <= ambiguity:
            return (
                f"ambiguo: {len(candidates)} candidatos con primeros timestamps a "
                f"{gap.total_seconds():g}s (umbral {ambiguity.total_seconds():g}s)"
            )
    return None


def attribute(
    sessions: list[Session],
    transcripts: dict[str, list[Path]],
    overrides: dict[str, str],
    ambiguity: timedelta,
    lead: timedelta = timedelta(seconds=DEFAULT_LEAD_SECONDS),
    max_lag: timedelta = timedelta(seconds=DEFAULT_MAX_LAG_SECONDS),
) -> Attribution:
    """Before: sesiones del registro y transcripts por directorio. During: enlaza cada
    sesion con sus directorios, calcula su ventana [started - lead, min(started + max_lag,
    started de la siguiente sesion del mismo directorio - lead)) y elige el transcript de
    primer timestamp mas cercano a `started`, sin reutilizar uno ya asignado (lo impone el
    bucle, ademas de que las ventanas son disjuntas) y sin elegir si hay candidatos a menos
    de `ambiguity`. After: el reparto; toda sesion sin transcript lleva
    su motivo y los transcripts de directorios enlazados sin dueno quedan en `unattributed`.
    Con `lead` = 0 la ventana es la estricta (primer timestamp >= started)."""
    names = sorted(transcripts)
    linked = {s.code: dirs_for_slot(s.slot, names, overrides) for s in sessions}
    cache: dict[Path, datetime | None] = {}

    def ts_of(path: Path) -> datetime | None:
        if path not in cache:
            cache[path] = first_timestamp(path)
        return cache[path]

    result = Attribution()
    used: set[Path] = set()
    dated = sorted(
        (s for s in sessions if s.started is not None), key=lambda s: s.started
    )
    for session in sorted(
        sessions, key=lambda s: (s.started is None, s.started or 0, s.code)
    ):
        if session.started is None or not linked[session.code]:
            result.missing[session.code] = (
                "el registro no trae `started`"
                if session.started is None
                else "sin directorio de transcripts para el slot"
            )
            continue
        neighbours = [
            other.started
            for other in dated
            if other.started >= session.started
            and other.code != session.code
            and set(linked[other.code]) & set(linked[session.code])
        ]
        start = session.started - lead
        end = session.started + max_lag
        if neighbours:
            end = min(end, min(neighbours) - lead)
        candidates = sorted(
            (abs(ts_of(p) - session.started), ts_of(p), name, p)
            for name in linked[session.code]
            for p in transcripts[name]
            if p not in used and ts_of(p) is not None and start <= ts_of(p) < end
        )
        reason = _ambiguity_reason(candidates, ambiguity)
        if reason:
            result.missing[session.code] = reason
        else:
            _, ts, name, path = candidates[0]
            result.chosen[session.code] = Transcript(path, name, ts)
            used.add(path)
    claimed = {d for dirs in linked.values() for d in dirs}
    for name in sorted(claimed):
        for path in transcripts[name]:
            if path not in used:
                result.unattributed.append(Transcript(path, name, ts_of(path)))
    return result


def _usage_total(usage: object, where: str) -> int:
    if not isinstance(usage, dict):
        raise FormatoDesconocidoError(f"{where}: `usage` no es un objeto")
    if "input_tokens" not in usage:
        raise FormatoDesconocidoError(f"{where}: `usage` sin input_tokens")
    total = 0
    for key in _USAGE_KEYS:
        value = usage.get(key, 0)
        if type(value) is not int or value < 0:
            raise FormatoDesconocidoError(
                f"{where}: {key} no es un entero >= 0 ({value!r})"
            )
        total += value
    return total


def _accumulate(record: dict, measure: Measure, where: str) -> None:
    """Suma un registro a `measure`: compactacion por `isCompactSummary` true y, si es un
    assistant real con usage, contexto actual y maximo. Los registros de cadena lateral
    (subagentes) no cuentan ni compactaciones ni contexto de la sesion principal."""
    if record.get("isSidechain") is True:
        return
    flag = record.get("isCompactSummary")
    if flag is not None and not isinstance(flag, bool):
        raise FormatoDesconocidoError(f"{where}: isCompactSummary no es booleano")
    if flag:
        measure.compactions += 1
    message = record.get("message")
    if record.get("type") != "assistant" or not isinstance(message, dict):
        return
    if message.get("model") == "<synthetic>":
        return
    if "usage" not in message:
        return
    total = _usage_total(message["usage"], where)
    measure.messages += 1
    measure.ctx_now = total
    measure.ctx_max = max(measure.ctx_max, total)


def measure_transcript(path: Path) -> Measure | None:
    """Before: `path` es un transcript JSONL de Claude Code. During: lo recorre en
    streaming; salta las lineas JSON truncadas, ignora los assistant `<synthetic>` y de
    cadena lateral, y cuenta `isCompactSummary` true como compactacion. After: la medida,
    o None si no hay ningun assistant con usage (contexto desconocido); un fichero sin
    ninguna linea JSON valida, una linea que no es objeto o un `usage` mal formado lanza
    FormatoDesconocidoError."""
    where = f"transcript {path.name}"
    measure = Measure()
    valid = 0
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            for number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except ValueError:
                    measure.skipped_lines += 1
                    continue
                if not isinstance(record, dict):
                    raise FormatoDesconocidoError(
                        f"{where}:{number}: la linea no es un objeto JSON"
                    )
                valid += 1
                _accumulate(record, measure, f"{where}:{number}")
    except OSError as exc:
        raise FormatoDesconocidoError(f"{where}: ilegible: {exc}") from exc
    if valid == 0:
        raise FormatoDesconocidoError(
            f"{where}: ninguna linea JSON valida (formato no reconocido)"
        )
    return measure if measure.messages else None


def build_report(
    sessions: list[Session],
    attribution: Attribution,
    compact_at: int,
    list_unattributed: bool = False,
) -> tuple[list[str], int]:
    """Before: sesiones esperadas y su atribucion. During: mide cada transcript elegido.
    After: (lineas del informe, numero de sesiones medidas); la primera linea es el
    denominador y toda sesion sin dato figura como DESCONOCIDO con su motivo."""
    measured: list[tuple[Session, Transcript, Measure]] = []
    unknown = dict(attribution.missing)
    for session in sessions:
        transcript = attribution.chosen.get(session.code)
        if transcript is None:
            continue
        measure = measure_transcript(transcript.path)
        if measure is None:
            unknown[session.code] = "transcript sin mensajes assistant con usage"
        else:
            measured.append((session, transcript, measure))
    head = f"esperados {len(sessions)}, medidos {len(measured)}, sin medicion {len(unknown)}"
    lines = [head]
    if measured:
        lines.append(
            f"{'sesion':14} {'slot':28} {'msgs':>5} {'ctx_now':>8} {'max':>8} "
            f"{'%' + str(compact_at // 1000) + 'k':>6} {'compact':>7} {'saltadas':>8} {'desfase_s':>9} transcript"
        )
    for session, transcript, m in measured:
        pct = f"{100 * m.ctx_now // compact_at}%"
        lag = int((transcript.first_ts - session.started).total_seconds())
        lines.append(
            f"{session.code:14} {(session.slot or '-')[:28]:28} {m.messages:5} {m.ctx_now:8} "
            f"{m.ctx_max:8} {pct:>6} {m.compactions:7} {m.skipped_lines:8} {lag:9} "
            f"{transcript.path.name[:8]}"
        )
    if unknown:
        lines.append("sin medicion (contexto DESCONOCIDO, no OK):")
        lines.extend(
            f"  {s.code} [{s.slot or '-'}]: {unknown[s.code]}"
            for s in sessions
            if s.code in unknown
        )
    lines.extend(_unattributed_lines(attribution.unattributed, list_unattributed))
    return lines, len(measured)


def _unattributed_lines(items: list[Transcript], listed: bool) -> list[str]:
    """Transcripts de directorios enlazados sin dueno: uno por linea o un conteo por directorio."""
    if not items:
        return []
    lines = ["transcripts de directorios enlazados sin atribuir:"]
    if listed:
        for item in items:
            when = item.first_ts.isoformat() if item.first_ts else "sin timestamp"
            lines.append(
                f"  {item.directory}/{item.path.name} (primer timestamp {when})"
            )
        return lines
    counts: dict[str, int] = {}
    for item in items:
        counts[item.directory] = counts.get(item.directory, 0) + 1
    lines.extend(f"  {name}: {count}" for name, count in sorted(counts.items()))
    return lines


def _parse_slot_dir(values: list[str]) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for value in values:
        slot, sep, text = value.partition("=")
        if not sep or not slot or not text:
            raise FormatoDesconocidoError(
                f"--slot-dir espera SLOT=TEXTO, recibio {value!r}"
            )
        overrides[slot] = text
    return overrides


def main(argv: list[str] | None = None) -> int:
    """Before: argumentos de linea de comandos. During: resuelve registro y raices, atribuye
    y mide, todo en solo lectura. After: imprime el informe y devuelve 0, o imprime el motivo
    en stderr y devuelve 2 (formato desconocido, entrada ilegible o nada medido)."""
    parser = argparse.ArgumentParser(
        description="Contexto de las sesiones de un vuelo (solo lectura)."
    )
    parser.add_argument("--registry", help=f"session_registry.json (o ${REGISTRY_ENV})")
    parser.add_argument(
        "--projects-root",
        action="append",
        default=[],
        help="raiz de proyectos Claude (repetible)",
    )
    parser.add_argument(
        "--sessions",
        nargs="+",
        metavar="CODE",
        help="limita los esperados a estos codigos",
    )
    parser.add_argument(
        "--slot-dir",
        action="append",
        default=[],
        metavar="SLOT=TEXTO",
        help="fuerza el directorio de un slot",
    )
    parser.add_argument(
        "--ambiguity-seconds", type=float, default=DEFAULT_AMBIGUITY_SECONDS
    )
    parser.add_argument(
        "--lead-seconds",
        type=float,
        default=DEFAULT_LEAD_SECONDS,
        help="cuanto antes del started puede arrancar su transcript",
    )
    parser.add_argument(
        "--max-lag-seconds",
        type=float,
        default=DEFAULT_MAX_LAG_SECONDS,
        help="cuanto despues del started puede arrancar su transcript",
    )
    parser.add_argument(
        "--list-unattributed",
        action="store_true",
        help="lista cada transcript sin atribuir",
    )
    parser.add_argument(
        "--compact-at",
        type=int,
        default=DEFAULT_COMPACT_AT,
        help="tokens de referencia para el porcentaje",
    )
    args = parser.parse_args(argv)
    try:
        registry = args.registry or os.environ.get(REGISTRY_ENV)
        if not registry:
            raise FormatoDesconocidoError(
                f"falta el registro: usa --registry o ${REGISTRY_ENV}"
            )
        if (
            min(args.ambiguity_seconds, args.lead_seconds, args.max_lag_seconds) < 0
            or args.compact_at <= 0
        ):
            raise FormatoDesconocidoError(
                "--ambiguity/--lead/--max-lag-seconds >= 0 y --compact-at > 0"
            )
        sessions = load_registry(Path(registry))
        if args.sessions:
            unknown = sorted(set(args.sessions) - {s.code for s in sessions})
            if unknown:
                raise FormatoDesconocidoError(
                    f"codigos ausentes del registro: {', '.join(unknown)}"
                )
            sessions = [s for s in sessions if s.code in set(args.sessions)]
        if not sessions:
            raise FormatoDesconocidoError("el registro no trae ninguna sesion esperada")
        transcripts = discover_transcripts(project_roots(args.projects_root))
        attribution = attribute(
            sessions,
            transcripts,
            _parse_slot_dir(args.slot_dir),
            timedelta(seconds=args.ambiguity_seconds),
            timedelta(seconds=args.lead_seconds),
            timedelta(seconds=args.max_lag_seconds),
        )
        lines, measured = build_report(
            sessions, attribution, args.compact_at, args.list_unattributed
        )
    except FormatoDesconocidoError as exc:
        print(f"NO VERIFICABLE: {exc}", file=sys.stderr)
        return 2
    print("\n".join(lines))
    if measured == 0:
        print("NO VERIFICABLE: ninguna sesion medida", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
