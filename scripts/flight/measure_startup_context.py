#!/usr/bin/env python3
"""WOT-2026-192b: Medidor de arranque por rol (WARN, no gate).

Mide el contexto de arranque (startup context) agrupado por rol inferido
a partir de la ruta del worktree (-orquestadora-\\d -> CO, -implantador- -> IM,
-triaje- -> TRclaude, resto -> DESCONOCIDO).

Soporta 3 formatos de entrada en modo solo lectura:
- Claude JSONL (--claude-jsonl)
- Codex JSONL (--codex-jsonl)
- OpenCode SQLite (--opencode-db)

Contrato de salida:
- rc=0: informe emitido con exito (incluyendo avisos WARN).
- rc=2: entrada totalmente ilegible, fichero inexistente o error fatal de argumentos.
Sin gates numericos ni SLOs (WOT-2026-024t).
Pure ASCII encoding only.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import median


class StartupContextError(Exception):
    """Error fatal por entrada ilegible o invalida (rc=2)."""


@dataclass(frozen=True)
class SessionStartup:
    session_id: str
    role: str
    directory: str
    timestamp: datetime
    input_tokens: int
    cache_creation: int
    cache_read: int

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.cache_creation + self.cache_read


def classify_role(directory: str) -> str:
    """Clasifica el rol a partir de regex sobre la ruta del worktree."""
    normalized = directory.replace("\\", "/")
    if re.search(r"(?:^|[-_/])orquestadora-\d", normalized):
        return "CO"
    if re.search(r"(?:^|[-_/])implantador(?:[-_/]|\d|$)", normalized):
        return "IM"
    if re.search(r"(?:^|[-_/])triaje(?:[-_/]|$)", normalized):
        return "TRclaude"
    return "DESCONOCIDO"


def parse_timestamp(value: str | int | float | None) -> datetime:
    """Convierte un timestamp ISO o numerico a datetime UTC consciente de zona."""
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, (int, float)):
        # Si es timestamp en milisegundos
        if value > 1e11:
            value = value / 1000.0
        return datetime.fromtimestamp(value, tz=timezone.utc)
    if isinstance(value, str):
        clean = value.strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(clean)
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _extract_claude_usage(data: dict, path: Path) -> SessionStartup | None:
    """Extrae la sesion de arranque de una linea Claude si corresponde a un assistant con usage."""
    msg_type = data.get("type")
    msg_role = data.get("role")
    if msg_type != "assistant" and msg_role != "assistant":
        return None

    msg = data.get("message")
    usage = {}
    if isinstance(msg, dict):
        usage = msg.get("usage", {})
    if not usage and isinstance(data.get("usage"), dict):
        usage = data.get("usage", {})

    if not usage:
        return None

    input_tokens = int(usage.get("input_tokens", 0) or 0)
    cache_read = int(usage.get("cache_read_input_tokens", 0) or 0)
    cache_creation = int(usage.get("cache_creation_input_tokens", 0) or 0)

    # Si usage existe pero tiene todos los valores en 0, no es medicion valida
    if input_tokens == 0 and cache_read == 0 and cache_creation == 0:
        return None

    cwd = (
        data.get("cwd")
        or data.get("directory")
        or (msg.get("cwd") if isinstance(msg, dict) else None)
        or str(path.parent)
    )
    role = classify_role(cwd)
    ts = parse_timestamp(data.get("timestamp"))
    session_id = str(data.get("sessionId") or path.stem)

    return SessionStartup(
        session_id=session_id,
        role=role,
        directory=cwd,
        timestamp=ts,
        input_tokens=input_tokens,
        cache_creation=cache_creation,
        cache_read=cache_read,
    )


def _parse_json_line(raw_line: str, line_no: int, path: Path) -> dict | None:
    """Decodifica una linea JSON capturando errores y emitiendo WARN."""
    raw = raw_line.strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except Exception as exc:
        sys.stderr.write(f"WARN: Linea corrupta ignorada en {path}:{line_no}: {exc}\n")
        return None


def parse_claude_jsonl(path: Path) -> list[SessionStartup]:
    """Parsea una transcripcion Claude JSONL extrayendo el arranque del primer assistant."""
    if not path.is_file():
        raise StartupContextError(f"Fichero Claude JSONL no existe o ilegible: {path}")

    sessions: list[SessionStartup] = []
    found_startup = False
    valid_lines = 0

    try:
        with open(path, encoding="utf-8") as f:
            for line_no, raw_line in enumerate(f, start=1):
                data = _parse_json_line(raw_line, line_no, path)
                if data is None:
                    continue
                valid_lines += 1

                if not found_startup:
                    startup = _extract_claude_usage(data, path)
                    if startup:
                        sessions.append(startup)
                        found_startup = True

        if valid_lines == 0:
            raise StartupContextError(
                f"Fichero Claude JSONL sin lineas validas: {path}"
            )

        if not found_startup:
            sys.stderr.write(
                f"WARN: Sesion Claude sin medicion de usage en primer assistant: {path}\n"
            )

    except (OSError, UnicodeDecodeError) as exc:
        raise StartupContextError(f"Error al leer Claude JSONL {path}: {exc}") from exc

    return sessions


def _extract_codex_token_count(
    payload: dict,
    cwd: str,
    default_ts: datetime | None,
    record_ts: str | None,
    session_id: str,
) -> SessionStartup | None:
    """Extrae SessionStartup de un payload token_count de Codex."""
    info = payload.get("info", {})
    if not isinstance(info, dict):
        return None

    usage = info.get("last_token_usage") or info.get("total_token_usage") or {}
    if not isinstance(usage, dict) or not usage:
        return None

    input_tokens = int(usage.get("input_tokens", 0) or 0)
    cache_read = int(
        usage.get("cached_input_tokens", 0)
        or usage.get("cache_read_input_tokens", 0)
        or usage.get("cache_read", 0)
        or 0
    )
    cache_creation = int(
        usage.get("cache_write_input_tokens", 0)
        or usage.get("cache_creation_input_tokens", 0)
        or usage.get("cache_creation", 0)
        or 0
    )

    if input_tokens == 0 and cache_read == 0 and cache_creation == 0:
        return None

    role = classify_role(cwd)
    ts = default_ts or parse_timestamp(record_ts)

    return SessionStartup(
        session_id=session_id,
        role=role,
        directory=cwd,
        timestamp=ts,
        input_tokens=input_tokens,
        cache_creation=cache_creation,
        cache_read=cache_read,
    )


def _update_codex_state(
    data: dict,
    cwd: str,
    session_id: str,
    session_ts: datetime | None,
    default_parent: str,
) -> tuple[str, str, datetime | None]:
    """Actualiza metadatos de sesion codex (cwd, id, timestamp)."""
    rec_type = data.get("type")
    payload = data.get("payload")
    if not isinstance(payload, dict):
        return cwd, session_id, session_ts

    if rec_type == "session_meta":
        if payload.get("cwd"):
            cwd = payload.get("cwd")
        if payload.get("id") or payload.get("session_id"):
            session_id = str(payload.get("id") or payload.get("session_id"))
        if payload.get("timestamp"):
            session_ts = parse_timestamp(payload.get("timestamp"))
    elif rec_type == "turn_context" and payload.get("cwd") and cwd == default_parent:
        cwd = payload.get("cwd")

    return cwd, session_id, session_ts


def parse_codex_jsonl(path: Path) -> list[SessionStartup]:
    """Parsea una sesion Codex JSONL extrayendo el primer token_count."""
    if not path.is_file():
        raise StartupContextError(f"Fichero Codex JSONL no existe o ilegible: {path}")

    sessions: list[SessionStartup] = []
    found_startup = False
    valid_lines = 0
    cwd = str(path.parent)
    session_id = path.stem
    session_ts: datetime | None = None

    try:
        with open(path, encoding="utf-8") as f:
            for line_no, raw_line in enumerate(f, start=1):
                data = _parse_json_line(raw_line, line_no, path)
                if data is None:
                    continue
                valid_lines += 1

                cwd, session_id, session_ts = _update_codex_state(
                    data, cwd, session_id, session_ts, str(path.parent)
                )

                if data.get("type") == "event_msg" and not found_startup:
                    payload = data.get("payload")
                    if (
                        isinstance(payload, dict)
                        and payload.get("type") == "token_count"
                    ):
                        st = _extract_codex_token_count(
                            payload, cwd, session_ts, data.get("timestamp"), session_id
                        )
                        if st:
                            sessions.append(st)
                            found_startup = True

        if valid_lines == 0:
            raise StartupContextError(f"Fichero Codex JSONL sin lineas validas: {path}")

        if not found_startup:
            sys.stderr.write(f"WARN: Sesion Codex sin evento token_count en {path}\n")

    except (OSError, UnicodeDecodeError) as exc:
        raise StartupContextError(f"Error al leer Codex JSONL {path}: {exc}") from exc

    return sessions


def _extract_opencode_tokens(
    m_data: str | dict,
    s_id: str,
    s_dir: str,
    s_role: str,
    default_ts: datetime,
    m_time: str | None,
) -> SessionStartup | None:
    """Extrae SessionStartup de un mensaje OpenCode si contiene tokens."""
    try:
        data = json.loads(m_data) if isinstance(m_data, str) else m_data
    except Exception as exc:
        sys.stderr.write(f"WARN: Mensaje corrupto en OpenCode session {s_id}: {exc}\n")
        return None

    if not isinstance(data, dict):
        return None

    tokens = data.get("tokens")
    if not isinstance(tokens, dict) or not tokens:
        return None

    input_tokens = int(tokens.get("input", 0) or 0)
    cache = tokens.get("cache")
    cache_read = 0
    cache_creation = 0
    if isinstance(cache, dict):
        cache_read = int(cache.get("read", 0) or 0)
        cache_creation = int(cache.get("write", 0) or 0)

    if input_tokens == 0 and cache_read == 0 and cache_creation == 0:
        return None

    msg_ts = parse_timestamp(m_time) if m_time else default_ts

    return SessionStartup(
        session_id=str(s_id),
        role=s_role,
        directory=s_dir,
        timestamp=msg_ts,
        input_tokens=input_tokens,
        cache_creation=cache_creation,
        cache_read=cache_read,
    )


def parse_opencode_db(uri_or_path: str) -> list[SessionStartup]:
    """Parsea una base de datos OpenCode SQLite en modo solo lectura."""
    clean_path = uri_or_path
    if clean_path.startswith("file:"):
        clean_path = clean_path[5:]
    if "?mode=" in clean_path:
        clean_path = clean_path.split("?mode=")[0]

    p = Path(clean_path)
    if not p.is_file():
        raise StartupContextError(f"Base de datos OpenCode no existe: {uri_or_path}")

    sessions: list[SessionStartup] = []
    try:
        conn = sqlite3.connect(f"file:{p.resolve()}?mode=ro", uri=True)
        cur = conn.cursor()

        cur.execute("SELECT id, directory, title, time_created FROM session")
        raw_sessions = cur.fetchall()

        for s_id, s_dir, _s_title, s_time in raw_sessions:
            s_dir = s_dir or ""
            role = classify_role(s_dir)
            ts = parse_timestamp(s_time)

            cur.execute(
                "SELECT time_created, data FROM message WHERE session_id = ? ORDER BY time_created ASC",
                (s_id,),
            )
            messages = cur.fetchall()
            found_startup = False

            for m_time, m_data in messages:
                if not m_data:
                    continue
                st = _extract_opencode_tokens(m_data, s_id, s_dir, role, ts, m_time)
                if st:
                    sessions.append(st)
                    found_startup = True
                    break

            if not found_startup:
                sys.stderr.write(
                    f"WARN: Sesion OpenCode {s_id} sin tokens en sus mensajes\n"
                )

        conn.close()

    except sqlite3.Error as exc:
        raise StartupContextError(
            f"Error SQLite en OpenCode {uri_or_path}: {exc}"
        ) from exc

    return sessions


def get_current_head() -> str:
    """Obtiene el HEAD commit de git o fallback a 'desconocido'."""
    git_bin = shutil.which("git") or "git"
    try:
        res = subprocess.check_output(  # noqa: S603
            [git_bin, "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
        )
        return res.strip()
    except Exception:
        return "desconocido"


def format_table(sessions: list[SessionStartup], head: str | None = None) -> str:
    """Construye la tabla markdown por rol con mediana, cache separado, ventana y N."""
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    current_head = head or get_current_head()

    lines = [
        "# Medicion de contexto de arranque por rol (WOT-2026-192b)",
        f"Fecha: {now_str}",
        f"HEAD: {current_head}",
        "",
        "| Rol | Mediana | Input | Cache Creation | Cache Read | Ventana | N |",
        "|---|---|---|---|---|---|---|",
    ]

    by_role: dict[str, list[SessionStartup]] = {}
    for s in sessions:
        by_role.setdefault(s.role, []).append(s)

    # Orden predecible: CO, IM, TRclaude, DESCONOCIDO o alfabetico
    known_order = ["CO", "IM", "TRclaude", "DESCONOCIDO"]
    roles = sorted(
        by_role.keys(),
        key=lambda r: known_order.index(r) if r in known_order else 99,
    )

    for role in roles:
        role_sessions = by_role[role]
        n_count = len(role_sessions)

        totals = [s.total_tokens for s in role_sessions]
        inputs = [s.input_tokens for s in role_sessions]
        creations = [s.cache_creation for s in role_sessions]
        reads = [s.cache_read for s in role_sessions]

        med_total = round(median(totals)) if totals else 0
        med_input = round(median(inputs)) if inputs else 0
        med_creation = round(median(creations)) if creations else 0
        med_read = round(median(reads)) if reads else 0

        dates = [s.timestamp for s in role_sessions]
        min_date = min(dates).strftime("%Y-%m-%dT%H:%M:%SZ")
        max_date = max(dates).strftime("%Y-%m-%dT%H:%M:%SZ")
        ventana = f"{min_date} .. {max_date}"

        lines.append(
            f"| {role} | {med_total} | {med_input} | {med_creation} | {med_read} | {ventana} | {n_count} |"
        )

    lines.append("")
    return "\n".join(lines)


def measure_startup(
    claude_paths: list[str] | None = None,
    codex_paths: list[str] | None = None,
    opencode_paths: list[str] | None = None,
) -> tuple[int, str]:
    """Mide arranque sobre las fuentes provistas. Devuelve (rc, salida_markdown)."""
    claude_paths = claude_paths or []
    codex_paths = codex_paths or []
    opencode_paths = opencode_paths or []

    if not claude_paths and not codex_paths and not opencode_paths:
        sys.stderr.write("WARN: No se especificaron fuentes de entrada.\n")
        return 0, format_table([])

    all_sessions: list[SessionStartup] = []

    for cp in claude_paths:
        p = Path(cp)
        sessions = parse_claude_jsonl(p)
        all_sessions.extend(sessions)

    for cx in codex_paths:
        p = Path(cx)
        sessions = parse_codex_jsonl(p)
        all_sessions.extend(sessions)

    for oc in opencode_paths:
        sessions = parse_opencode_db(oc)
        all_sessions.extend(sessions)

    table_md = format_table(all_sessions)
    return 0, table_md


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada CLI del medidor de arranque."""
    parser = argparse.ArgumentParser(
        description="Medidor de contexto de arranque por rol (WOT-2026-192b)"
    )
    parser.add_argument(
        "--claude-jsonl",
        action="append",
        default=[],
        help="Ruta a fichero de transcripcion Claude JSONL (repetible)",
    )
    parser.add_argument(
        "--codex-jsonl",
        action="append",
        default=[],
        help="Ruta a fichero de sesion Codex JSONL (repetible)",
    )
    parser.add_argument(
        "--opencode-db",
        action="append",
        default=[],
        help="Ruta o URI a base de datos OpenCode SQLite (repetible)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Ruta opcional para guardar el informe emitido",
    )

    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code != 0 else 0

    try:
        rc, out_text = measure_startup(
            claude_paths=args.claude_jsonl,
            codex_paths=args.codex_jsonl,
            opencode_paths=args.opencode_db,
        )
    except StartupContextError as exc:
        sys.stderr.write(f"ERROR: {exc}\n")
        return 2
    except Exception as exc:
        sys.stderr.write(f"ERROR inesperado: {exc}\n")
        return 2

    if args.output:
        try:
            out_p = Path(args.output)
            out_p.parent.mkdir(parents=True, exist_ok=True)
            out_p.write_text(out_text, encoding="utf-8")
        except OSError as exc:
            sys.stderr.write(f"ERROR al escribir salida en {args.output}: {exc}\n")
            return 2

    sys.stdout.write(out_text)
    return rc


if __name__ == "__main__":
    sys.exit(main())
