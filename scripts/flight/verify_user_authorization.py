#!/usr/bin/env python3
"""WOT-2026-153v: verificador de la procedencia del mensaje del usuario.

Este modulo es el nucleo del wrapper que verifica Y ejecuta una accion de
clase B (push) en el mismo comando. Lee en SOLO LECTURA el almacen de T3
(`statev2.sqlite`) y solo acepta una autorizacion si existe UN mensaje del
usuario que cumple TODO el predicado del contrato.

Before (precondiciones): existe un almacen SQLite de T3 con el esquema real
    medido en el PASO 0: `orchestration_v2_projection_messages` (message_id,
    thread_id, run_id, node_id, role, streaming, created_at, updated_at,
    payload_json) y `orchestration_v2_projection_threads` (thread_id,
    created_at, updated_at, deleted_at, ...). El payload JSON trae createdBy,
    creationSource, text y, opcionalmente, senderThreadId. El invocador aporta
    el messageId ancla de la peticion del agente y la frase canonica esperada.
During (proceso): abre el almacen con `mode=ro` y `PRAGMA query_only=ON`, valida
    el esquema (smoke-test fail-closed), resuelve el ancla, recorre SOLO los
    mensajes del hilo del ancla (nunca otros hilos), y evalua el predicado:
    createdBy=user, creationSource en {web, mobile}, messageId UUID36 sin
    prefijos automaticos, sin senderThreadId, no streaming, posterior al ancla
    por (created_at, message_id) y texto ENTERO igual a la frase canonica tras
    una normalizacion ASCII acotada.
After (postcondiciones): devuelve una Decision con allowed, el motivo
    machine-readable y, si autoriza, el messageId elegido y el sha256 del texto
    para el ledger. Todo fallo de infraestructura (base ausente, corrupta,
    bloqueada, esquema distinto, limite de escaneo) se eleva como InfraError
    con causa NOMBRADA y NUNCA como "no autorizado" ni como silencio. No
    escribe en el almacen jamas.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote


_ORIGINAL_OS_CLOSE = os.close


SCHEMA_MESSAGES = "orchestration_v2_projection_messages"
SCHEMA_THREADS = "orchestration_v2_projection_threads"

MESSAGE_COLUMNS = (
    "message_id",
    "thread_id",
    "created_at",
    "updated_at",
    "streaming",
    "payload_json",
)
THREAD_COLUMNS = ("thread_id", "created_at", "updated_at", "deleted_at")

ACCEPTED_CREATED_BY = "user"
ACCEPTED_SOURCES = frozenset({"web", "mobile"})

# Se miran en el messageId, NUNCA en el texto.
FORBIDDEN_MESSAGE_ID_PREFIXES = (
    "scheduled-task-message:",
    "async-answer:",
    "limit-resume:",
    "import:",
    "message:",
    "mcp:",
)

# Formas de messageId que el productor imprime hoy (medidas en el PASO 0).
_UUID36_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_SHA12_RE = re.compile(r"^[0-9a-f]{12}$")
_SHA_FULL_RE = re.compile(r"^[0-9a-f]{40}$")
_CANONICAL_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
_EDGE_WS = " \t\r\n\f\v\u00a0"
_TOKEN_SPLIT_RE = re.compile(r"[ \t]+")

PAGE_SIZE = 2000
MAX_PAGES = 5

_MESSAGE_SELECT = (
    "message_id, thread_id, created_at, updated_at, streaming, payload_json"
)
_SQL_BY_MESSAGE_ID = (
    f"SELECT {_MESSAGE_SELECT} FROM {SCHEMA_MESSAGES} WHERE message_id = ?"  # noqa: S608
)
_SQL_THREAD_STATE = f"SELECT deleted_at FROM {SCHEMA_THREADS} WHERE thread_id = ?"  # noqa: S608
_SQL_THREAD_PAGE = (
    f"SELECT {_MESSAGE_SELECT} FROM {SCHEMA_MESSAGES} "  # noqa: S608
    "WHERE thread_id = ? AND (created_at > ? OR (created_at = ? AND message_id > ?)) "
    "ORDER BY created_at, message_id LIMIT ?"
)

# Orden de prioridad para elegir el motivo mas accionable cuando ningun
# candidato autoriza. Indice menor = mas especifico.
FAILURE_PRIORITY = (
    "consumed",
    "text-mismatch",
    "sender-thread",
    "not-final",
    "message-id-prefix",
    "message-id-form",
    "source-not-accepted",
    "timestamp-form",
    "payload-unreadable",
)

EXIT_ALLOWED = 0
EXIT_REJECTED = 10
EXIT_INFRA = 11
EXIT_USAGE = 12
EXIT_PUSH_FAILED = 20

_MISSING = object()


class InfraError(RuntimeError):
    """Fallo de infraestructura con causa NOMBRADA (nunca "no autorizado").

    Before: recibe una causa corta y estable (`store-missing`, `store-locked`,
        `schema-missing-table`, ...) y un detalle libre de secretos.
    During: solo almacena el par; no hace I/O.
    After: expone `.cause` y `.detail`; el CLI la traduce a EXIT_INFRA.
    """

    def __init__(self, cause: str, detail: str = "") -> None:
        super().__init__(f"{cause}: {detail}" if detail else cause)
        self.cause = cause
        self.detail = detail


class RowUnreadableError(ValueError):
    """Una fila concreta no se puede interpretar (payload o timestamp)."""


class TimestampFormError(RowUnreadableError):
    """created_at no tiene la forma canonica `.mmmZ` (fail-closed)."""


class UsageError(Exception):
    """Error de uso del CLI (se traduce a EXIT_USAGE, rc 12)."""


@dataclass(frozen=True)
class ExpectedAuthorization:
    """Frase canonica que el usuario debe teclear y sus piezas verificables.

    Before: las piezas las genera el wrapper DESDE GIT (repo, remoto, rama,
        sha12 y numero de commits del rango origin/main..HEAD).
    During: valida sha12 (hex minusculas de 12) y N >= 1; construye la frase.
    After: `phrase` es exactamente `PUSH <repo> <remoto>/<rama> <sha12> <N>`.
    """

    phrase: str
    sha12: str
    commit_count: int
    full_sha: str | None = None

    @classmethod
    def from_git_parts(
        cls,
        *,
        repo: str,
        remote: str,
        branch: str,
        sha12: str,
        commit_count: int,
        full_sha: str | None = None,
    ) -> ExpectedAuthorization:
        """Construye la frase canonica validando sus piezas.

        Before: cada pieza viene de git; no se acepta texto libre sin validar.
        During: exige sha12 hex-minusculas, N>=1 y piezas sin espacios ni
            backticks (un nombre de rama puede llevar barras).
        After: devuelve ExpectedAuthorization; ValueError si una pieza no vale.
        """
        if not _SHA12_RE.match(sha12):
            raise ValueError(f"sha12 no es hex minusculas de 12: {sha12!r}")
        if not isinstance(commit_count, int) or commit_count < 1:
            raise ValueError("commit_count debe ser entero >= 1")
        for label, value in (("repo", repo), ("remote", remote), ("branch", branch)):
            if not value:
                raise ValueError(f"{label} vacio")
            if any(ch.isspace() for ch in value) or "`" in value:
                raise ValueError(f"{label} contiene espacio o backtick: {value!r}")
        if "/" in remote:
            raise ValueError(f"remote no puede llevar barra: {remote!r}")
        if full_sha is not None and not _SHA_FULL_RE.match(full_sha):
            raise ValueError(f"full_sha no es hex minusculas de 40: {full_sha!r}")
        phrase = f"PUSH {repo} {remote}/{branch} {sha12} {commit_count}"
        return cls(
            phrase=phrase,
            sha12=sha12,
            commit_count=commit_count,
            full_sha=full_sha,
        )


@dataclass(frozen=True)
class MessageRecord:
    """Proyeccion normalizada de una fila de mensaje (sin exponer nada mas)."""

    message_id: str
    thread_id: str
    created_at: str
    updated_at: str
    streaming: bool
    created_by: str
    creation_source: str
    sender_thread_id: str | None
    sender_thread_present: bool
    text: str
    normalized_text: str | None
    created_dt: datetime


@dataclass(frozen=True)
class Decision:
    """Resultado del predicado.

    Before: la produce `find_authorization` o `revalidate`.
    During: allowed=False lleva un motivo machine-readable; allowed=True lleva
        el messageId elegido, su created_at y el sha256 del texto.
    After: el CLI imprime self-service con `format_decision` y usa
        EXIT_ALLOWED/EXIT_REJECTED/EXIT_INFRA segun corresponda.
    """

    allowed: bool
    reason: str
    message_id: str | None = None
    thread_id: str | None = None
    created_at: str | None = None
    text_sha256: str | None = None


CHAIN_HARD_MAX_DURATION_HOURS = 12
_CHAIN_TEXT_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def _parse_chain_expiry(value: str) -> datetime:
    """Parsea una caducidad ISO-8601 con zona explicita.

    Before: recibe una cadena de registro, no una hora local ambigua.
    During: usa `datetime.fromisoformat` y exige offset o zona UTC.
    After: devuelve datetime aware o ValueError fail-closed.
    """
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError("expiry-invalid") from exc
    if parsed.tzinfo is None:
        raise ValueError("expiry-zone-required")
    return parsed


def _parse_chain_successors(raw: object) -> tuple[str, ...]:
    """Valida la sucesion ordenada minima del registro de cadena."""
    successors = raw
    if (
        not isinstance(successors, list)
        or not successors
        or any(not isinstance(item, str) or not item for item in successors)
    ):
        raise ValueError("successors-invalid")
    if len(successors) < 2:
        raise ValueError("successors-too-short")
    return tuple(successors)


def _parse_chain_trigger(raw: object) -> int:
    """Valida el disparador y exige representación exacta en miles."""
    if isinstance(raw, bool) or not isinstance(raw, int) or raw <= 0:
        raise ValueError("trigger-invalid")
    if raw % 1000 != 0:
        raise ValueError("trigger-not-whole-k")
    return raw


_LITERAL_EDGE_PUNCTUATION = "()[]{}'\",;:.!?"


def _literal_tokens(text: str) -> list[str]:
    """Tokeniza por espacios y quita solo puntuación permitida de los bordes."""
    return [part.strip(_LITERAL_EDGE_PUNCTUATION) for part in text.split()]


@dataclass(frozen=True)
class ChainAuthorizationRecord:
    """Registro estructurado y revalidable de una autorizacion de cadena.

    Before: recibe un mapping persistido fuera del almacen de mensajes con
        sucesores ordenados, disparador, caducidad ISO con zona, texto literal,
        identidad del mensaje, createdAt del servidor y digest del texto.
    During: valida formas, conserva la cita literal y comprueba que cada campo
        operativo aparece en el mensaje exacto; la ventana se calcula desde
        createdAt del servidor, nunca desde el reloj del agente.
    After: devuelve un registro inmutable o lanza ValueError; los metodos de
        validacion devuelven None o un motivo fail-closed machine-readable.
    """

    successors: tuple[str, ...]
    trigger_context_tokens: int
    expires_at: datetime
    literal_text: str
    message_id: str
    created_at: str
    text_sha256: str
    max_duration_hours: int

    @classmethod
    def from_mapping(cls, raw: dict) -> ChainAuthorizationRecord:
        """Construye el registro comprobando tipos, UUID, digest y timestamps.

        Before: `raw` es el snapshot de autorizacion, no un mensaje confiado.
        During: valida todos los campos obligatorios y normaliza sucesores y
            fechas sin interpretar una hora local ambigua.
        After: devuelve un registro listo para revalidacion o ValueError con la
            primera discrepancia estructural.
        """
        successors = _parse_chain_successors(raw.get("successors"))
        message_id = raw.get("message_id")
        if not isinstance(message_id, str) or not _UUID36_RE.match(message_id):
            raise ValueError("message-id-form")
        literal_text = raw.get("literal_text")
        text_sha256 = raw.get("text_sha256")
        if not isinstance(literal_text, str) or not literal_text:
            raise ValueError("literal-text-invalid")
        if not isinstance(text_sha256, str) or not _CHAIN_TEXT_SHA_RE.match(
            text_sha256
        ):
            raise ValueError("text-digest-form")
        if sha256_text(literal_text) != text_sha256:
            raise ValueError("text-digest-mismatch")
        trigger = _parse_chain_trigger(raw.get("trigger_context_tokens"))
        max_duration = raw.get("max_duration_hours")
        if (
            isinstance(max_duration, bool)
            or not isinstance(max_duration, int)
            or not 1 <= max_duration <= CHAIN_HARD_MAX_DURATION_HOURS
        ):
            raise ValueError("duration-limit-invalid")
        created_at = raw.get("created_at")
        if not isinstance(created_at, str):
            raise ValueError("created-at-invalid")
        _parse_iso(created_at)
        expires_at_raw = raw.get("expires_at")
        if not isinstance(expires_at_raw, str):
            raise ValueError("expiry-invalid")
        expires_at = _parse_chain_expiry(expires_at_raw)
        return cls(
            successors=successors,
            trigger_context_tokens=trigger,
            expires_at=expires_at,
            literal_text=literal_text,
            message_id=message_id,
            created_at=created_at,
            text_sha256=text_sha256,
            max_duration_hours=max_duration,
        )

    def validate_literal(self, message_text: str) -> str | None:
        """Comprueba digest, sucesores, disparador y caducidad en texto entero.

        Before: `message_text` es el texto real revalidado del mensaje.
        During: exige el digest exacto y la secuencia textual de cada campo,
            sin aceptar que el registro estructurado invente datos ausentes. No
            comprueba `max_duration_hours`; los sucesores se validan
            estructuralmente en `from_mapping` y aquí se comprueba su secuencia
            literal delimitada.
        After: None si toda la evidencia textual coincide; en otro caso un
            motivo estable de rechazo.
        """
        if sha256_text(message_text) != self.text_sha256:
            return "text-digest-mismatch"
        if message_text != self.literal_text:
            return "literal-text-mismatch"
        tokens = _literal_tokens(message_text)
        cursor = 0
        for left, right in zip(self.successors, self.successors[1:], strict=False):
            pair_start = None
            for index in range(cursor, len(tokens) - 2):
                if (
                    tokens[index] == left
                    and tokens[index + 1] == "->"
                    and tokens[index + 2] == right
                ):
                    pair_start = index
                    break
            if pair_start is None:
                return "successors-not-literal"
            cursor = pair_start + 2
        trigger_token = f"{self.trigger_context_tokens // 1000}k"
        if trigger_token not in tokens:
            return "trigger-not-literal"
        if self.expires_at.isoformat() not in tokens:
            return "expiry-not-literal"
        return None

    def validate_server_window(self) -> str | None:
        """Rechaza plazos no positivos o mayores que el tope duro desde servidor.

        Before: `created_at` es el timestamp del mensaje servido por T3.
        During: compara ambos timestamps con zona y aplica el máximo de doce
            horas; no consulta datetime.now ni una hora del agente.
        After: None para una ventana válida o motivo fail-closed.
        """
        created = _parse_iso(self.created_at)
        if created.tzinfo is None:
            return "created-at-zone-required"
        delta = self.expires_at.astimezone(timezone.utc) - created.astimezone(
            timezone.utc
        )
        if delta.total_seconds() <= 0:
            return "expiry-not-after-created-at"
        if delta > timedelta(hours=self.max_duration_hours):
            return "expiry-over-hard-limit"
        return None


def revalidate_chain_authorization(
    connection: sqlite3.Connection,
    *,
    record: ChainAuthorizationRecord,
    anchor_message_id: str,
    now: datetime | None = None,
) -> Decision:
    """Revalida procedencia real y evidencia estructurada antes del consumo.

    Before: conexión de solo lectura, registro estructurado y ancla del pedido.
    During: valida la ventana desde createdAt servidor, aplica un limite
        exclusivo (`now >= expires_at` es caducado), valida el literal y relee
        el mensaje real, su hilo, createdAt, procedencia, UUID y ancla mediante
        el predicado comun de identidad. Si `now` se omite usa UTC solo en este
        instante; un reloj inyectado debe tener zona.
    After: devuelve Decision autorizada o rechazo fail-closed sin escribir el
        almacen de mensajes.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now-zone-required")
    reason = record.validate_server_window() or record.validate_literal(
        record.literal_text
    )
    if reason is not None:
        return Decision(False, f"chain-{reason}")
    if now.astimezone(timezone.utc) >= record.expires_at.astimezone(timezone.utc):
        return Decision(False, "chain-expired")
    thread_id = _thread_id_for_message(connection, record.message_id)
    row = _fetch_one(connection, _SQL_BY_MESSAGE_ID, (record.message_id,))
    if row is None:
        return Decision(False, "revalidation-missing")
    try:
        message = _row_to_record(row)
    except (TimestampFormError, RowUnreadableError):
        return Decision(False, "revalidation-unreadable")
    rejection = _revalidate_identity(
        connection,
        message,
        thread_id=thread_id,
        created_at=record.created_at,
        anchor_message_id=anchor_message_id,
    )
    if rejection is not None:
        return rejection
    if sha256_text(message.text) != record.text_sha256:
        return Decision(False, "chain-text-digest-mismatch")
    failure = _chain_candidate_failure(message, record.literal_text)
    if failure is not None:
        return Decision(False, failure)
    return Decision(
        True,
        "authorized",
        message_id=message.message_id,
        thread_id=message.thread_id,
        created_at=message.created_at,
        text_sha256=record.text_sha256,
    )


def sha256_text(text: str) -> str:
    """Digest estable del texto para el ledger y la revalidacion."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _strip_edges(text: str) -> str:
    return text.strip(_EDGE_WS)


def _unwrap_once(text: str) -> str:
    """Quita UNA sola envoltura: bloque de codigo o un par de comillas.

    Before: `text` ya viene recortado en extremos.
    During: si empieza y acaba en triple backtick, quita la cerca y un salto de
        linea inicial; si no, quita UN par de comillas iguales (" ' `).
    After: devuelve el interior recortado; nunca desenvuelve dos veces.
    """
    if len(text) >= 6 and text.startswith("```") and text.endswith("```"):
        inner = text[3:-3]
        if inner.startswith("\r\n"):
            inner = inner[2:]
        elif inner.startswith("\n"):
            inner = inner[1:]
        return _strip_edges(inner)
    for mark in ('"', "'", "`"):
        if len(text) >= 2 and text.startswith(mark) and text.endswith(mark):
            return _strip_edges(text[1:-1])
    return text


def normalize_text(text: object) -> str | None:
    """Normalizacion ASCII acotada del texto del usuario.

    Before: `text` es el valor crudo del payload (puede no ser str).
    During: (1) recorta extremos ASCII/NBSP; (2) quita UNA envoltura de bloque
        de codigo o de comillas; (3) sustituye NBSP por espacio; (4) colapsa
        runs de espacio y tabulador ASCII; (5) NO toca LF/CR, NO aplica NFKC,
        NO pliega mayusculas del resto de la frase (solo el verbo se compara
        sin caja en `matches_phrase`).
    After: devuelve el texto normalizado, o None si no es str. Un texto
        multilinea conserva sus saltos y por tanto NO iguala la frase.
    """
    if not isinstance(text, str):
        return None
    result = _strip_edges(text)
    result = _unwrap_once(result)
    result = result.replace("\u00a0", " ")
    result = _TOKEN_SPLIT_RE.sub(" ", result)
    return result


def _ascii_upper(value: str) -> str:
    """Mayusculas SOLO para ASCII a-z (sin plegado Unicode de confusables).

    Antes: `value` es un token del texto normalizado.
    Durante: mapea 'a'..'z' a 'A'..'Z'; cualquier otro caracter queda intacto
        (U+017F, U+212A, U+0131, fullwidth, etc. NO se pliegan).
    Despues: devuelve el token con caja ASCII, nunca con `str.upper()`.
    """
    return "".join(
        chr(ord(char) - 32) if "a" <= char <= "z" else char for char in value
    )


def matches_phrase(normalized_text: str | None, expected_phrase: str) -> bool:
    """Compara el texto ENTERO con la frase canonica (no subcadena).

    Before: `normalized_text` viene de `normalize_text`; `expected_phrase` la
        genera `ExpectedAuthorization.from_git_parts`.
    During: exige exactamente 5 tokens separados por un espacio; el verbo debe
        ser ASCII y se compara con la tabla ASCII (`_ascii_upper`), NUNCA con
        `str.upper/lower` de Unicode; repo, remoto/rama, sha12 y N se comparan
        EXACTOS contra la frase generada (N siempre >= 1). El sha debe ser
        ademas hex minusculas de 12 (defensa en profundidad). Un confusable
        no-ASCII (p.ej. U+017F) NO se pliega.
    After: True solo si el texto entero coincide.
    """
    if normalized_text is None:
        return False
    got = normalized_text.split(" ")
    exp = expected_phrase.split(" ")
    if len(got) != 5 or len(exp) != 5:
        return False
    if exp[0] != "PUSH":
        return False
    if not got[0].isascii():
        return False
    if _ascii_upper(got[0]) != "PUSH":
        return False
    if got[1:] != exp[1:]:
        return False
    return _SHA12_RE.match(got[3]) is not None


def _parse_iso(value: str) -> datetime:
    """Convierte created_at a datetime UTC; exige la forma canonica ESTRICTA.

    La unica forma aceptada es `^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}\\.\\d{3}Z$`,
    SIN recortar (un espacio extremo, un separador espacio, sin fraccion, 1 o 6
    decimales u offset se rechazan con `TimestampFormError`). Razon: el cursor
    SQL compara texto y la decision datetime; solo con `.mmmZ` ambos coinciden.
    """
    if not isinstance(value, str) or not _CANONICAL_TS_RE.fullmatch(value):
        raise TimestampFormError("created_at no tiene la forma canonica .mmmZ")
    text = value[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise RowUnreadableError(f"created_at no ISO-8601: {value!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _row_to_record(row: sqlite3.Row) -> MessageRecord:
    """Interpreta una fila; RowUnreadableError si payload o timestamp no sirven."""
    payload_raw = row["payload_json"]
    try:
        payload = json.loads(payload_raw) if isinstance(payload_raw, str) else None
    except (TypeError, ValueError) as exc:
        raise RowUnreadableError(f"payload_json no JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise RowUnreadableError("payload_json no es objeto")
    created_by = payload.get("createdBy")
    creation_source = payload.get("creationSource")
    raw_sender = payload.get("senderThreadId", _MISSING)
    sender_thread_present = raw_sender is not _MISSING and raw_sender is not None
    sender_thread_id = raw_sender if isinstance(raw_sender, str) else None
    text = payload.get("text")
    created_dt = _parse_iso(row["created_at"])
    return MessageRecord(
        message_id=str(row["message_id"]),
        thread_id=str(row["thread_id"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        streaming=bool(row["streaming"]),
        created_by=created_by if isinstance(created_by, str) else "",
        creation_source=creation_source if isinstance(creation_source, str) else "",
        sender_thread_id=sender_thread_id,
        sender_thread_present=sender_thread_present,
        text=text if isinstance(text, str) else "",
        normalized_text=normalize_text(text),
        created_dt=created_dt,
    )


def _classify_open_error(exc: sqlite3.Error, path: Path | None = None) -> str:
    """Clasifica el fallo de apertura; distingue ausente de existente-sin-permiso.

    Si SQLite dice "unable to open database file" y el path EXISTE (p.ej. un
    directorio o un fichero sin permisos) la causa es `store-permission`; si no
    existe, `store-missing`.
    """
    message = str(exc).lower()
    if "unable to open database file" in message or "cannot open" in message:
        if path is not None and path.exists():
            return "store-permission"
        return "store-missing"
    if "locked" in message or "busy" in message:
        return "store-locked"
    if "not a database" in message or "malformed" in message:
        return "store-corrupt"
    return "store-unavailable"


def _fetch_all(
    connection: sqlite3.Connection,
    sql: str,
    params: Sequence[object] = (),
) -> list[sqlite3.Row]:
    """Ejecuta una consulta de lectura y traduce CUALQUIER sqlite3.Error.

    Un fallo de SQLite despues de abrir (bloqueo, corrupcion, I/O) es
    infraestructura con causa nombrada `store-read-error` (rc 11), nunca una
    excepcion cruda ni un "no autorizado".
    """
    try:
        return connection.execute(sql, params).fetchall()
    except sqlite3.Error as exc:
        raise InfraError("store-read-error", str(exc)) from exc


def _fetch_one(
    connection: sqlite3.Connection,
    sql: str,
    params: Sequence[object] = (),
) -> sqlite3.Row | None:
    """Igual que `_fetch_all` para una sola fila (traduce sqlite3.Error)."""
    try:
        return connection.execute(sql, params).fetchone()
    except sqlite3.Error as exc:
        raise InfraError("store-read-error", str(exc)) from exc


def _thread_id_for_message(connection: sqlite3.Connection, message_id: str) -> str:
    """Resuelve el hilo del mensaje real para delegar la revalidacion comun.

    Before: `connection` tiene el esquema validado y `message_id` es la
        identidad del registro estructurado.
    During: lee una sola fila del almacen SQLite de solo lectura.
    After: devuelve el thread_id o eleva InfraError si la fila no existe o es
        ilegible; nunca inventa un hilo para autorizar.
    """
    row = _fetch_one(connection, _SQL_BY_MESSAGE_ID, (message_id,))
    if row is None:
        raise InfraError("message-missing", message_id)
    try:
        return _row_to_record(row).thread_id
    except (TimestampFormError, RowUnreadableError) as exc:
        raise InfraError("message-unreadable", str(exc)) from exc


def open_store_ro(db_path: str | Path) -> sqlite3.Connection:
    """Abre el almacen en SOLO LECTURA, sin `immutable` (WAL vivo).

    Before: `db_path` apunta al `statev2.sqlite` real o a una copia.
    During: abre con URI `mode=ro` y `PRAGMA query_only=ON`; fuerza una lectura
        de cabecera para que un fichero ausente/corrupto falle AQUI con causa
        nombrada. No usa `immutable=1` (ignoraria el WAL vivo).
    After: devuelve una conexion row_factory=Row; eleva InfraError con causa
        `store-missing`, `store-permission`, `store-locked`, `store-corrupt` o
        `store-unavailable`.
    """
    path = Path(db_path)
    try:
        uri = path.resolve().as_uri() + "?mode=ro"
    except (OSError, ValueError) as exc:
        raise InfraError("store-path-invalid", str(exc)) from exc
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(uri, uri=True, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        connection.execute("SELECT count(*) FROM sqlite_master").fetchone()
    except sqlite3.OperationalError as exc:
        if connection is not None:
            connection.close()
        raise InfraError(_classify_open_error(exc, path=path), str(exc)) from exc
    except sqlite3.DatabaseError as exc:
        if connection is not None:
            connection.close()
        raise InfraError("store-corrupt", str(exc)) from exc
    return connection


def check_schema(connection: sqlite3.Connection) -> None:
    """Smoke-test de esquema fail-closed.

    Before: conexion abierta en solo lectura.
    During: exige que existan las DOS tablas y sus columnas minimas (medidas
        contra una copia real en el PASO 0). No exige indices: su ausencia
        degrada rendimiento, no correccion.
    After: None si el esquema es el esperado; InfraError
        `schema-missing-table` o `schema-missing-column` en caso contrario.
    """
    for table, required in (
        (SCHEMA_MESSAGES, MESSAGE_COLUMNS),
        (SCHEMA_THREADS, THREAD_COLUMNS),
    ):
        found = _fetch_one(
            connection,
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        )
        if found is None:
            raise InfraError("schema-missing-table", table)
        columns = {
            str(row[1])
            for row in _fetch_all(connection, f'PRAGMA table_info("{table}")')
        }
        missing = [name for name in required if name not in columns]
        if missing:
            raise InfraError(
                "schema-missing-column", f"{table}: {', '.join(sorted(missing))}"
            )


def _iter_thread_messages(
    connection: sqlite3.Connection,
    thread_id: str,
    after_created_at: str,
    after_message_id: str,
) -> Iterator[sqlite3.Row]:
    """Itera SOLO los mensajes POSTERIORES al ancla, por cursor textual.

    Before: conexion validada; `thread_id` y el cursor (created_at, message_id)
        del ancla (o del ultimo de la pagina anterior).
    During: consulta `created_at > cursor OR (= AND message_id > cursor)` con
        LIMIT y paginacion por cursor (sin OFFSET); nunca consulta otros hilos
        ni mensajes anteriores al ancla. El orden de paginacion es textual; el
        orden SEMANTICO lo aplica `_scan_candidates` en Python por
        (datetime UTC, message_id).
    After: genera filas posteriores al ancla; eleva InfraError `scan-limit` si
        supera MAX_PAGES*PAGE_SIZE filas POSTERIORES al ancla. `_scan_candidates`
        lo convierte en RECHAZO rc 10 y NUNCA autoriza tras truncar.
    """
    cursor_created = after_created_at
    cursor_message_id = after_message_id
    scanned = 0
    max_rows = PAGE_SIZE * MAX_PAGES
    while True:
        remaining = max_rows - scanned
        limit = PAGE_SIZE if remaining >= PAGE_SIZE else remaining + 1
        rows = _fetch_all(
            connection,
            _SQL_THREAD_PAGE,
            (thread_id, cursor_created, cursor_created, cursor_message_id, limit),
        )
        if not rows:
            return
        if scanned + len(rows) > max_rows:
            raise InfraError(
                "scan-limit", f"more than {max_rows} rows after the anchor"
            )
        yield from rows
        scanned += len(rows)
        if len(rows) < limit:
            return
        last = rows[-1]
        cursor_created = str(last["created_at"])
        cursor_message_id = str(last["message_id"])


def _after_anchor(record: MessageRecord, anchor: MessageRecord) -> bool:
    return (record.created_dt, record.message_id) > (
        anchor.created_dt,
        anchor.message_id,
    )


def _candidate_failure(
    record: MessageRecord, expected: ExpectedAuthorization
) -> str | None:
    """Devuelve el primer motivo que impide autorizar, en orden de contrato."""
    if record.created_by != ACCEPTED_CREATED_BY:
        return "source-not-accepted"
    if record.creation_source not in ACCEPTED_SOURCES:
        return "source-not-accepted"
    if record.message_id.startswith(FORBIDDEN_MESSAGE_ID_PREFIXES):
        return "message-id-prefix"
    if not _UUID36_RE.match(record.message_id):
        return "message-id-form"
    if record.sender_thread_present:
        return "sender-thread"
    if record.streaming:
        return "not-final"
    if not matches_phrase(record.normalized_text, expected.phrase):
        return "text-mismatch"
    return None


def _chain_candidate_failure(record: MessageRecord, expected_text: str) -> str | None:
    """Aplica el predicado de procedencia sin imponer el verbo PUSH.

    Before: `record` es la fila releida y `expected_text` la cita estructurada.
    During: conserva las mismas barreras de identidad, procedencia, UUID,
        sender, estado final y compara el texto entero de cadena.
    After: devuelve el motivo de rechazo o None; nunca relaja una barrera del
        flujo PUSH, solo sustituye su frase esperada.
    """
    if record.created_by != ACCEPTED_CREATED_BY:
        return "source-not-accepted"
    if record.creation_source not in ACCEPTED_SOURCES:
        return "source-not-accepted"
    if record.message_id.startswith(FORBIDDEN_MESSAGE_ID_PREFIXES):
        return "message-id-prefix"
    if not _UUID36_RE.match(record.message_id):
        return "message-id-form"
    if record.sender_thread_present:
        return "sender-thread"
    if record.streaming:
        return "not-final"
    if record.normalized_text != expected_text:
        return "text-mismatch"
    return None


def _better_failure(current: str | None, candidate: str) -> str:
    if current is None:
        return candidate
    current_rank = (
        FAILURE_PRIORITY.index(current)
        if current in FAILURE_PRIORITY
        else len(FAILURE_PRIORITY)
    )
    candidate_rank = (
        FAILURE_PRIORITY.index(candidate)
        if candidate in FAILURE_PRIORITY
        else len(FAILURE_PRIORITY)
    )
    return candidate if candidate_rank < current_rank else current


def _load_anchor(
    connection: sqlite3.Connection, anchor_message_id: str
) -> tuple[MessageRecord | None, Decision | None]:
    """Carga el ancla; (None, rechazo) si no existe o no se puede leer."""
    row = _fetch_one(connection, _SQL_BY_MESSAGE_ID, (anchor_message_id,))
    if row is None:
        return None, Decision(False, "anchor-missing")
    try:
        return _row_to_record(row), None
    except TimestampFormError:
        return None, Decision(False, "timestamp-form")
    except RowUnreadableError:
        return None, Decision(False, "anchor-unreadable")


def _thread_rejection(connection: sqlite3.Connection, thread_id: str) -> str | None:
    """Motivo si el hilo del ancla no existe o esta borrado; None si vale."""
    row = _fetch_one(connection, _SQL_THREAD_STATE, (thread_id,))
    if row is None:
        return "anchor-thread-missing"
    if row["deleted_at"] is not None:
        return "thread-deleted"
    return None


def _evaluate_record(
    record: MessageRecord,
    *,
    anchor: MessageRecord,
    expected: ExpectedAuthorization,
    is_consumed: Callable[[str], bool] | None,
) -> tuple[Decision | None, str | None]:
    """Evalua un registro ordenado: (Decision, None) o (None, motivo)."""
    if not _after_anchor(record, anchor):
        return None, None
    failure = _candidate_failure(record, expected)
    if failure is not None:
        return None, failure
    if is_consumed is not None and is_consumed(record.message_id):
        return None, "consumed"
    return (
        Decision(
            True,
            "authorized",
            message_id=record.message_id,
            thread_id=record.thread_id,
            created_at=record.created_at,
            text_sha256=sha256_text(record.text),
        ),
        None,
    )


def _try_record(row: sqlite3.Row) -> tuple[MessageRecord | None, str | None]:
    """(registro, None) o (None, motivo) sin excepciones."""
    try:
        return _row_to_record(row), None
    except TimestampFormError:
        return None, "timestamp-form"
    except RowUnreadableError:
        return None, "payload-unreadable"


def _scan_candidates(
    connection: sqlite3.Connection,
    *,
    anchor: MessageRecord,
    expected: ExpectedAuthorization,
    is_consumed: Callable[[str], bool] | None,
) -> Decision:
    """Ordena y decide por (datetime UTC, message_id), el MISMO criterio.

    Before: conexion validada, ancla con `created_dt` en UTC.
    During: recoge SOLO los registros posteriores al ancla (cursor textual),
        los ordena en Python por (created_dt, message_id) y evalua en ese
        orden; el primero valido no consumido autoriza. `scan-limit` corta el
        recorrido y devuelve RECHAZO sin evaluar: nunca autoriza tras truncar.
    After: Decision (allow o motivo). Nunca usa el orden textual de SQL para
        decidir: solo para paginar.
    """
    best_failure: str | None = None
    records: list[MessageRecord] = []
    try:
        for row in _iter_thread_messages(
            connection, anchor.thread_id, anchor.created_at, anchor.message_id
        ):
            record, failure = _try_record(row)
            if record is not None:
                records.append(record)
            else:
                best_failure = _better_failure(best_failure, str(failure))
    except InfraError as exc:
        if exc.cause != "scan-limit":
            raise
        return Decision(False, "scan-limit")
    records.sort(key=lambda record: (record.created_dt, record.message_id))
    for record in records:
        decision, failure = _evaluate_record(
            record,
            anchor=anchor,
            expected=expected,
            is_consumed=is_consumed,
        )
        if decision is not None:
            return decision
        if failure is not None:
            best_failure = _better_failure(best_failure, failure)
    if best_failure is None:
        return Decision(False, "no-message-after-anchor")
    return Decision(False, best_failure)


def find_authorization(
    connection: sqlite3.Connection,
    *,
    anchor_message_id: str,
    expected: ExpectedAuthorization,
    is_consumed: Callable[[str], bool] | None = None,
) -> Decision:
    """Evalua el predicado completo sobre el hilo del ancla.

    Before: conexion al almacen, messageId ancla de la peticion del agente,
        frase esperada y, opcionalmente, un predicado de consumo (ledger).
    During: valida esquema, resuelve el ancla y su hilo (no borrado), recorre
        solo ese hilo, filtra por (datetime UTC, message_id) posterior al ancla y
        aplica el predicado. El hilo se compara por IGUALDAD EXACTA de
        `thread_id`: `mcp:<uuid>` y `<uuid>` son hilos DISTINTOS y no se
        normalizan. Tras un relevo, el ancla es la peticion nueva en el hilo
        nuevo (el ancla manda). Si varios candidatos valen, elige el PRIMERO no
        consumido en orden (datetime UTC, message_id). Nunca lee otros hilos.
    After: Decision. Motivos de rechazo: anchor-missing, anchor-unreadable,
        anchor-thread-missing, thread-deleted, no-message-after-anchor,
        source-not-accepted, message-id-prefix, sender-thread, not-final,
        text-mismatch, consumed, payload-unreadable, scan-limit.
    """
    check_schema(connection)
    anchor, rejection = _load_anchor(connection, anchor_message_id)
    if rejection is not None:
        return rejection
    if anchor is None:  # defensivo: _load_anchor siempre devuelve ancla o rechazo
        return Decision(False, "anchor-unreadable")
    thread_rejection = _thread_rejection(connection, anchor.thread_id)
    if thread_rejection is not None:
        return Decision(False, thread_rejection)
    return _scan_candidates(
        connection,
        anchor=anchor,
        expected=expected,
        is_consumed=is_consumed,
    )


def _revalidate_identity(
    connection: sqlite3.Connection,
    record: MessageRecord,
    *,
    thread_id: str,
    created_at: str,
    anchor_message_id: str,
) -> Decision | None:
    """Rechazo si hilo/ancla/posterioridad cambiaron; None si siguen igual."""
    if record.thread_id != thread_id:
        return Decision(False, "revalidation-thread")
    if _thread_rejection(connection, thread_id) is not None:
        return Decision(False, "revalidation-thread-state")
    if record.created_at != created_at:
        return Decision(False, "revalidation-edited")
    anchor_row = _fetch_one(connection, _SQL_BY_MESSAGE_ID, (anchor_message_id,))
    if anchor_row is None:
        return Decision(False, "revalidation-anchor-missing")
    try:
        anchor = _row_to_record(anchor_row)
    except TimestampFormError:
        return Decision(False, "revalidation-timestamp-form")
    except RowUnreadableError:
        return Decision(False, "revalidation-anchor-unreadable")
    if anchor.thread_id != thread_id:
        return Decision(False, "revalidation-thread")
    if not _after_anchor(record, anchor):
        return Decision(False, "revalidation-after-anchor")
    return None


def revalidate(
    connection: sqlite3.Connection,
    *,
    message_id: str,
    thread_id: str,
    created_at: str,
    text_sha256: str,
    anchor_message_id: str,
    expected: ExpectedAuthorization,
) -> Decision:
    """Revalida la identidad COMPLETA y el digest JUSTO antes del push.

    Before: el messageId, su thread_id/created_at, el digest y el ancla vienen
        del Decision que autorizo (identidad completa del candidato).
    During: relee la fila y exige que siga existiendo, que no cambie de hilo,
        que su hilo siga existiendo y NO este borrado, que su created_at sea el
        mismo, que el ancla exista en el mismo hilo y que el candidato siga
        siendo posterior al ancla por (datetime UTC, message_id); despues
        comprueba digest, procedencia y frase.
    After: Decision allowed=True con la identidad/digest, o False con
        `revalidation-missing`, `revalidation-unreadable`,
        `revalidation-thread`, `revalidation-thread-state`,
        `revalidation-edited`, `revalidation-anchor-missing`,
        `revalidation-anchor-unreadable`, `revalidation-after-anchor`,
        `revalidation-provenance` o `revalidation-text`.
    """
    check_schema(connection)
    row = _fetch_one(connection, _SQL_BY_MESSAGE_ID, (message_id,))
    if row is None:
        return Decision(False, "revalidation-missing")
    try:
        record = _row_to_record(row)
    except TimestampFormError:
        return Decision(False, "revalidation-timestamp-form")
    except RowUnreadableError:
        return Decision(False, "revalidation-unreadable")
    rejection = _revalidate_identity(
        connection,
        record,
        thread_id=thread_id,
        created_at=created_at,
        anchor_message_id=anchor_message_id,
    )
    if rejection is not None:
        return rejection
    if sha256_text(record.text) != text_sha256:
        return Decision(False, "revalidation-edited")
    failure = _candidate_failure(record, expected)
    if failure == "text-mismatch":
        return Decision(False, "revalidation-text")
    if failure is not None:
        return Decision(False, "revalidation-provenance")
    return Decision(
        True,
        "authorized",
        message_id=record.message_id,
        thread_id=record.thread_id,
        created_at=record.created_at,
        text_sha256=text_sha256,
    )


_REASON_TEXT = {
    "anchor-missing": "el ancla de la peticion no existe en el almacen",
    "anchor-unreadable": "el ancla existe pero su fila no se puede leer",
    "anchor-thread-missing": "el hilo del ancla no existe en la proyeccion",
    "thread-deleted": "el hilo del ancla esta marcado como borrado",
    "no-message-after-anchor": (
        "no hay ningun mensaje valido en el hilo del ancla posterior a la peticion"
    ),
    "source-not-accepted": (
        "el mensaje que autoriza no es del usuario: exige createdBy=user y "
        "creationSource web o mobile (un evento automatico no es consentimiento)"
    ),
    "message-id-prefix": (
        "el messageId del mensaje es automatico (lleva un prefijo prohibido), "
        "no una confirmacion tecleada"
    ),
    "message-id-form": (
        "el messageId no tiene forma UUID de 36 y no lleva un prefijo automatico "
        "conocido"
    ),
    "sender-thread": "el mensaje viene de otro hilo (senderThreadId presente)",
    "not-final": "el mensaje aun esta en streaming: no es texto final",
    "text-mismatch": "el texto NO coincide ENTERO con la frase canonica",
    "consumed": (
        "esa confirmacion ya se uso antes (un solo uso; un lock huerfano del "
        "ledger, aunque no tenga linea, tambien cuenta como consumido)"
    ),
    "payload-unreadable": "una fila candidata tiene un payload ilegible",
    "timestamp-form": (
        "un timestamp no tiene la forma canonica .mmmZ (offset o formato no "
        "soportado); fail-closed"
    ),
    "revalidation-timestamp-form": (
        "un timestamp dejo de tener la forma .mmmZ entre la verificacion y el "
        "push; la confirmacion quedo CONSUMIDA"
    ),
    "scan-limit": (
        "el hilo tiene mas de 10.000 mensajes posteriores al ancla; el escaneo "
        "se corto y NO se autoriza. Remedio: pide una NUEVA peticion (ancla "
        "nueva) y repite el comando con --anchor-message-id del ancla nueva"
    ),
    "push-failed": "el push fallo; la confirmacion quedo CONSUMIDA (un solo uso)",
    "ls-remote-failed": (
        "no se pudo verificar el remoto tras el push; la confirmacion quedo CONSUMIDA"
    ),
    "ls-remote-mismatch": (
        "la ref remota no apunta al SHA probado; la confirmacion quedo CONSUMIDA"
    ),
    "head-moved": (
        "HEAD cambio entre la validacion y el push; no se empujo y la "
        "confirmacion quedo CONSUMIDA"
    ),
    "head-unreadable": (
        "no se pudo releer HEAD antes del push; no se empujo y la confirmacion "
        "quedo CONSUMIDA"
    ),
    "remote-moved": (
        "el remoto/rama avanzo entre la verificacion y el push; no se publico y "
        "la confirmacion quedo CONSUMIDA"
    ),
    "remote-unreadable": (
        "no se pudo releer la ref remota antes del push; no se publico y la "
        "confirmacion quedo CONSUMIDA"
    ),
    "revalidation-thread": (
        "el mensaje cambio de hilo entre la verificacion y el push"
    ),
    "revalidation-thread-state": (
        "el hilo del mensaje desaparecio o se borro entre la verificacion y el push"
    ),
    "revalidation-anchor-missing": (
        "el ancla desaparecio entre la verificacion y el push"
    ),
    "revalidation-anchor-unreadable": (
        "el ancla dejo de ser legible entre la verificacion y el push"
    ),
    "revalidation-after-anchor": (
        "el mensaje dejo de ser posterior al ancla entre la verificacion y el push"
    ),
    "revalidation-edited": (
        "el mensaje cambio entre la verificacion y el push; la confirmacion "
        "quedo CONSUMIDA"
    ),
    "revalidation-missing": (
        "el mensaje desaparecio entre la verificacion y el push; la confirmacion "
        "quedo CONSUMIDA"
    ),
    "revalidation-unreadable": (
        "el mensaje dejo de ser legible entre la verificacion y el push; la "
        "confirmacion quedo CONSUMIDA"
    ),
    "revalidation-provenance": (
        "la procedencia del mensaje cambio entre la verificacion y el push; la "
        "confirmacion quedo CONSUMIDA"
    ),
    "revalidation-text": (
        "el texto dejo de coincidir con la frase entre la verificacion y el push; "
        "la confirmacion quedo CONSUMIDA"
    ),
}


def describe_reason(reason: str) -> str:
    """Traduce un motivo machine-readable a una frase self-service."""
    return _REASON_TEXT.get(reason, f"motivo no autorizado ({reason})")


def format_decision(decision: Decision, expected: ExpectedAuthorization) -> str:
    """Mensaje self-service: que fallo, la frase exacta y como repetir.

    Before: Decision del predicado y la frase esperada (generada desde git).
    During: compone un texto sin rutas ni identificadores de otros hilos.
    After: devuelve el bloque imprimible; no hace I/O ni toca el repo.
    """
    if decision.allowed:
        return "AUTORIZADO: mensaje del usuario verificado en el hilo del ancla."
    lines = [
        f"NO AUTORIZADO ({decision.reason}): {describe_reason(decision.reason)}.",
        "Frase exacta que debes escribir (texto ENTERO, en el hilo de la peticion):",
        expected.phrase,
        "Como repetir: envia exactamente esa frase como mensaje tuyo (web o movil) "
        "en el hilo de la peticion, despues del ancla; no hace falta escalar.",
    ]
    burn_reasons = {
        "consumed",
        "push-failed",
        "ls-remote-failed",
        "ls-remote-mismatch",
        "head-moved",
        "head-unreadable",
        "remote-moved",
        "remote-unreadable",
        "revalidation-edited",
        "revalidation-missing",
        "revalidation-unreadable",
        "revalidation-provenance",
        "revalidation-text",
        "revalidation-thread",
        "revalidation-thread-state",
        "revalidation-anchor-missing",
        "revalidation-anchor-unreadable",
        "revalidation-after-anchor",
        "revalidation-timestamp-form",
    }
    if decision.reason in burn_reasons:
        lines.append(
            "La confirmacion anterior quedo CONSUMIDA (un solo uso): envia un "
            "mensaje NUEVO con la frase exacta tras corregir la causa."
        )
    if decision.reason == "scan-limit":
        lines.append(
            "Remedio: pide una NUEVA peticion en el hilo (ancla nueva) y repite "
            "el comando con --anchor-message-id del ancla nueva; reenviar la "
            "frase tras el ancla vieja NO lo resuelve."
        )
    return "\n".join(lines)


LEDGER_RELPATH = Path(".agent") / "runtime" / "session" / "push_authority_ledger.jsonl"

_CONTEXT_REASON_TEXT = {
    "tested-sha-mismatch": "el SHA probado no coincide con HEAD",
    "remote-ref-missing": "el remoto/rama no existe tras el fetch",
    "not-ancestor": "el remoto/rama ya no es ancestro de HEAD (rebasa o revisa)",
    "nothing-to-push": "no hay commits en el rango remoto/rama..HEAD",
    "ambiguous-sha12": "el sha12 es ambiguo: no identifica un unico commit",
    "pushurl-count": (
        "el remoto tiene 0 o varias URLs de push (remote.<n>.pushurl); exige "
        "exactamente una para saber donde se publica"
    ),
    "pushurl-mismatch": (
        "la URL de push difiere de la URL de fetch/identidad mostrada; no se "
        "empuja hasta que coincidan"
    ),
}


@dataclass(frozen=True)
class PushContext:
    """Contexto del push generado DESDE GIT (nunca por el agente).

    Before: lo produce `collect_push_context` tras validar HEAD, fetch,
        ancestro y numero de commits.
    During: transporta las piezas y la frase canonica ya construida.
    After: `expected.phrase` es exactamente la que el usuario debe teclear.
    """

    project_root: Path
    remote: str
    branch: str
    repo: str
    full_sha: str
    sha12: str
    commit_count: int
    remote_sha: str
    expected: ExpectedAuthorization


@dataclass(frozen=True)
class ExecutionResult:
    """Resultado de verificar y (si procede) ejecutar el push."""

    exit_code: int
    decision: Decision
    pushed: bool = False
    push_rc: int = 0
    detail: str = ""


class PushAuthorityLedger:
    """Ledger append-only con consumo atomico de un solo uso (O_EXCL).

    Before: `path` apunta a `push_authority_ledger.jsonl` (propio, NUNCA
        comms_ledger). El directorio de locks vive junto al ledger.
    During: `consume` crea un fichero lock con `O_CREAT|O_EXCL` por messageId
        (el ganador es unico) y despues anade UNA linea JSON al ledger. Si el
        append falla, retira el lock para permitir reintento y eleva
        `ledger-append-failed`.
    After: `is_consumed` es True si existe el lock o el ledger ya tiene la
        linea. Los campos obligatorios del registro son messageId, createdAt,
        textSha256, fullSha y anchorMessageId.
    """

    REQUIRED_FIELDS = (
        "messageId",
        "createdAt",
        "textSha256",
        "fullSha",
        "anchorMessageId",
    )

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    @classmethod
    def default(cls, project_root: str | Path) -> PushAuthorityLedger:
        """Ledger canonico del proyecto (gitignored bajo .agent/runtime)."""
        return cls(Path(project_root).resolve() / LEDGER_RELPATH)

    @property
    def lock_dir(self) -> Path:
        return self.path.parent / (self.path.name + ".locks")

    @staticmethod
    def _key(message_id: str) -> str:
        return hashlib.sha256(message_id.encode("utf-8")).hexdigest()

    def _lock_path(self, message_id: str) -> Path:
        return self.lock_dir / (self._key(message_id) + ".lock")

    def is_consumed(self, message_id: str) -> bool:
        """True si el messageId ya fue consumido.

        Un lock existente cuenta aunque NO haya linea en el ledger (lock
        huerfano: el consumo se considero hecho); una linea sin lock tambien
        cuenta. En ambos casos el motivo `consumed` lo explica en self-service.
        """
        if self._lock_path(message_id).exists():
            return True
        if not self.path.exists():
            return False
        key = self._key(message_id)
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                for raw in handle:
                    stripped = raw.strip()
                    if not stripped:
                        continue
                    try:
                        record = json.loads(stripped)
                    except ValueError:
                        continue
                    if record.get("messageId") == message_id:
                        return True
                    if record.get("messageIdSha256") == key:
                        return True
        except OSError as exc:
            raise InfraError("ledger-unreadable", str(exc)) from exc
        return False

    def consume(self, record: dict) -> bool:
        """Consume el messageId de forma atomica; False si ya estaba usado."""
        missing = [name for name in self.REQUIRED_FIELDS if not record.get(name)]
        if missing:
            raise ValueError(f"registro de ledger incompleto: {', '.join(missing)}")
        message_id = str(record["messageId"])
        if self.is_consumed(message_id):
            return False
        payload = {**record, "messageIdSha256": self._key(message_id)}
        try:
            self.lock_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise InfraError("ledger-lock-failed", str(exc)) from exc
        lock_path = self._lock_path(message_id)
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            return False
        except OSError as exc:
            raise InfraError("ledger-lock-failed", str(exc)) from exc
        try:
            os.write(
                descriptor, json.dumps(payload, ensure_ascii=False).encode("utf-8")
            )
        finally:
            os.close(descriptor)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(payload, ensure_ascii=False) + "\n"
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(line)
        except OSError as exc:
            with contextlib.suppress(OSError):
                lock_path.unlink()
            raise InfraError("ledger-append-failed", str(exc)) from exc
        return True


class ChainAuthorityLedger:
    """Ledger append-only de consumo por `(messageId, step)`.

    Before: `path` apunta al ledger propio de la cadena y cada transición
        aporta un messageId, ordinal positivo y códigos de salida/entrada.
    During: adquiere un lock O_EXCL por clave compuesta y añade una línea JSON;
        un mismo mensaje puede autorizar pasos distintos, pero nunca repetir
        el mismo paso.
    After: `consume` devuelve True solo al ganador del paso, False en replay, y
        `is_consumed` consulta locks o líneas sin modificar el ledger.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    @staticmethod
    def _key(message_id: str, step: int) -> str:
        return hashlib.sha256(f"{message_id}:{step}".encode()).hexdigest()

    def _lock_path(self, message_id: str, step: int) -> Path:
        return (
            self.path.parent
            / (self.path.name + ".locks")
            / (self._key(message_id, step) + ".lock")
        )

    @staticmethod
    def _strict_json_loads(raw: str) -> object:
        """Decodifica una línea y rechaza claves duplicadas o constantes no finitas."""

        def reject_duplicate_pairs(
            pairs: list[tuple[str, object]],
        ) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("duplicate-json-key")
                result[key] = value
            return result

        def reject_constant(value: str) -> object:
            raise ValueError(f"non-finite-json-constant: {value}")

        return json.loads(
            raw,
            object_pairs_hook=reject_duplicate_pairs,
            parse_constant=reject_constant,
        )

    def _iter_records(self) -> Iterator[dict[str, object]]:
        """Lee registros JSONL y convierte corrupción de bytes en InfraError."""
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                for raw in handle:
                    stripped = raw.strip()
                    if not stripped:
                        continue
                    try:
                        item = self._strict_json_loads(stripped)
                    except (TypeError, ValueError, RecursionError) as exc:
                        raise InfraError("chain-ledger-corrupt-line", str(exc)) from exc
                    if (
                        not isinstance(item, dict)
                        or not isinstance(item.get("messageId"), str)
                        or isinstance(item.get("step"), bool)
                        or not isinstance(item.get("step"), int)
                    ):
                        raise InfraError("chain-ledger-corrupt-line", "invalid object")
                    yield item
        except OSError as exc:
            raise InfraError("chain-ledger-unreadable", str(exc)) from exc
        except UnicodeError as exc:
            raise InfraError("chain-ledger-corrupt-line", str(exc)) from exc

    def is_consumed(self, message_id: str, step: int) -> bool:
        """Comprueba el consumo compuesto sin considerar el mensaje completo.

        Before: `step` es un ordinal entero positivo.
        During: revisa lock y las líneas recorridas del ledger JSONL hasta
            hallar evidencia de consumo; ignora líneas vacías y valida que cada
            línea recorrida sea un objeto con `messageId` textual y `step` entero.
            El decodificador rechaza duplicados y constantes no finitas.
        After: devuelve True solo para la misma pareja messageId/step; un lock
            existente siempre bloquea el replay, incluso sin linea de log.
        """
        if isinstance(step, bool) or not isinstance(step, int) or step < 1:
            raise ValueError("step-invalid")
        if self._lock_path(message_id, step).exists():
            return True
        if not self.path.exists():
            return False
        for item in self._iter_records():
            if item["messageId"] == message_id and item["step"] == step:
                return True
        return False

    def consume(self, message_id: str, step: int, out_code: str, in_code: str) -> bool:
        """Consume exactamente una transición de la cadena.

        Before: messageId, ordinal y códigos describen una transición real.
        During: crea el lock exclusivo y persiste una línea append-only.
        After: devuelve True una vez; replay o contienda devuelve False y los
            errores de I/O se convierten en InfraError.
        """
        if isinstance(step, bool) or not isinstance(step, int) or step < 1:
            raise ValueError("step-invalid")
        if not message_id or not out_code or not in_code:
            raise ValueError("transition-invalid")
        if self.is_consumed(message_id, step):
            return False
        lock_path = self._lock_path(message_id, step)
        try:
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            return False
        except OSError as exc:
            raise InfraError("chain-ledger-lock-failed", str(exc)) from exc
        payload = {
            "messageId": message_id,
            "step": step,
            "outCode": out_code,
            "inCode": in_code,
        }
        try:
            os.write(
                descriptor, json.dumps(payload, ensure_ascii=False).encode("utf-8")
            )
        except OSError as exc:
            with contextlib.suppress(OSError):
                os.close(descriptor)
            with contextlib.suppress(OSError):
                _ORIGINAL_OS_CLOSE(descriptor)
            with contextlib.suppress(OSError):
                lock_path.unlink()
            raise InfraError("chain-ledger-lock-write-failed", str(exc)) from exc
        try:
            os.close(descriptor)
        except OSError as exc:
            with contextlib.suppress(OSError):
                _ORIGINAL_OS_CLOSE(descriptor)
            with contextlib.suppress(OSError):
                lock_path.unlink()
            raise InfraError("chain-ledger-lock-close-failed", str(exc)) from exc
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except OSError as exc:
            with contextlib.suppress(OSError):
                lock_path.unlink()
            raise InfraError("chain-ledger-append-failed", str(exc)) from exc
        return True


def _default_git_runner(
    project_root: Path,
) -> Callable[[Sequence[str]], tuple[int, str, str]]:
    """Ejecuta git en `project_root` y devuelve (rc, stdout, stderr)."""

    def run(args: Sequence[str]) -> tuple[int, str, str]:
        try:
            command = ["git", *args]
            completed = subprocess.run(  # noqa: S603 - sin shell, argv controlado
                command,
                cwd=str(project_root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except OSError as exc:
            raise InfraError("git-unavailable", str(exc)) from exc
        return completed.returncode, completed.stdout, completed.stderr

    return run


def _repo_from_url(url: str) -> str:
    """Extrae el nombre del repo de la URL de un remoto (sin .git)."""
    raw = url.strip().replace("\\", "/").rstrip("/")
    if raw.endswith(".git"):
        raw = raw[:-4]
    return raw.rsplit("/", 1)[-1].rsplit(":", 1)[-1]


def _resolve_unique_commit(
    run: Callable[[Sequence[str]], tuple[int, str, str]],
    sha12: str,
    full_sha: str,
) -> str | None:
    """None si `sha12` resuelve de forma UNICA a `full_sha`; si no, motivo."""
    rc, out, _err = run(["rev-parse", "--verify", f"{sha12}^{{commit}}"])
    if rc != 0:
        return "ambiguous-sha12"
    if out.strip().lower() != full_sha:
        return "ambiguous-sha12"
    return None


def _head_full_sha(
    run: Callable[[Sequence[str]], tuple[int, str, str]],
) -> str:
    """Valida repo y HEAD; devuelve el SHA completo de HEAD (lowercase)."""
    rc, out, err = run(["rev-parse", "--is-inside-work-tree"])
    if rc != 0 or out.strip() != "true":
        raise InfraError("git-not-a-repository", err.strip()[:300])
    rc, out, err = run(["rev-parse", "HEAD"])
    if rc != 0:
        raise InfraError("git-head-unreadable", err.strip()[:300])
    full_sha = out.strip().lower()
    if not _SHA_FULL_RE.match(full_sha):
        raise InfraError("git-head-unreadable", full_sha[:80])
    return full_sha


def _range_commit_count(
    run: Callable[[Sequence[str]], tuple[int, str, str]],
    remote: str,
    branch: str,
) -> tuple[int, str, str | None]:
    """Fetch, ancestro, conteo del rango y SHA esperado del remoto/rama.

    Before: runner de git y remoto/rama.
    During: `git fetch --prune`, resuelve `<remote>/<branch>` y guarda su SHA
        completo (base esperada para `--force-with-lease`), comprueba ancestro
        y cuenta `remoto/rama..HEAD`.
    After: (count, remote_sha, None) o (0, remote_sha, motivo). Un fallo de
        infraestructura eleva InfraError `git-*`.
    """
    rc, _out, err = run(["fetch", "--prune", remote])
    if rc != 0:
        raise InfraError("git-fetch-failed", err.strip()[:300])
    remote_ref = f"{remote}/{branch}"
    rc, out, _err = run(["rev-parse", "--verify", f"{remote_ref}^{{commit}}"])
    if rc != 0:
        return 0, "", "remote-ref-missing"
    remote_sha = out.strip().lower()
    if not _SHA_FULL_RE.match(remote_sha):
        raise InfraError("git-remote-sha-unreadable", remote_sha[:80])
    rc, _out, err = run(["merge-base", "--is-ancestor", remote_ref, "HEAD"])
    if rc == 1:
        return 0, remote_sha, "not-ancestor"
    if rc != 0:
        raise InfraError("git-ancestor-check-failed", err.strip()[:300])
    rc, out, err = run(["rev-list", "--count", f"{remote_ref}..HEAD"])
    if rc != 0:
        raise InfraError("git-count-failed", err.strip()[:300])
    try:
        count = int(out.strip())
    except ValueError as exc:
        raise InfraError("git-count-unreadable", out.strip()[:80]) from exc
    if count < 1:
        return 0, remote_sha, "nothing-to-push"
    return count, remote_sha, None


def collect_push_context(
    project_root: str | Path,
    *,
    tested_commit_sha: str | None,
    remote: str = "origin",
    branch: str = "main",
    git_runner: Callable[[Sequence[str]], tuple[int, str, str]] | None = None,
) -> tuple[PushContext | None, str | None]:
    """Genera el contexto del push DESDE GIT (frase incluida).

    Before: `project_root` es el checkout; `tested_commit_sha` el SHA que paso
        la suite (None solo para `--print-phrase`, donde se usa HEAD).
    During: valida repo y HEAD, exige tested==HEAD, ejecuta
        `git fetch --prune <remote>` (ESCRIBE `FETCH_HEAD` y las refs
        remote-tracking del repo: NO es read-only), comprueba que el remoto/rama
        es ANCESTRO de HEAD, cuenta el rango, exige sha12 no ambiguo y deriva el
        repo de la URL del remoto.
    After: (PushContext, None) o (None, motivo). Un fallo de git o de red eleva
        InfraError con causa `git-*` (nunca se disfraza de no autorizado).
    """
    root = Path(project_root).resolve()
    run = git_runner or _default_git_runner(root)
    full_sha = _head_full_sha(run)
    if tested_commit_sha is not None and tested_commit_sha.strip().lower() != full_sha:
        return None, "tested-sha-mismatch"
    commit_count, remote_sha, reason = _range_commit_count(run, remote, branch)
    if reason is not None:
        return None, reason
    sha12 = full_sha[:12]
    ambiguity = _resolve_unique_commit(run, sha12, full_sha)
    if ambiguity is not None:
        return None, ambiguity
    rc, fetch_url, err = run(["remote", "get-url", remote])
    if rc != 0:
        raise InfraError("git-remote-unreadable", err.strip()[:300])
    rc, push_urls_raw, err = run(["remote", "get-url", "--push", "--all", remote])
    if rc != 0:
        raise InfraError("git-remote-unreadable", err.strip()[:300])
    push_urls = [line.strip() for line in push_urls_raw.splitlines() if line.strip()]
    if len(push_urls) != 1:
        return None, "pushurl-count"
    if push_urls[0] != fetch_url.strip():
        return None, "pushurl-mismatch"
    repo = _repo_from_url(push_urls[0])
    if not repo:
        raise InfraError(
            "git-remote-unreadable", "no se pudo derivar el nombre del repo"
        )
    expected = ExpectedAuthorization.from_git_parts(
        repo=repo,
        remote=remote,
        branch=branch,
        sha12=sha12,
        commit_count=commit_count,
        full_sha=full_sha,
    )
    return (
        PushContext(
            project_root=root,
            remote=remote,
            branch=branch,
            repo=repo,
            full_sha=full_sha,
            sha12=sha12,
            commit_count=commit_count,
            remote_sha=remote_sha,
            expected=expected,
        ),
        None,
    )


def build_prompt_link(*, environment_id: str, thread_id: str, phrase: str) -> str:
    """Construye el enlace `t3code://threads/<env>/<hilo>?prompt=<frase>`.

    El id del hilo conserva el prefijo `mcp:` sin codificar (los dos puntos);
    la frase se URL-encodea entera. Un enlace es un BORRADOR: no autoriza.
    """
    thread = quote(thread_id, safe=":")
    prompt = quote(phrase, safe="")
    env = quote(environment_id, safe="")
    return f"t3code://threads/{env}/{thread}?prompt={prompt}"


def execute_authorized_push(
    context: PushContext,
    *,
    anchor_message_id: str,
    db_path: str | Path,
    ledger: PushAuthorityLedger,
    dry_run: bool = False,
    git_runner: Callable[[Sequence[str]], tuple[int, str, str]] | None = None,
) -> ExecutionResult:
    """Verifica la autorizacion, la consume y ejecuta el push en un comando.

    Before: contexto de git, ancla, almacen y ledger.
    During: (1) `find_authorization`; (2) si dry_run, para sin consumir ni
        empujar; (3) consume el messageId de forma atomica; (4) revalida la
        identidad COMPLETA (messageId, thread_id, created_at, ancla no borrada y
        posterioridad) y el digest JUSTO antes del push (si falla, el mensaje
        queda quemado: fail-closed); (5) exige HEAD == full_sha justo antes del
        push (si HEAD se movio, no empuja y falla cerrado); (6) relee la ref
        remota y exige que siga en `remote_sha` (si se movio, no empuja); (7)
        push con refspec explicito `<full_sha>:refs/heads/<branch>` (el SHA
        PROBADO, NUNCA HEAD mutable) condicionado con
        `--force-with-lease=refs/heads/<branch>:<remote_sha>` (SIN `--force` a
        secas ni `--all`); (8) verifica con `ls-remote` que la ref remota apunta
        al SHA completo.
    After: ExecutionResult con EXIT_ALLOWED, EXIT_REJECTED, EXIT_INFRA (via
        excepcion) o EXIT_PUSH_FAILED (`push-failed`, `ls-remote-failed`,
        `ls-remote-mismatch`). Cualquier fallo DESPUES del consumo (incluido
        push-failed) deja el messageId QUEMADO: el usuario debe enviar un
        mensaje NUEVO con la frase exacta; `format_decision` lo explica.
    """
    connection = open_store_ro(db_path)
    try:
        decision = find_authorization(
            connection,
            anchor_message_id=anchor_message_id,
            expected=context.expected,
            is_consumed=ledger.is_consumed,
        )
        if not decision.allowed:
            return ExecutionResult(EXIT_REJECTED, decision)
        if dry_run:
            return ExecutionResult(EXIT_ALLOWED, decision, pushed=False)
        record = {
            "messageId": decision.message_id,
            "threadId": decision.thread_id,
            "createdAt": decision.created_at,
            "textSha256": decision.text_sha256,
            "fullSha": context.full_sha,
            "anchorMessageId": anchor_message_id,
        }
        if not ledger.consume(record):
            return ExecutionResult(EXIT_REJECTED, Decision(False, "consumed"))
        again = revalidate(
            connection,
            message_id=str(decision.message_id),
            thread_id=str(decision.thread_id),
            created_at=str(decision.created_at),
            text_sha256=str(decision.text_sha256),
            anchor_message_id=anchor_message_id,
            expected=context.expected,
        )
        if not again.allowed:
            return ExecutionResult(EXIT_REJECTED, again)
    finally:
        connection.close()

    return _push_and_verify(context, decision, git_runner)


def _push_and_verify(
    context: PushContext,
    decision: Decision,
    git_runner: Callable[[Sequence[str]], tuple[int, str, str]] | None,
) -> ExecutionResult:
    """Relee HEAD y la ref remota, empuja con lease y verifica con ls-remote.

    Before: contexto, Decision ya consumida/revalidada y runner de git.
    During: exige HEAD == full_sha; relee la ref remota y exige remote_sha;
        empuja full_sha a la rama con `--force-with-lease=...:<remote_sha>` (sin
        `--force` a secas ni `--all`); verifica con ls-remote el SHA publicado.
    After: ExecutionResult allowed o EXIT_PUSH_FAILED con motivo nombrado. Un
        fallo aqui ya dejo el messageId consumido (quemado).
    """
    run = git_runner or _default_git_runner(context.project_root)
    rc, out, err = run(["rev-parse", "HEAD"])
    if rc != 0:
        return ExecutionResult(
            EXIT_PUSH_FAILED,
            Decision(False, "head-unreadable"),
            detail=err.strip()[:500],
            push_rc=rc,
        )
    if out.strip().lower() != context.full_sha:
        return ExecutionResult(
            EXIT_PUSH_FAILED,
            Decision(False, "head-moved"),
            detail=out.strip()[:64],
        )
    rc, out, err = run(["ls-remote", context.remote, f"refs/heads/{context.branch}"])
    if rc != 0:
        return ExecutionResult(
            EXIT_PUSH_FAILED,
            Decision(False, "remote-unreadable"),
            detail=err.strip()[:500],
            push_rc=rc,
        )
    fields = out.split()
    current_remote = fields[0].strip().lower() if fields else ""
    if current_remote != context.remote_sha:
        return ExecutionResult(
            EXIT_PUSH_FAILED,
            Decision(False, "remote-moved"),
            detail=current_remote[:64],
        )
    rc, _out, err = run(
        [
            "-c",
            "push.followTags=false",
            "push",
            f"--force-with-lease=refs/heads/{context.branch}:{context.remote_sha}",
            context.remote,
            f"{context.full_sha}:refs/heads/{context.branch}",
        ]
    )
    if rc != 0:
        return ExecutionResult(
            EXIT_PUSH_FAILED,
            Decision(False, "push-failed"),
            detail=err.strip()[:500],
            push_rc=rc,
        )
    rc, out, err = run(["ls-remote", context.remote, f"refs/heads/{context.branch}"])
    if rc != 0:
        return ExecutionResult(
            EXIT_PUSH_FAILED,
            Decision(False, "ls-remote-failed"),
            pushed=True,
            detail=err.strip()[:500],
            push_rc=rc,
        )
    fields = out.split()
    remote_sha = fields[0].strip().lower() if fields else ""
    if remote_sha != context.full_sha:
        return ExecutionResult(
            EXIT_PUSH_FAILED,
            Decision(False, "ls-remote-mismatch"),
            pushed=True,
            detail=remote_sha[:64],
        )
    return ExecutionResult(
        EXIT_ALLOWED,
        Decision(
            True,
            "authorized",
            message_id=decision.message_id,
            thread_id=decision.thread_id,
            created_at=decision.created_at,
            text_sha256=decision.text_sha256,
        ),
        pushed=True,
    )


def _read_anchor_thread(db_path: str | Path, anchor_message_id: str) -> str:
    """Devuelve el thread_id del ancla para el enlace; InfraError si no vale."""
    connection = open_store_ro(db_path)
    try:
        check_schema(connection)
        anchor, rejection = _load_anchor(connection, anchor_message_id)
    finally:
        connection.close()
    if rejection is not None or anchor is None:
        raise InfraError("anchor-unreadable", rejection.reason if rejection else "")
    return anchor.thread_id


def _run_print_phrase(args) -> int:
    """Imprime la frase ya rellenada y el enlace ?prompt= (no consume).

    Before: args con project_root, db, anchor, environment_id, remote y branch.
    During: genera el contexto desde git (tested=None -> HEAD), lee el hilo del
        ancla SOLO para el enlace y compone el bloque de codigo.
    After: EXIT_ALLOWED si imprime; EXIT_REJECTED si no puede generar la frase.
        No escribe ledger ni ejecuta push.
    """
    if not args.environment_id:
        raise UsageError("--environment-id es obligatorio con --print-phrase")
    context, reason = collect_push_context(
        args.project_root,
        tested_commit_sha=None,
        remote=args.remote,
        branch=args.branch,
    )
    if context is None:
        print(f"NO DISPONIBLE ({reason}): no se puede generar la frase.")
        return EXIT_REJECTED
    thread_id = _read_anchor_thread(args.db, args.anchor_message_id)
    link = build_prompt_link(
        environment_id=args.environment_id,
        thread_id=thread_id,
        phrase=context.expected.phrase,
    )
    print("Frase canonica (bloque de codigo, ya rellenada):")
    print("```")
    print(context.expected.phrase)
    print("```")
    print(f"Enlace: {link}")
    return EXIT_ALLOWED


def _display_phrase(
    project_root: str | Path,
    tested_commit_sha: str | None,
    remote: str,
    branch: str,
) -> str | None:
    """Frase canonica best-effort para el self-service de un rechazo de collect.

    Before: project_root, tested_commit_sha (puede ser None), remote y branch.
    During: lee HEAD, exige tested==HEAD (si tested se dio), cuenta el rango y
        deriva el repo de la URL de FETCH (la identidad que el usuario confirma),
        no de la pushurl. No exige ancestro ni URL de push: solo compone texto.
    After: la frase o None si no se puede componer; nunca eleva.
    """
    root = Path(project_root).resolve()
    run = _default_git_runner(root)
    try:
        rc, out, _err = run(["rev-parse", "HEAD"])
        if rc != 0:
            return None
        full_sha = out.strip().lower()
        if not _SHA_FULL_RE.match(full_sha):
            return None
        if tested_commit_sha and tested_commit_sha.strip().lower() != full_sha:
            return None
        rc, out, _err = run(["rev-list", "--count", f"{remote}/{branch}..HEAD"])
        if rc != 0:
            return None
        count = int(out.strip())
        if count < 1:
            return None
        rc, out, _err = run(["remote", "get-url", remote])
        if rc != 0:
            return None
        repo = _repo_from_url(out)
        if not repo:
            return None
        expected = ExpectedAuthorization.from_git_parts(
            repo=repo,
            remote=remote,
            branch=branch,
            sha12=full_sha[:12],
            commit_count=count,
        )
        return expected.phrase
    except (InfraError, ValueError, OSError):
        return None


def _run_verify(args, ledger) -> int:
    """Verifica la autorizacion y ejecuta (o simula) el push.

    Before: args con project_root, db, anchor, tested_commit_sha, remote,
        branch y dry_run; ledger ya construido.
    During: exige tested_commit_sha, genera el contexto desde git, ejecuta el
        wrapper y, si no autoriza, imprime el self-service.
    After: rc del resultado (0, 10, 20); los usos invalidos elevan UsageError y
        la infraestructura InfraError (los traduce `main`).
    """
    if not args.tested_commit_sha:
        raise UsageError("--tested-commit-sha es obligatorio para verificar y push")
    context, reason = collect_push_context(
        args.project_root,
        tested_commit_sha=args.tested_commit_sha,
        remote=args.remote,
        branch=args.branch,
    )
    if context is None:
        detail = _CONTEXT_REASON_TEXT.get(reason or "", reason or "")
        print(f"NO AUTORIZADO ({reason}): {detail}. No se ejecuto ningun push.")
        phrase = _display_phrase(
            args.project_root, args.tested_commit_sha, args.remote, args.branch
        )
        if phrase:
            print("Frase canonica (bloque de codigo, ya rellenada):")
            print("```")
            print(phrase)
            print("```")
        print(
            "Como repetir: corrige la causa y vuelve a ejecutar el comando; "
            "--print-phrase regenera la frase."
        )
        return EXIT_REJECTED
    result = execute_authorized_push(
        context,
        anchor_message_id=args.anchor_message_id,
        db_path=args.db,
        ledger=ledger,
        dry_run=args.dry_run,
    )
    if result.decision.allowed:
        suffix = "push verificado con ls-remote" if result.pushed else "dry-run"
        print(f"AUTORIZADO ({suffix}).")
        return result.exit_code
    print(format_decision(result.decision, context.expected))
    if result.detail:
        print(f"detalle: {result.detail}")
    return result.exit_code


def main(argv: Sequence[str] | None = None) -> int:
    """CLI del wrapper: muestra la frase o verifica y ejecuta el push."""
    import argparse

    class _Parser(argparse.ArgumentParser):
        def error(self, message):
            raise UsageError(message)

    parser = _Parser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--anchor-message-id", required=True)
    parser.add_argument("--tested-commit-sha", default=None)
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--branch", default="main")
    parser.add_argument("--environment-id", default=None)
    parser.add_argument("--ledger", type=Path, default=None)
    parser.add_argument("--print-phrase", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    try:
        args = parser.parse_args(argv)
    except UsageError as exc:
        print(f"USO: {exc}", file=sys.stderr)
        return EXIT_USAGE

    ledger = (
        PushAuthorityLedger(args.ledger)
        if args.ledger is not None
        else PushAuthorityLedger.default(args.project_root)
    )
    try:
        if args.print_phrase:
            return _run_print_phrase(args)
        return _run_verify(args, ledger)
    except UsageError as exc:
        print(f"USO: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except InfraError as exc:
        print(f"INFRAESTRUCTURA ({exc.cause}): {exc.detail}", file=sys.stderr)
        return EXIT_INFRA


if __name__ == "__main__":
    raise SystemExit(main())
