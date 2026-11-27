"""Mide el contexto acumulado de una coordinadora en transcripts JSONL.

Before: se reciben uno o mas directorios de proyecto y marcadores que identifican
    la sesion por su primer mensaje de usuario; los transcripts se leen solamente.
During: se suman los tokens actuales y los tramos cerrados por compactacion, y se
    aplica el umbral de preparacion o de cierre.
After: se imprime una medicion; rc 0 es OK, rc 3 PREPARA, rc 4 CERRAR_Y_SALTAR
    y rc 2 indica que ningun transcript coincide con los marcadores.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


def _json_records(path: Path) -> list[dict[str, Any]]:
    """Before: `path` es un transcript JSONL legible.

    During: lee cada linea, omitiendo JSON invalido y valores que no sean objetos.
    After: devuelve los eventos interpretables sin modificar el transcript.
    """
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            try:
                value = json.loads(line)
            except (TypeError, ValueError):
                continue
            if isinstance(value, dict):
                records.append(value)
    return records


def _content_text(value: object) -> str:
    """Before: `value` es el contenido del primer mensaje de usuario.

    During: conserva texto y serializa contenido estructurado de forma estable.
    After: devuelve el texto sobre el que se buscan los marcadores.
    """
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _first_user_text(records: list[dict[str, Any]]) -> str:
    """Before: `records` contiene eventos de un transcript.

    During: localiza el primer evento de usuario y extrae su contenido.
    After: devuelve una cadena vacía si no existe un mensaje de usuario.
    """
    for record in records:
        message = record.get("message")
        is_user = record.get("type") == "user" or (
            isinstance(message, dict) and message.get("role") == "user"
        )
        if is_user:
            content = message.get("content") if isinstance(message, dict) else None
            return _content_text(content)
    return ""


def _token_value(usage: object, key: str) -> int:
    """Before: `usage` es un mapping opcional de contadores.

    During: acepta solo enteros no negativos para evitar sumar valores corruptos.
    After: devuelve el contador válido o cero.
    """
    if not isinstance(usage, dict):
        return 0
    value = usage.get(key, 0)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value


def _assistant_usage(record: dict[str, Any]) -> int | None:
    """Before: `record` puede ser un evento assistant.

    During: identifica el rol y suma los tres contadores de entrada.
    After: devuelve el total o None cuando el evento no aporta uso.
    """
    message = record.get("message")
    if record.get("type") != "assistant" and not (
        isinstance(message, dict) and message.get("role") == "assistant"
    ):
        return None
    usage = message.get("usage") if isinstance(message, dict) else None
    if not isinstance(usage, dict):
        return None
    return sum(
        _token_value(usage, key)
        for key in (
            "input_tokens",
            "cache_read_input_tokens",
            "cache_creation_input_tokens",
        )
    )


def _compact_pre(record: dict[str, Any], default_pre: int) -> int | None:
    """Before: `record` es un evento de sistema potencialmente compacto.

    During: lee `compactMetadata.preTokens` y aplica el valor por defecto si falta.
    After: devuelve el preTokens, el default o None si no es compact_boundary.
    """
    if record.get("subtype") != "compact_boundary":
        return None
    metadata = record.get("compactMetadata")
    pre_tokens = metadata.get("preTokens") if isinstance(metadata, dict) else None
    if (
        isinstance(pre_tokens, int)
        and not isinstance(pre_tokens, bool)
        and pre_tokens > 0
    ):
        return pre_tokens
    return default_pre


def _measure(path: Path, default_pre: int) -> dict[str, Any]:
    """Before: `path` es un transcript que coincide con un marcador.

    During: mide usos assistant, compactaciones marcadas y caídas no marcadas.
    After: devuelve la medición sin escribir el transcript.
    """
    records = _json_records(path)
    usages: list[int] = []
    pre_tokens: list[int] = []
    compact_positions: list[int] = []
    for record in records:
        compact = _compact_pre(record, default_pre)
        if compact is not None:
            compact_positions.append(len(usages))
            pre_tokens.append(compact)
        usage = _assistant_usage(record)
        if usage is not None:
            usages.append(usage)
    estimated = 0
    for index in range(1, len(usages)):
        dropped_by_half = usages[index] < usages[index - 1] * 0.5
        boundary_nearby = any(
            abs(index - position) <= 3 for position in compact_positions
        )
        if dropped_by_half and not boundary_nearby:
            pre_tokens.append(default_pre)
            estimated += 1
    return {
        "file": path.name[:8],
        "msgs": len(usages),
        "now": usages[-1] if usages else 0,
        "pre": pre_tokens,
        "estimated": estimated,
    }


def _transcript_paths(project_dirs: list[Path]) -> list[Path]:
    """Before: `project_dirs` son los directorios declarados por CLI.

    During: recoge solo ficheros JSONL directos y deduplica rutas resueltas.
    After: devuelve rutas ordenadas de forma determinista.
    """

    def resolved_or_original(path: Path) -> Path:
        """Before: `path` es un transcript descubierto.

        During: intenta resolverlo para deduplicar rutas.
        After: devuelve la ruta resuelta o la original si el sistema no puede resolverla.
        """
        try:
            return path.resolve()
        except OSError:
            return path

    paths: dict[Path, Path] = {}
    for directory in project_dirs:
        if not directory.is_dir():
            continue
        for path in directory.glob("*.jsonl"):
            paths[resolved_or_original(path)] = path
    return sorted(paths.values(), key=lambda item: str(item))


def _emit_alert(
    alert_ops_dir: Path, dry_run: bool, accumulated: int, compactations: int
) -> int:
    """Before: rc 4 ha sido decidido y `alert_ops_dir` fue solicitado.

    During: carga `comms_alert.py` junto a este script y emite un aviso urgente.
    After: devuelve el rc del aviso o 2 si no se pudo cargar/ejecutar.
    """
    alert_path = Path(__file__).resolve().with_name("comms_alert.py")
    try:
        print(
            f"ALERTA URGENTE: CERRAR_Y_SALTAR acumulado={accumulated} "
            f"compactaciones={compactations}"
        )
        spec = importlib.util.spec_from_file_location("flight_comms_alert", alert_path)
        if spec is None or spec.loader is None:
            raise ImportError("no se pudo crear el cargador de comms_alert.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.configure(str(alert_ops_dir))
        return int(
            module.event(
                "ctx_cerrar_y_saltar",
                "URGENTE",
                "Vuelo ?",
                f"CERRAR_Y_SALTAR: acumulado={accumulated} compactaciones={compactations}",
                False,
                dry_run,
            )
        )
    except (AttributeError, ImportError, OSError, TypeError, ValueError) as exc:
        print(f"ERROR: no se pudo emitir el aviso URGENTE: {exc}", file=sys.stderr)
        return 2


def _parser() -> argparse.ArgumentParser:
    """Before: no se requiere estado externo.

    During: construye el parser del contrato CLI.
    After: devuelve un parser con project-dir y marker repetibles y obligatorios.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-dir", type=Path, action="append", required=True)
    parser.add_argument("--marker", action="append", required=True)
    parser.add_argument("--default-pre", type=int, default=550_000)
    parser.add_argument("--prepare-at", type=int, default=380_000)
    parser.add_argument("--alert-ops-dir", type=Path, default=None)
    parser.add_argument("--alert-dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Before: argv contiene los directorios, marcadores y umbrales del vuelo.

    During: selecciona transcripts, imprime la tabla y opcionalmente avisa en rc 4.
    After: devuelve el codigo de salida funcional del contrato.
    """
    args = _parser().parse_args(argv)
    if args.default_pre <= 0 or args.prepare_at < 0:
        print("ERROR: los umbrales deben ser positivos", file=sys.stderr)
        return 2
    measurements: list[dict[str, Any]] = []
    try:
        for path in _transcript_paths(args.project_dir):
            records = _json_records(path)
            if any(marker in _first_user_text(records) for marker in args.marker):
                measurements.append(_measure(path, args.default_pre))
    except (OSError, ValueError) as exc:
        print(f"ERROR: no se pudo leer un transcript: {exc}", file=sys.stderr)
        return 2
    if not measurements:
        print("ERROR: ningun transcript casa con los marcadores", file=sys.stderr)
        return 2

    total_pre = sum(sum(item["pre"]) for item in measurements)
    accumulated_now = sum(item["now"] for item in measurements)
    accumulated = total_pre + accumulated_now
    compactations = sum(len(item["pre"]) for item in measurements)
    live_now = measurements[-1]["now"]
    print(
        f"{'sesion':8} {'msgs':>5} {'actual':>8} {'compact':>7} {'suma_pre':>9} {'estimadas':>9}"
    )
    for item in measurements:
        print(
            f"{item['file']:8} {item['msgs']:5} {item['now']:8} "
            f"{len(item['pre']):7} {sum(item['pre']):9} {item['estimated']:9}"
        )
    estimated = sum(item["estimated"] for item in measurements)
    print(
        f"ACUMULADO = suma(pre)={total_pre} + suma(actual de cada tramo)="
        f"{accumulated_now} = {accumulated} tokens (actual del tramo vivo={live_now}); "
        f"compactaciones={compactations} (estimadas a {args.default_pre}: {estimated})"
    )
    if compactations >= 1 or accumulated >= args.default_pre:
        if args.alert_ops_dir is not None:
            _emit_alert(
                args.alert_ops_dir, args.alert_dry_run, accumulated, compactations
            )
        print("ESTADO: CERRAR_Y_SALTAR")
        return 4
    if live_now >= args.prepare_at:
        print("ESTADO: PREPARA")
        return 3
    print("ESTADO: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
