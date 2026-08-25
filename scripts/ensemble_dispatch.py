#!/usr/bin/env python3
# ruff: noqa: S603
"""Ensemble dispatcher: bucles proposer/challenger multi-backend (WOT-2026-019o).

Before: el agents.json del MOTOR (schema 1.3+) declara `ensemble_profiles`,
    `ensemble_pipelines` y `ensemble_private_roots`, validados en capa UNICA
    por `.agent/agents_config.py::_validate_config`. El scorecard y la
    proyeccion viven en el destino-rol (`--project-root`), NUNCA en el motor.
During: expone subcomandos CLI:
    - `smoke`: round-trip por CONTENIDO (token en la respuesta), nunca por
      exit code (`opencode run` devuelve exit 0 con Auth Error, medido).
    - `run`: ejecuta un pipeline; ROUND 0 = premise_check es INVARIANTE del
      dispatcher (no configurable: las premisas falsas son el modo de fallo
      dominante medido). `task_type` se valida contra `TASK_TYPES` (enum
      cerrado) en la ENTRADA de `run_pipeline`, antes de ROUND 0; invalido
      -> ValueError (WOT-2026-025y, D2). Cada fila de ronda mide
      `latency_ms` con `time.perf_counter()` (monotonico, nunca estimado) y
      porta `session_id` opcional (`--session-id`). Escribe una fila de
      scorecard por CADA intervencion, incluida `no-aportacion` (sin ceros
      hay sesgo de supervivencia).
    - `adjudicate`: el TERCER rol (sesion orquestadora) adjudica el outcome
      con evidencia OBLIGATORIA; registra `adjudicator_backend`
      (OBLIGATORIO) y `adjudicator_model` (opcional) para no perder QUIEN
      adjudico, en campos NUEVOS que no tocan `backend`/`task_type`
      (siguen copiados del SOURCE: mover la identidad ahi corrompe la
      proyeccion, WOT-2026-025y). `session_id` en la fila adjudicada viene
      del flag `--session-id` de la adjudicacion, nunca del source. El veto
      humano usa `--supersede` (evento nuevo, nunca mutacion de filas:
      append-only se preserva por evento).
    - `leaders`: regenera `backend_leaders.json` DERIVADO del scorecard
      (hash de la fuente; lider solo con n>=5; politica de exploracion
      documentada en el propio artefacto).
    Todo envio a backend pasa por `send_to_profile`, cuyo PRIMER paso es
    `privacy_preflight` (fail-closed): backend sin `trusted:true` +
    (`data_sensitivity != public` O rutas bajo `ensemble_private_roots`)
    -> DispatchBlockedError ANTES de tocar red. Auth por-invocacion via la
    env var nombrada en `api_key_env` (`setx` no propaga a procesos vivos,
    medido). GENERACION B2: el dispatcher NUNCA aplica escrituras de un
    backend al arbol; solo captura propuestas (stdout + scorecard).
After: scorecard.jsonl (UTF-8 SIN BOM, append-only) y backend_leaders.json
    actualizados bajo `<destino>/.agent/runtime/ensemble/`; exit 0 en exito,
    1 en bloqueo/validacion, 2 en error de invocacion.

Resolucion de config MOTOR-EXPLICITA (M9 del contrato): la config se resuelve
desde la ubicacion de ESTE script, con independencia de AGENT_PROJECT_ROOT
(cuya prioridad 1 apuntaria al workspace, que no tiene claves ensemble_*).
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import json
import math
import os
import re
import secrets
import subprocess
import sys
import time
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


# WOT-2026-041b: lock de fichero por plataforma. Solo uno de los dos existe en
# cada SO; el que falte queda en None y `_locked_for_append` degrada a no-op.
try:  # Windows
    import msvcrt
except ImportError:  # pragma: no cover -- POSIX
    msvcrt = None  # type: ignore[assignment]
try:  # POSIX
    import fcntl
except ImportError:  # pragma: no cover -- Windows
    fcntl = None  # type: ignore[assignment]


MOTOR_ROOT = Path(__file__).resolve().parent.parent
_AGENT_DIR = MOTOR_ROOT / ".agent"
# WOT-2026-048d: MOTOR_ROOT va DELANTE de `.agent`, y esto no contradice el
# comentario de abajo: lo COMPLETA. `agents_config` (que vive en `.agent/`)
# importa `runtime.project_root`, y `runtime` debe resolver a
# `<motor>/runtime/`, NO a `.agent/runtime/` (que tiene `__init__.py` y gana si
# esta antes). Medido: con MOTOR_ROOT por APPEND, el import revienta con
# `No module named 'runtime.project_root'`. Poner el motor primero fija la
# resolucion correcta y de paso hace importable `bus/`.
if str(MOTOR_ROOT) not in sys.path:
    sys.path.insert(0, str(MOTOR_ROOT))
# APPEND, nunca insert(0): con .agent al frente, `runtime` resolveria a
# `.agent/runtime/` en vez de `<motor>/runtime/` (hazard documentado en
# AGENTS.md para la coleccion de pytest).
if str(_AGENT_DIR) not in sys.path:
    sys.path.append(str(_AGENT_DIR))

from agents_config import load_agents_config  # noqa: E402
from bus.subprocess_env import build_backend_env  # noqa: E402


SCORECARD_REL = Path(".agent/runtime/ensemble/scorecard.jsonl")
LEADERS_REL = Path(".agent/runtime/ensemble/backend_leaders.json")
# WOT-2026-040b: registro append-only de los challenge_nonce EMITIDOS antes de
# cada fan-out de gobierno. Fuente externa contra la que check_loop_execution
# valida cada receipt. Vive en el runtime del destino-rol (nunca en repo_motor).
EMITTED_NONCES_REL = Path(".agent/runtime/ensemble/emitted_nonces.jsonl")
# Campos de una fila de emision. issuer_role/issuer_backend_key documentan QUIEN
# emitio (el gate exige que ese backend_key NO cuente como lente ejecutora para N);
# issued_before_ts fija el orden emision-antes-que-receipt que prueba la ceremonia
# previa (adjudicado por Codex 2026-07-24: independencia OPERACIONAL, no criptografica).
EMITTED_NONCE_FIELDS = [
    "ts",
    "issuer_role",
    "issuer_backend_key",
    "issued_before_ts",
    "commit_sha",
    "loop_id",
    "challenge_nonce",
]

SCORECARD_FIELDS = [
    "ts",
    "event",
    "ticket",
    "rol",
    "task_type",
    "backend",
    "model",
    "backend_version",
    "ronda",
    "outcome",
    "evidencia",
    "finding_confirmed_by",
    "adjudication_evidence",
    "input_bytes",
    "context_kind",
    "failure_mode",
    # WOT-2026-025y: los 4 campos siguientes van SIEMPRE al final. El
    # prefijo de 16 campos de arriba es INVARIANTE (frozen, ver
    # test_scorecard_fields_prefix_is_frozen): insertar algo en medio
    # reordena la comprehension de append_scorecard y rompe consumidores
    # posicionales.
    "session_id",
    "latency_ms",
    "adjudicator_backend",
    "adjudicator_model",
    # WOT-2026-037b: campos del registro citable de bucles, tambien SIEMPRE
    # al final por el mismo motivo (prefijo frozen invariante).
    "phase",
    "loop_id",
    "backend_key",
    # WOT-2026-040b: commit_sha ata el receipt al commit generado FUERA del
    # ejecutor; challenge_nonce es el nonce emitido FUERA (emitted_nonces.jsonl)
    # y copiado a cada receipt de ronda. check_loop_execution exige el join dual
    # (commit + nonce match, emision anterior) para probar que la ronda respondio
    # a ESE challenge de ESE commit. Al final (prefijo frozen invariante).
    "commit_sha",
    "challenge_nonce",
    # WOT-2026-043q: tamano REAL de la respuesta del backend, en caracteres del
    # texto crudo ANTES de truncar. `evidencia` NO sirve para medirlo: se guarda
    # como `text[:500]`, asi que 249 de 472 rondas historicas caen exactamente en
    # el tope, y una respuesta almacenada fuera de linea ("raw/....json (2134c)")
    # ocupa 46 caracteres pese a ser sustantiva. Sin este campo, una lente que NO
    # RESPONDE y una que RESPONDE VACIO son indistinguibles para la barrera del
    # bucle. Al final (prefijo frozen invariante).
    "output_chars",
    # WOT-2026-048g: el modelo que el backend dice haber USADO, extraido de su
    # STDERR. `model` es el DECLARADO por el perfil; este es el REPORTADO por el
    # proceso. WOT-2026-047y hizo que coincidieran por construccion (el flag
    # entra en el argv), pero un CLI que ACEPTE el flag y sirva otro modelo
    # seguia siendo invisible: el scorecard solo tenia la version declarada.
    # No hace falta parsear cada CLI ni disenar nada: AMBOS lo declaran ya y el
    # transporte tiraba el stderr (medido 2026-08-03: opencode escribe
    # "> builder - glm-5.2"; codex escribe "model: gpt-5.5"). None = el backend
    # no lo declaro (canal api, o CLI sin banner): AUSENCIA de dato, nunca
    # desacuerdo. Al final (prefijo frozen invariante).
    "model_reported",
    # WOT-2026-042v: AMBITO EFECTIVO desde el que observo la lente
    # (`destino` | `motor` | `sin-fs` | `declarado` | `motor:<causa>`). Sin este
    # campo el scorecard MEZCLA dos poblaciones con tasas de acierto distintas
    # -- una lente que ve el arbol y otra que opina sobre el -- y
    # `backend_leaders.json` elegiria lider comparando lo incomparable. Se
    # ANADE AL FINAL, que es el mecanismo de extension que el propio contrato
    # WOT-2026-025y documenta (el prefijo frozen son los 16 primeros campos;
    # 037b, 040b, 043q y 048g ya crecieron por aqui), asi que no lo rompe.
    "lens_scope",
]

ADJUDICATED_OUTCOMES = {
    "adoptada",
    "rechazada-redundante",
    "falso-positivo",
    "error-factual",
    "no-aportacion",
}

TASK_TYPES = {
    "code-gen",
    "code-review",
    "prose",
    "translation",
    "triage",
    "contract-audit",
    "adjudication",
    "prompt-audit",
}

LEADER_MIN_N = 5
EXPLORATION_POLICY = (
    "1-de-5 rondas, o al cambiar la version del modelo/backend, el challenger "
    "se elige entre NO-lideres y se registra igual (sin exploracion el ranking "
    "se auto-confirma)"
)

PREMISE_CHECK_PREAMBLE = (
    "ROUND 0 - PREMISE CHECK (invariante del dispatcher): ANTES de refinar o "
    "proponer nada, verifica las premisas factuales del material siguiente. "
    "Lista cada premisa falsa, stale o no verificable con su evidencia. Si "
    "todas sostienen, responde PREMISES-OK y nada mas."
)


class DispatchBlockedError(RuntimeError):
    """El privacy_preflight bloqueo el envio (fail-closed)."""


def load_motor_config() -> dict:
    """Config del MOTOR, motor-explicita (M9): ignora AGENT_PROJECT_ROOT."""
    return load_agents_config(project_root=MOTOR_ROOT)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_project_root(raw: str) -> Path:
    """El destino-rol de los artefactos runtime. NUNCA el propio motor."""
    root = Path(raw).resolve()
    if root == MOTOR_ROOT:
        raise ValueError(
            "El dispatcher NUNCA escribe runtime en repo_motor: --project-root "
            "debe apuntar al destino-rol (workspace / repo_destino)"
        )
    return root


# WOT-2026-027n: gate de CONTENIDO, acotado a ASIGNACION CON VALOR DE ALTA
# ENTROPIA y a prefijos de credencial inequivocos. NUNCA substring suelto.
#
# POR QUE ACOTADO (medido 2026-07-22, no teorico): un gate por substring
# ('token', 'secret', 'api_key', 'sk-') bloquea bundles REALES del repo que
# citan esos terminos en PROSA TECNICA -- incluido el bundle de gobernanza de
# este mismo ticket, con lo que el vuelo se auto-bloquearia en su propio
# MANAGER_REVIEW. Un gate que bloquea el trabajo legitimo ensena al operador a
# saltarselo, y un gate que se saltan es peor que no tenerlo (anti-patron
# "aplicate tu propia vara", AGENTS.md). Los fixtures versionados de
# tests/fixtures/ensemble_bundles/ fijan ese limite: DEBEN pasar.
#
# RIESGO RESIDUAL DECLARADO (no lo cierra este ticket): de los 7 vectores
# medidos, esto cierra .env clasico, clave privada PEM y tokens con prefijo
# reconocible. SIGUEN SALIENDO: valor sin patron, base64 opaco, PII y rutas de
# maquina. Hoy el riesgo es BAJO porque el AGENTE elige que va en el bundle; se
# dispara cuando lo elija el MODELO (WOT-2026-027m, que declara 027n como
# precondicion dura).
# WOT-2026-027s: renombrado desde `_HIGH_ENTROPY_ASSIGNMENT`. El nombre viejo
# MENTIA: pese a decir "entropia" no mide entropia alguna -- exige un nombre de
# clave RECONOCIBLE (password|api_key|token|secret) y solo entonces un valor de
# >=8 chars. Es un gate por NOMBRE-DE-CLAVE, no por aleatoriedad del valor.
# Conservarlo hacia irrealizable el DoD (e) de aislamiento por capa: la capa 3,
# que si mide entropia de Shannon, colisionaba nominalmente con esta y "quitar
# la capa de entropia" no tenia un referente unico. Simbolo privado: el
# renombrado no toca ninguna firma publica.
_CREDENTIAL_ASSIGNMENT = re.compile(
    r"(password|api_key|token|secret)\s*=\s*[\"'][^\"']{8,}[\"']",
    re.IGNORECASE,
)
_CREDENTIAL_LITERALS = (
    re.compile(r"sk-[A-Za-z0-9]{16,}"),
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)


# WOT-2026-027s CAPA 3: entropia REAL (Shannon), ortogonal a
# `_CREDENTIAL_ASSIGNMENT` (que casa NOMBRES de clave conocidos y no mide nada
# aleatorio). Cierra el vector "valor sin patron" que 027n dejo abierto y
# declaro como riesgo residual.
#
# DEUDA DECLARADA -- DUENO: WOT-2026-041n. El umbral NO esta calibrado contra un
# corpus: los bundles reales vivian en `.agent/runtime/tmp/` (gitignored) y se
# purgaron, hecho ya declarado en el propio plan de vuelo. Elegir un numero "a
# ojo" seria exactamente la "meseta sin medir" que AGENTS.md prohibe. Por eso
# esta capa nace en DETECCION BASICA y deliberadamente CONSERVADORA:
#   - solo mira tokens LARGOS (>=32 chars) y sin espacios, la forma de un
#     secreto opaco en BASE64, no de la prosa. El HEX puro NO lo cubre esta
#     rama (solo tiene 2 clases de caracter y cae en el guardia de abajo): lo
#     cubre la capa 3b `_HEX_SECRET`, anadida en WOT-2026-041q. Hasta ese
#     ticket este comentario decia "base64/hex" y era FALSO;
#   - exige entropia >= 4.0 bits/caracter, que la prosa natural (~2.5-3.5) y los
#     identificadores de codigo no alcanzan, pero base64 aleatorio (~5.5-6.0) si;
#   - exige mezcla de clases de caracter, para no morder un hash hex de commit
#     ni una cadena repetitiva.
# FALSO-POSITIVO RESIDUAL MEDIDO (2026-07-27, contra el REPO REAL -- 481
# ficheros .md/.py, no contra los fixtures de este ticket, que medirian solo a
# si mismos): 6/481 (1.2%) muerden, y los 6 son ficheros de TEST que llevan
# credenciales sinteticas o identificadores CamelCase largos. Prosa, prompts y
# documentacion: 0 mordidos. Ese perfil es ACEPTABLE porque el payload real de
# un envio son bundles de prosa, no la suite. Iteracion previa MEDIDA y
# DESCARTADA: incluir `/ _ -` en el alfabeto daba 6/120 mordidos, todos rutas y
# URLs (`docs/BUS_ARCHITECTURE_WT-2026-210`); una segunda iteracion que exigia
# densidad de digitos bajaba el residual pero DEJABA DE CAZAR base64 real, asi
# que se revirtio: un filtro que no detecta es peor que un falso positivo.
# CRITERIO DE SALIDA de la deuda (WOT-2026-041n): reunir un corpus versionado de
# bundles reales, barrer el umbral contra la SUITE REAL (no contra fixtures
# escritos para el barrido) y publicar AMBOS bordes de la meseta; si la cota
# superior queda abierta, decirlo. Hasta entonces el numero es un DEFAULT
# CONSERVADOR declarado, no un umbral medido.
_ENTROPY_MIN_TOKEN_LEN = 32
_ENTROPY_BITS_THRESHOLD = 4.0
# WOT-2026-041r: alfabeto ampliado a base64URL con `_` y `-`. Sin ellos, un
# token OAuth/JWT estandar SALIA LIMPIO -- vector (B), preexistente desde 027s y
# hallado por dos lentes independientes del bucle L700.
#
# `/` SE QUEDA FUERA A PROPOSITO (medido 2026-07-27, no teorico): incluirlo hace
# que una RUTA entera case como un solo token y reintroduce el falso positivo que
# 027s ya habia medido y descartado -- `docs/BUS_ARCHITECTURE_WT-2026-210`,
# `repos/FDL32/orquestador-de-agentes/rules/branches/main`. Con `/` dentro: 26
# ficheros mordidos y 4 de prosa; sin el: los numeros de abajo. El guardia de
# ETIQUETA no cubre esto, porque solo se aplica a la rama hex, no a esta.
# Consecuencia aceptada: un base64 estandar que use `/` en la posicion justa
# puede partirse en dos tramos; como cada tramo de >=32 chars sigue casando, el
# secreto se caza igual salvo que AMBOS lados queden por debajo del minimo.
#
# COSTE MEDIDO DE ADMITIR `_` y `-` (snapshot 2026-07-27, repo real de 481
# ficheros): 11 mordidos en total -- el MISMO numero que 041q -- y 2 de PROSA,
# frente a 1 en 041q. El fichero que entra es un NOMBRE DE FICHERO con guiones
# bajos (`execution_log_WP-2026-037-to-041`, `DEC-008G-001-vocabulary-...`), que
# es el precio directo e inevitable de aceptar el alfabeto url-safe. A cambio se
# cierra la salida de tokens OAuth/JWT, que ANTES salian limpios. Se acepta: un
# nombre de fichero bloqueado es visible y recuperable; un token de sesion que
# sale, no. CREDITS.md, que era el falso positivo de 041q, YA NO MUERDE gracias
# al guardia de etiqueta.
_OPAQUE_TOKEN = re.compile(rf"[A-Za-z0-9+=_-]{{{_ENTROPY_MIN_TOKEN_LEN},}}")
# WOT-2026-041q CAPA 3b: el hex puro NO PASA por _OPAQUE_TOKEN + clases.
#
# EL DEFECTO QUE CIERRA (medido 2026-07-27 por un bucle adversarial externo, no
# por la suite de 027s: 4 lentes convergieron en el mismo hueco): un secreto en
# hex -- el formato MAS COMUN de clave API y de hash -- tiene solo DOS clases de
# caracter (letras + digitos), asi que el guardia `classes < 3` lo descartaba
# ANTES de mirar su entropia. Par medido: 'd41d8cd98f00b204e9800998ecf8427e5f1a2b3c'
# ESCAPABA; con esta rama, se caza. El comentario de arriba ya prometia
# "base64/hex" y el codigo solo cubria base64: la promesa era FALSA, que es la
# familia "barrera del alcance" de AGENTS.md.
#
# POR QUE UNA RAMA PROPIA Y NO relajar `classes` a >=2: relajar el guardia
# generico reabre falsos positivos en identificadores CamelCase largos (ya
# medidos en 027s). El hex tiene alfabeto CERRADO, asi que se reconoce por FORMA
# sin tocar el resto de la capa 3.
#
# POR QUE SIN EXCEPCION POR LONGITUD (iteracion MEDIDA Y DESCARTADA, no la
# repitas): excluir las longitudes canonicas de hash (32/40/64) deja el repo real
# en 0 falsos positivos... pero hace ESCAPAR MD5, SHA-1 y SHA-256, que es
# justamente donde caen las claves API hex reales. Compraba silencio a costa de
# la cobertura que esta capa viene a dar.
#
# COSTE DE 041q, SUPERADO POR WOT-2026-041r (se conserva el registro porque el
# razonamiento fue REFUTADO por medicion, y borrarlo perderia la leccion):
# 041q mordia 5 ficheros, 1 de ellos PROSA (CREDITS.md, que cita SHAs de repos
# externos), y justificaba ese falso positivo con una "asimetria de dano":
# bloquear un bundle que cita un SHA seria RECUPERABLE, dejar salir una clave no.
# LA PARTE "RECUPERABLE" RESULTO FALSA: la capa bloqueo el bundle de gobernanza
# de su propio ticket y el operador se recupero OMITIENDO el literal, es decir,
# aprendiendo a evadir el gate en su primer contacto con trabajo legitimo.
# Hoy el hex NO muerde desnudo -- exige etiqueta de credencial (ver abajo) -- y
# CREDITS.md ya no es falso positivo. Sigue siendo cierto lo unico que aquel
# analisis acerto: un SHA-1 y una clave hex de 40 chars son INDISTINGUIBLES por
# forma, y por eso hace falta contexto.
_HEX_SECRET = re.compile(r"(?<![0-9a-zA-Z])[0-9a-fA-F]{32,}(?![0-9a-zA-Z])")
_HEX_BITS_THRESHOLD = 3.0
# WOT-2026-041r: ventana de contexto a la IZQUIERDA del token.
#
# POR QUE EXISTE (medido EN PRODUCCION, no teorico): la capa 3b de 041q decidia
# por FORMA pura y bloqueo el bundle de GOBERNANZA de su propio ticket, por citar
# el hash de ejemplo que documentaba el fix. La reaccion del operador fue OMITIR
# el literal para poder enviarlo -- o sea, la barrera enseno su propia evasion al
# primer contacto con trabajo legitimo. AGENTS.md lo predice: "un gate que se
# saltan es peor que no tenerlo". Una barrera que entrena la evasion se esta
# desactivando sola.
#
# LA SENAL (medida sobre el repo real, 481 ficheros): de los 15 hex que la capa
# 3b mordia, CERO llevaban etiqueta de credencial -- todos eran citas (URLs de
# commit, prosa tecnica, fixtures de test). O sea: exigir etiqueta elimina el
# 100% del falso positivo SIN perder ningun secreto realmente presente.
#
# ASIMETRIA DELIBERADA entre ramas, y por que NO es incoherente:
#   - HEX: exige etiqueta. Un SHA-1 y una clave hex son IDENTICOS en forma
#     (medido en 041q), asi que la forma no puede decidir y el contexto es la
#     unica senal disponible.
#   - BASE64 opaco (>=4.0 bits): NO exige etiqueta. No hay un "SHA base64" que la
#     gente cite en prosa; ese umbral ya da 0 mordidos sobre prosa real, luego
#     pedirle contexto solo debilitaria la deteccion sin ganar nada.
_CREDENTIAL_LABEL = re.compile(
    r"(api[_-]?key|secret|token|password|passwd|pwd|auth|bearer|credential"
    r"|access[_-]?key)\w*\s*[:=]?\s*[\"']?\s*$",
    re.IGNORECASE,
)
_LABEL_WINDOW = 48


def _shannon_bits(value: str) -> float:
    """Entropia de Shannon en bits/caracter de `value`.

    Before: `value` es un token no vacio ya extraido del payload.
    During: cuenta frecuencias por caracter y aplica -sum(p*log2(p)). Sin I/O.
    After: retorna los bits por caracter (0.0 para cadena vacia o de un solo
        simbolo repetido). No lanza.
    """
    if not value:
        return 0.0
    total = len(value)
    counts = Counter(value)
    return -sum((n / total) * math.log2(n / total) for n in counts.values())


def _entropy_leak(payload_text: str) -> str | None:
    """Token opaco de alta entropia en el payload, o None si no lo hay.

    CAPA 3 (WOT-2026-027s), ortogonal a `_content_leak`: aquella mira NOMBRES de
    clave conocidos, esta mira la FORMA del valor. Un secreto sin patron
    reconocible (base64 opaco) solo lo ve esta.

    Before: `payload_text` es el material serializado que saldria al backend.
    During: extrae tokens de >=32 chars del alfabeto base64/hex y evalua, para
        cada uno, entropia de Shannon y diversidad de clases de caracter. Sin
        I/O ni red.
    After: retorna una etiqueta describiendo el hallazgo (sin FILTRAR el valor:
        el reason viaja a logs, incluirlo seria fugar el secreto que se intenta
        proteger) o None. No lanza.
    """
    for hex_hit in _HEX_SECRET.finditer(payload_text):
        token = hex_hit.group()
        # La FORMA hex no basta: 'a'*64 es hex valido y tiene entropia 0.00.
        # El umbral es MAS BAJO que el de base64 porque el alfabeto hex solo
        # tiene 16 simbolos: su maximo teorico es 4.0 bits/char (log2(16)), de
        # modo que exigirle 4.0 lo haria inalcanzable. 3.0 deja fuera la cadena
        # repetida y el patron trivial, y admite MD5/SHA/claves reales (medido:
        # 3.56-3.73 bits). Hereda la MISMA deuda de calibracion que el umbral de
        # base64: dueno WOT-2026-041n.
        if _shannon_bits(token) < _HEX_BITS_THRESHOLD:
            continue
        izquierda = payload_text[
            max(0, hex_hit.start() - _LABEL_WINDOW) : hex_hit.start()
        ]
        if not _CREDENTIAL_LABEL.search(izquierda):
            continue
        return (
            f"token hexadecimal opaco de {len(token)} chars "
            "(forma de clave API o hash; WOT-2026-041q)"
        )
    for token in _OPAQUE_TOKEN.findall(payload_text):
        classes = sum(
            (
                any(c.islower() for c in token),
                any(c.isupper() for c in token),
                any(c.isdigit() for c in token),
            )
        )
        if classes < 3:
            continue
        bits = _shannon_bits(token)
        if bits >= _ENTROPY_BITS_THRESHOLD:
            return (
                f"token opaco de {len(token)} chars con entropia "
                f"{bits:.2f} bits/char (umbral {_ENTROPY_BITS_THRESHOLD})"
            )
    return None


# WOT-2026-027s CAPA 1: allowlist de LECTURA. Que ficheros pueden ENTRAR al
# payload, decidido ANTES de leer el fichero -- no que contiene, que es lo que
# miran las capas 2 y 3. Es la unica capa que puede cerrar el vector "el MODELO
# elige el fichero" (WOT-2026-027m): las otras dos solo ven el texto una vez ya
# se leyo, y un fichero fuera de la allowlist no debe llegar siquiera a leerse.
#
# ESTADO MEDIDO 2026-07-27: `ensemble_private_roots` esta VACIA en el motor y
# AUSENTE en el destino. La capa por-RUTA que figura como existente NO PROTEGE
# NADA hoy; esta capa 1 no hereda esa cobertura inexistente.
#
# Config: clave ADITIVA `ensemble_payload_allowlist` en el agents.json del
# MOTOR, leida via `load_motor_config` (motor-explicita, ignora
# AGENT_PROJECT_ROOT por el contrato M9). Lista VACIA o AUSENTE = allowlist
# DESACTIVADA (retrocompatible: el pipeline de hoy sigue funcionando). Con
# entradas, se vuelve fail-closed.
def payload_read_allowed(
    payload_path: Path,
    allowlist: list[str],
    motor_root: Path | None = None,
) -> tuple[bool, str]:
    """Decide si `payload_path` puede leerse como payload de un envio.

    Before: `payload_path` es la ruta cruda pedida por el CLI (puede no
        existir); `allowlist` son prefijos de ruta RELATIVOS al motor,
        tal cual vienen de `ensemble_payload_allowlist`.
    During: resuelve la ruta (siguiendo symlinks, para que un enlace no
        sortee la barrera) y comprueba contencion bajo alguna raiz de la
        allowlist. Sin leer el CONTENIDO del fichero: la decision es por
        RUTA y ocurre ANTES de cualquier lectura.
    After: retorna (allowed, reason). Allowlist vacia/ausente -> (True,
        motivo nombrado) para preservar el comportamiento actual; con
        entradas, todo lo que no este contenido -> (False, motivo). No
        lanza: el caller decide (el CLI lo convierte en DispatchBlockedError).
    """
    if not allowlist:
        return True, "allowlist de payload no configurada (capa 1 inactiva)"
    root = (motor_root or MOTOR_ROOT).resolve()
    try:
        resolved = payload_path.resolve()
    except (OSError, ValueError):
        return False, f"ruta de payload irresoluble: {payload_path}"
    for entry in allowlist:
        if not entry:
            continue
        candidate = Path(entry)
        base = candidate if candidate.is_absolute() else root / candidate
        try:
            base = base.resolve()
        except (OSError, ValueError):
            continue
        if resolved == base or base in resolved.parents:
            return True, f"payload bajo raiz permitida: {entry}"
    return False, (
        f"payload fuera de ensemble_payload_allowlist: {resolved} no esta bajo "
        f"ninguna de {allowlist}"
    )


def _content_leak(payload_text: str) -> str | None:
    """Nombre del patron de credencial detectado, o None si el payload esta limpio.

    Before: `payload_text` es el material serializado que saldria hacia el
        backend. No se asume ningun encoding ni tamano.
    During: casa (1) asignacion `clave = "<valor de >=8 chars>"` y (2) los
        prefijos de credencial inequivocos. Ambos exigen un VALOR, de modo que
        la mencion en prosa del nombre de la clave no dispara.
    After: retorna la etiqueta del patron (para el `reason` del caller) o None.
        No lanza: el caller decide el veredicto.
    """
    if _CREDENTIAL_ASSIGNMENT.search(payload_text):
        return "asignacion a nombre de clave de credencial"
    for pattern in _CREDENTIAL_LITERALS:
        if pattern.search(payload_text):
            return f"literal de credencial ({pattern.pattern})"
    entropy = _entropy_leak(payload_text)
    if entropy is not None:
        return entropy
    return None


def privacy_preflight(
    payload_text: str,
    sensitivity: str | None,
    backend_cfg: dict,
    private_roots: list[str],
) -> tuple[bool, str]:
    """Barrera portable (CI/headless) contra fuga de contenido privado.

    Before: `payload_text` es el material serializado que saldria hacia el
        backend; `sensitivity` viene del caller (CLI) o del perfil; AUSENTE
        se trata como `private` (fail-closed); `backend_cfg` es la entrada de
        `backends` (con `trusted` opcional, ausente = false).
    During: un backend `trusted: true` pasa siempre. Para el resto: bloquea
        si la sensibilidad no es `public`; en la rama `public` bloquea ademas
        si el payload nombra una raiz de `ensemble_private_roots` (filtro por
        RUTA) o si contiene una credencial (filtro por CONTENIDO, WOT-2026-027n:
        `_content_leak`, acotado a asignacion con valor de alta entropia y a
        prefijos inequivocos -- la mencion en prosa NO dispara).
    After: retorna (allowed, reason). El caller DEBE abortar el envio si
        allowed es False; `send_to_profile` lo hace lanzando
        DispatchBlockedError ANTES de tocar red (mutation: sin este paso,
        el payload sale).
    """
    if backend_cfg.get("trusted") is True:
        return True, "backend trusted:true"
    effective = sensitivity or "private"
    if effective != "public":
        return False, (f"data_sensitivity={effective} hacia backend sin trusted:true")
    for root in private_roots or []:
        if root and root in payload_text:
            return False, f"payload contiene raiz privada declarada: {root}"
    leak = _content_leak(payload_text)
    if leak is not None:
        return False, f"payload contiene contenido sensible: {leak}"
    return True, "payload public sin raices privadas ni contenido sensible"


# WOT-2026-029f: api.nan.builders vive tras Cloudflare, que rechaza la firma
# por defecto de urllib (Python-urllib/3.x -> HTTP 403, body "error code: 1010")
# ANTES de evaluar la auth; con un UA explicito la MISMA clave devuelve 200
# (par medido 2026-07-18: "orquestador-ensemble/1.0" -> 200;
# "Python-urllib/3.12" -> 403/1010). Sin esta cabecera, todo el canal nan_api
# muere en el WAF y el 403 se confunde con clave invalida.
ENSEMBLE_USER_AGENT = "orquestador-ensemble/1.0"

# WOT-2026-041a: el motor es un repo PUBLICO y `_transport_api` construye un
# Request con "Authorization: Bearer <key>". Si urlopen levanta HTTPError, el
# objeto crudo llega a los callers, que hacen `f"{type(exc).__name__}: {exc}"`
# (:575) o lo imprimen a stderr (:1173). MEDIDO 2026-07-24 (probe propio, NO
# heredado): `str(HTTPError)` NO contiene la key, pero `err.headers` SI (True) y
# `repr(req.header_items())` SI (True). Por eso el saneado NO consiste en
# reformatear el mensaje: consiste en no dejar salir el objeto crudo NI por
# __cause__/__context__.
#
# LIMITE DECLARADO (no lo cierra este ticket, medido bajo mutation): la local
# `api_key` de `_transport_api` sigue conteniendo la clave -- es necesaria para
# construir el Request--, asi que un reporter de terceros que vuelque
# `locals()` de los frames la vera. Cerrarlo exige no tener la clave en una
# local, que es otra superficie. Tampoco cubre la key en el CUERPO que devuelva
# el backend ni en query params de la URL.
REDACTED_MARKER = "***REDACTED***"


class TransportError(RuntimeError):
    """Error de transporte SANEADO: nunca referencia al HTTPError/Request crudo.

    Before: se construye solo desde `_transport_api` al capturar un fallo de
    `urlopen`, con la api_key en mano para poder redactarla.
    During: copia status/code y el cuerpo diagnostico ya redactado; no guarda
    referencia al objeto original ni a sus headers.
    After: `str()`, `repr()`, `.args` y el traceback quedan libres de la clave.
    Se levanta FUERA del bloque `except` (ver `_transport_api`) para que ni
    __cause__ ni __context__ apunten al HTTPError crudo.
    """

    def __init__(self, message: str, *, status: int | None, body: str | None) -> None:
        super().__init__(message)
        self.status = status
        self.code = status  # alias: HTTPError expone ambos
        self.body = body


def _redact_secret(text: str, secret: str | None) -> str:
    """Sustituye la clave por REDACTED_MARKER. Sin clave, devuelve el texto tal cual."""
    if not secret:
        return text
    return text.replace(secret, REDACTED_MARKER)


def _sanitized_transport_error(exc: Exception, api_key: str | None) -> TransportError:
    """Convierte un fallo de urlopen en un TransportError sin secretos.

    Preserva status/code y el cuerpo diagnostico (redactado) para no romper el
    diagnostico de cuota/429 de WOT-2026-027g: silenciar el error tambien es un
    fallo, no solo filtrarlo.
    """
    status = getattr(exc, "code", None)
    body: str | None = None
    read = getattr(exc, "read", None)
    if callable(read):
        try:
            raw = read()
        except Exception:  # cuerpo ilegible: no es motivo para perder el status
            raw = None
        if raw:
            body = _redact_secret(
                raw.decode("utf-8", errors="replace")
                if isinstance(raw, bytes)
                else str(raw),
                api_key,
            )
    reason = _redact_secret(str(getattr(exc, "reason", "") or ""), api_key)
    detail = _redact_secret(str(exc), api_key)
    parts = [type(exc).__name__]
    if status is not None:
        parts.append(f"HTTP {status}")
    if detail:
        parts.append(detail)
    if reason and reason not in detail:
        parts.append(reason)
    if body:
        parts.append(f"body={body}")
    return TransportError(" | ".join(parts), status=status, body=body)


def _transport_api(
    profile: dict, backend_cfg: dict, messages: list[dict], timeout: int
) -> str:
    """POST chat-completions con auth por-invocacion (env var de api_key_env)."""
    key_env = profile["api_key_env"]
    api_key = os.environ.get(key_env)
    if not api_key:
        raise RuntimeError(
            f"auth por-invocacion: la variable {key_env} no esta en el entorno"
        )
    body = json.dumps(
        {
            "model": profile.get("model"),
            "messages": messages,
            "temperature": 0,
        }
    ).encode("utf-8")
    req = urllib.request.Request(  # noqa: S310 -- https exigido por el validador
        profile["api_base_url"],
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": ENSEMBLE_USER_AGENT,
        },
        method="POST",
    )
    # WOT-2026-041a: el saneado se CONSTRUYE dentro del except pero se LEVANTA
    # fuera. Motivo medido: `raise ... from None` limpia __cause__, pero el
    # interprete reasigna __context__ al ejecutar el `raise` DENTRO del except,
    # y ahi vuelve a quedar el HTTPError crudo con sus headers (la asercion (d)
    # de la mutation lo caza). Levantarlo fuera deja ambos encadenamientos en
    # None. `req` tampoco se referencia nunca: repr(req) filtra la key.
    #
    # El try envuelve SOLO el urlopen y la lectura de la respuesta, NO el
    # json.loads: una respuesta 200 con cuerpo malformado es un error de
    # PARSEO, no de transporte, y convertirlo en TransportError con
    # status=None borraria el tipo original (JSONDecodeError) que un caller
    # podria estar discriminando. Hallazgo de dos lentes del MANAGER_REVIEW,
    # confirmado midiendo: antes de acotarlo, un 200 con cuerpo no-JSON salia
    # como "TransportError | JSONDecodeError ... status=None".
    sanitized: TransportError | None = None
    raw_body: bytes | None = None
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            raw_body = resp.read()
    except Exception as exc:
        sanitized = _sanitized_transport_error(exc, api_key)
    if sanitized is not None:
        raise sanitized
    data = json.loads(raw_body.decode("utf-8"))
    return data["choices"][0]["message"]["content"]


def _kill_process_tree(pid: int) -> None:
    """Mata el ARBOL completo del proceso (Windows: taskkill /T /F).

    Motivo (medido 2026-07-16, smoke real): `codex exec` via shim .cmd spawnea
    node.exe que HEREDA los pipes; el timeout de subprocess.run mata solo al
    hijo directo y el communicate() posterior BLOQUEA para siempre esperando
    el EOF del pipe retenido por el descendiente superviviente. Sin kill de
    arbol, un backend colgado congela el smoke/piloto entero.
    """
    if os.name == "nt":
        taskkill = (
            Path(os.environ.get("SYSTEMROOT", r"C:\Windows"))
            / "System32"
            / "taskkill.exe"
        )
        subprocess.run(
            [str(taskkill), "/T", "/F", "/PID", str(pid)],
            capture_output=True,
            timeout=30,
            shell=False,
        )
    else:  # pragma: no cover -- rama no-Windows
        import contextlib
        import signal

        with contextlib.suppress(OSError):
            os.kill(pid, signal.SIGKILL)


# WOT-2026-048g: marca que `_transport_agent` antepone cuando el CLI sale con
# rc != 0. `_record_round` la reconoce y registra la fila como `no-aportacion`
# con `failure_mode`, en vez de contarla como intervencion valida.
_TRANSPORT_FAILED_PREFIX = "[transport-failed] "

# WOT-2026-048g: el modelo que el CLI dice estar usando, en su banner de STDERR.
# Medido 2026-08-03 sobre los dos backends CLI reales:
#   opencode -> "> builder - glm-5.2"   (separador U+00B7 en la salida real)
#   codex    -> "model: gpt-5.5"
# Deliberadamente ESTRECHO: solo estas dos formas. Un parser generoso inventaria
# desacuerdos donde solo hay un formato no previsto, y un falso "el backend
# corrio otro modelo" es peor que no tener el dato -- por eso lo no reconocido
# es None (ausencia), nunca un valor adivinado.
_REPORTED_MODEL_KEY = "_model_reported"

# WOT-2026-042v: AMBITO EFECTIVO de la lente, sellado sobre el `profile` (dict
# mutable que el caller ya tiene) por la MISMA razon que `_REPORTED_MODEL_KEY`:
# la firma `transport(profile, backend_cfg, messages, timeout)` es CONTRATO --
# los tests inyectan `_FakeTransport` con esa aridad exacta -- y anadir un valor
# de retorno la rompe. `_record_round` lo lee de ahi y lo escribe como
# `lens_scope`.
_LENS_SCOPE_KEY = "_lens_scope_effective"

_MODEL_REPORTED_PATTERNS = (
    re.compile(r"^\s*model:\s*(?P<model>[^\s]+)\s*$", re.MULTILINE),
    re.compile(r"^\s*>\s*\w+\s*[·|-]\s*(?P<model>[^\s]+)\s*$", re.MULTILINE),
)


def _extract_reported_model(stderr_text: str) -> str | None:
    """Modelo que el CLI declara usar, o None si no lo declara.

    Before: `stderr_text` es el STDERR crudo del backend (puede traer codigos
        ANSI y venir vacio).
    During: limpia los escapes ANSI y prueba los patrones conocidos en orden.
    After: retorna el primer modelo reconocido, o None. NUNCA lanza: este dato
        es telemetria y no puede tumbar una ronda que si respondio.
    """
    if not stderr_text:
        return None
    clean = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", stderr_text)
    for pattern in _MODEL_REPORTED_PATTERNS:
        match = pattern.search(clean)
        if match:
            return match.group("model").strip() or None
    return None


def _render_model_flag(profile: dict, backend_cfg: dict) -> list[str]:
    """Renderiza la plantilla `model_flag` del BACKEND con el modelo del PERFIL.

    WOT-2026-047y. El modelo es atributo del PERFIL pero su SINTAXIS es del
    BACKEND: cada CLI la escribe a su manera (`--model X`, `-m X`, `--model=X`).
    Por eso la plantilla se declara en el backend -- `model_flag: ["--model",
    "{model}"]` -- y aqui solo se sustituye. Meter `--model` en
    `backends.<n>.args` seria PEOR que no hacer nada: `args` aplica a TODOS los
    perfiles del backend y fijaria un modelo unico, rompiendo el contrato
    perfil->modelo. Precedente de sintaxis en el arbol: `bus/review_bridge.py`
    invoca opencode con `["--agent", "manager", "--model", model]`.

    Before: `profile` puede declarar `model` (str no vacio) o no declararlo /
        declararlo `null`; `backend_cfg` puede declarar `model_flag` como lista
        de strings con `{model}` en algun elemento.
    During: sin modelo en el perfil no renderiza nada (los perfiles
        `model: null` -- `proposer_claude`, `challenger_codex` -- dejan que el
        CLI use su default, que es el contrato vigente). Con modelo, sustituye
        `{model}` en cada elemento de la plantilla.
    After: retorna la lista de argumentos a insertar (vacia si el perfil no
        declara modelo). Un perfil CON modelo contra un backend SIN plantilla
        lanza RuntimeError en vez de devolver `[]`: devolver la lista vacia
        reintroduciria el defecto exacto que el ticket cierra -- el CLI correria
        su default y el scorecard registraria el declarado, sin senal. El
        validador de config (`_validate_ensemble_agent_model`) lo bloquea antes,
        en la carga; esta comprobacion es la defensa en profundidad para el
        `backend_cfg` que NO pasa por el loader (inyeccion directa en tests o en
        un caller futuro), porque el modo de fallo es SILENCIOSO y por eso no
        puede depender de una sola barrera.
    """
    model = profile.get("model")
    if not model:
        return []
    template = backend_cfg.get("model_flag")
    if not template:
        raise RuntimeError(
            f"el perfil declara model '{model}' pero el backend "
            f"'{profile.get('backend')}' no declara plantilla 'model_flag': el "
            "modelo se perderia y el CLI correria su default en silencio "
            "(WOT-2026-047y)"
        )
    return [part.replace("{model}", model) for part in template]


def _render_readonly_agent_flag(profile: dict, backend_cfg: dict) -> list[str]:
    """Traduce `write: false` del PERFIL a `--agent <readonly>` del BACKEND.

    WOT-2026-048k. `write: false` era un campo DECORATIVO: `agents_config.py`
    validaba su TIPO (bool) y nadie validaba su EFECTO, asi que la unica
    consecuencia de declararlo era que el lector confiaba en el. Sin `--agent`,
    `opencode run` cae en su `default_agent` -- que en este repo es `builder`,
    con `edit/bash/task: allow` -- y la lente auditora recibia el system prompt
    del Builder: instrucciones para implementar el ticket activo y cerrarlo con
    `--mark-ready`. Medido 2026-08-05: una lente GLM delibero sobre su whitelist
    de `Files Likely Touched` y sobre si invocar `--mark-ready`, ninguna de las
    dos cosas presente en su bundle. Lo unico que impidio la escritura fue la
    disciplina del propio modelo, que no es un guardrail.

    La asimetria con `_render_model_flag` es DELIBERADA. Alli un perfil con
    modelo contra un backend sin plantilla lanza RuntimeError, porque el modo de
    fallo es silencioso Y el scorecard registraria un dato FALSO. Aqui, en
    cambio, un backend sin `readonly_agent` no puede recibir un nombre de agente
    inventado: el CLI lo rechazaria, o peor, lo resolveria a otra cosa. Se
    devuelve `[]` y la restriccion queda sin cablear para ESE backend. Esa
    laguna es real y se cierra con el gate fail-closed
    (`check_agent_write_enforced`), que es superficie propia y NO entra aqui:
    hoy los 7 perfiles del ensemble declaran `write: false` y ningun backend
    salvo `opencode` declara enforcement, asi que un fail-closed en esta funcion
    tumbaria el ensemble entero -- incluidos los `channel: api`, que van por HTTP
    y nunca tuvieron el problema.

    Before: `profile` puede declarar `write` (bool) o no declararlo;
        `backend_cfg` puede declarar `readonly_agent` (str no vacio).
    During: sin `write: false` no renderiza nada (backward-compat). Con
        `write: false` y `readonly_agent` declarado, emite `["--agent", <name>]`.
    After: retorna la lista de argumentos a insertar (vacia si no aplica). El
        caller la coloca ANTES del prompt / del sentinel `-`, porque cualquier
        argumento posterior al prompt lo leeria el CLI como parte del mensaje.
    """
    if profile.get("write") is not False:
        return []
    agent_name = backend_cfg.get("readonly_agent")
    if not agent_name:
        return []
    return ["--agent", agent_name]


def _transport_agent(
    profile: dict, backend_cfg: dict, messages: list[dict], timeout: int
) -> str:
    """One-shot CLI del backend (p.ej. `claude -p`, `codex exec`).

    El exit code NO se usa como veredicto (exit 0 con Auth Error, medido en
    opencode): el caller valida por CONTENIDO. En timeout se mata el ARBOL de
    procesos (ver _kill_process_tree) y se lanza RuntimeError: el caller lo
    registra como backend caido (STEP_SKIP), nunca lo inventa.

    WOT-2026-026n -- entrega del prompt:
    - Por DEFECTO el prompt va por argv (backward-compat).
    - Si el backend declara ``prompt_via_stdin: true``, el prompt va por STDIN
      (``communicate(input=...)``) y el cmd lleva el sentinel ``-``. Es la causa
      raiz del hang del bucle ``run`` en Windows: ``proposer_claude``
      (channel=agent) metia el payload completo en la linea de comando y el CLI
      colgaba (analogo al WinError 206 de codex, WOT-2026-035c, resuelto igual:
      prompt por stdin). Los backends ``channel: api`` (los nan) no pasan por
      aqui -- van por HTTP y nunca sufrieron el hang.

    WOT-2026-038o -- contrato de AMBITO:
    - `backend_cfg["repo_root"]` (opcional) es el arbol desde el que el hijo
      debe operar. Se pasa como `cwd=` al Popen SOLO si viene declarado; si
      falta, el hijo hereda el cwd del padre (conducta previa intacta).
    - Sin esto, un codex despachado por esta ruta refutaba sobre el arbol del
      PROCESO PADRE, no sobre el repo que la llamada declara. 038l cerro la
      misma clase de fallo en run_codex_audit.py y dejo ESTA ruta declarada
      OUT-OF-SCOPE; aqui se cierra con el mismo patron (repo_root opcional,
      `cwd=` condicional) y sin tocar la firma publica del transporte
      `transport(profile, backend_cfg, messages, timeout)`, que los tests
      inyectan como `_FakeTransport` con esa aridad exacta.

    WOT-2026-047y -- inyeccion del modelo:
    - `profile["model"]` NO entraba en argv en NINGUNA de las dos ramas, asi
      que el CLI corria su modelo por DEFECTO mientras el scorecard registraba
      el DECLARADO: la telemetria que rankea `backend_leaders.json` era falsa
      para todo perfil `channel: agent` con modelo. Se inyecta via
      `_render_model_flag` (plantilla del backend), antes del sentinel `-` en
      la rama stdin y antes del prompt en la rama argv.
    - `_transport_api` NO se toca: los `channel: api` pasan el modelo en el
      body JSON y estaban sanos.

    WOT-2026-048k -- inyeccion del agente read-only:
    - `profile["write"]` tampoco entraba en argv, asi que `write: false` era
      DECORATIVO y el CLI caia en su `default_agent` (aqui `builder`, con
      `edit/bash/task: allow`): una lente AUDITORA recibia el system prompt del
      IMPLEMENTADOR. Se inyecta via `_render_readonly_agent_flag`, en la misma
      posicion que el modelo y por la misma razon (antes del prompt / del
      sentinel `-`).
    - `_transport_api` NO se toca aqui tampoco: los `channel: api` no tienen
      system prompt de agente ni permisos de FS -- el vector no existe.
    """
    prompt = "\n\n".join(m["content"] for m in messages)
    via_stdin = bool(backend_cfg.get("prompt_via_stdin"))
    model_args = _render_model_flag(profile, backend_cfg)
    agent_args = _render_readonly_agent_flag(profile, backend_cfg)
    base = [
        backend_cfg["executable"],
        *backend_cfg.get("args", []),
        *model_args,
        *agent_args,
    ]
    if via_stdin:
        # El flag del modelo va ANTES del sentinel: `-` cierra la linea de
        # comando diciendo "el prompt viene por stdin", y cualquier argumento
        # posterior lo leeria el CLI como parte del prompt.
        cmd = [*base, "-"]
        stdin_mode = subprocess.PIPE
        stdin_payload: str | None = prompt
    else:
        cmd = [*base, prompt]
        stdin_mode = subprocess.DEVNULL
        stdin_payload = None
    repo_root = backend_cfg.get("repo_root")
    popen_kwargs: dict = {}
    if repo_root is not None:
        popen_kwargs["cwd"] = repo_root
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=stdin_mode,
        text=True,
        shell=False,
        encoding="utf-8",
        errors="replace",
        # WOT-2026-048d: `env` EXPLICITO. Sin este argumento, Popen hereda el
        # entorno completo del orquestador y cada lente recibia sus 4
        # credenciales (medido 2026-08-03). La auth de los CLI vive en el HOME,
        # no en variables: probe funcional con este entorno minimo -> `opencode
        # run --model ...` y `codex exec` responden correctamente.
        env=build_backend_env(),
        **popen_kwargs,
    )
    try:
        out, err = proc.communicate(input=stdin_payload, timeout=timeout)
        # WOT-2026-048g: el modelo REPORTADO viaja por el perfil (dict mutable
        # que el caller ya tiene) y no por el valor de retorno. La firma
        # `transport(profile, backend_cfg, messages, timeout) -> str` es
        # CONTRATO: los tests inyectan `_FakeTransport` con esa aridad exacta y
        # devolviendo un str; cambiarla a tupla los rompe a todos y convierte un
        # anadido de telemetria en una migracion.
        profile[_REPORTED_MODEL_KEY] = _extract_reported_model(err)
    except subprocess.TimeoutExpired:
        _kill_process_tree(proc.pid)
        # El mensaje NO debe AFIRMAR una causa que no ha medido. La version
        # anterior decia "pipe-inheritance hang" en TODO timeout, y ese texto fijo
        # se leyo como diagnostico: el 2026-08-04 llevo a atribuir tres timeouts de
        # `opencode` a un cuelgue del backend cuando el proceso estaba VIVO
        # trabajando y solo era lento (p90=236s contra un techo de 300s). Un
        # diagnostico inventado viaja a los informes y cuesta mas que el fallo.
        # Se enumeran las causas POSIBLES y se dice cual verificar primero.
        raise RuntimeError(
            f"backend CLI sin respuesta tras {timeout}s; arbol de procesos matado. "
            "CAUSA NO DETERMINADA -- comprueba en este orden: (1) latencia normal "
            "del backend por encima del techo (mira `latency_ms` de sus rondas OK "
            "en scorecard.jsonl y sube `timeout_s` de ese backend en agents.json "
            "si roza); (2) el proceso seguia vivo al morir (tasklist durante la "
            "corrida); (3) pipe-inheritance hang (medido 2026-07-16), que es UNA "
            "hipotesis, no el veredicto por defecto."
        ) from None
    # WOT-2026-048g: un rc != 0 marca la salida como NO UTILIZABLE. El exit code
    # sigue sin ser veredicto POSITIVO -- un rc 0 con Auth Error es el caso que
    # obliga a validar por CONTENIDO, y eso no cambia --, pero un rc != 0 es un
    # fallo DECLARADO por el propio CLI y descartarlo era lo que dejaba pasar
    # basura como aportacion. Medido 2026-08-03: `codex.cmd exec` devuelve rc=1
    # con el volcado de un `taskkill` ("CORRECTO: el proceso con PID ... ha sido
    # terminado.") en STDOUT; el scorecard lo registraba con failure_mode None,
    # o sea indistinguible de una revision real. Se anota en el texto en vez de
    # vaciarlo: vaciar borraria la evidencia de QUE devolvio el backend.
    # `getattr` y no `proc.returncode`: un Popen REAL siempre lo tiene tras
    # `communicate()`, pero los dobles de test que solo capturan el argv no, y
    # un AttributeError aqui convertiria un fallo de fixture en un fallo de
    # transporte. Ausente = 0 = conducta heredada (aditividad).
    rc = getattr(proc, "returncode", 0)
    if rc:
        return f"{_TRANSPORT_FAILED_PREFIX}rc={rc}\n{out or ''}"
    return out or ""


# WOT-2026-042v: NINGUNA LENTE VE EL repo_destino. El mecanismo de ambito lo
# cerro WOT-2026-038o (`repo_root` -> `cwd` del Popen, _transport_agent) y
# quedo CABLEADO PERO SIN INVOCAR: censo al HEAD 8f7c5ff -- `'repo_root' in
# json.dumps(agents.json)` -> False en motor Y destino. Consecuencia medida: un
# perfil `channel: agent` hereda el cwd del PADRE (el repo_motor), asi que su
# "no existe" sobre un artefacto del destino es un FALSO NEGATIVO POR AMBITO,
# no un hallazgo (14 objeciones auditadas en 2026-08-10/11: 9 falsos positivos,
# y los 9 son afirmaciones SOBRE EL ARBOL emitidas sin poder verlo).
#
# POR QUE SE RESUELVE AQUI Y NO EN `agents.json`: el DoD (b) prohibe hardcodear
# la ruta del destino -- el motor es portable y `backend_cfg` es POR BACKEND
# (compartido por todos los perfiles que lo usan), mientras que el ambito es
# POR VUELO. La ruta solo puede salir del runtime: `--project-root` (que el CLI
# ya resuelve con `_resolve_project_root`) o `AGENT_PROJECT_ROOT`.
#
# POR QUE NO EXIGE ALLOWLIST DE LECTURA (pregunta abierta de la ficha,
# resuelta por medicion): cambiar el `cwd` de un hijo NO le concede ninguna
# lectura nueva -- ya tiene filesystem completo y alcanza cualquier ruta
# ABSOLUTA (medido en WOT-2026-030a: una lente leyo un fichero del repo real
# por ruta absoluta desde dentro de su sandbox). El bloqueante de seguridad de
# la ficha aplica a la via que DA filesystem a quien hoy no lo tiene (tools en
# el payload de los `channel: api`), que es NON-GOAL declarado de este ticket.
# `ensemble_payload_allowlist` (WOT-2026-041t) es OTRA capa y no puede
# sustituir a esta: decide que fichero lee EL DISPATCHER antes de enviar, y no
# alcanza a un subproceso.
def resolve_lens_repo_root(
    profile: dict,
    backend_cfg: dict,
    project_root: Path | None = None,
) -> tuple[str | None, str]:
    """Ambito desde el que debe observar la lente, y su etiqueta auditable.

    Before: `profile` es la entrada de `ensemble_profiles` (declara `channel` y,
        opcionalmente, `repo_scope: "destino"`); `backend_cfg` es su entrada de
        `backends` (puede declarar `repo_root` explicito, contrato 038o);
        `project_root` es el destino-rol ya resuelto por el caller, o None.
    During: decide por precedencia -- canal sin filesystem, `repo_root`
        explicito del backend, perfil que no pide destino, y por ultimo la
        resolucion del destino desde `project_root` o `AGENT_PROJECT_ROOT`.
        No lee ningun fichero ni lanza procesos.
    After: retorna `(cwd_o_None, scope)`. NUNCA lanza: un ticket code-only, o
        un vuelo sin destino resoluble, cae a la conducta heredada (el hijo
        hereda el cwd del padre) en vez de empezar a fallar -- es el
        ANTI-FALSO-POSITIVO del DoD. La degradacion NO es muda: `scope` la
        nombra (`motor:destino-no-resoluble`), porque un fallback silencioso
        haria indistinguible "la lente vio el arbol" de "la lente iba ciega",
        que es justo el falso verde que este ticket persigue.
    """
    # Limite de CLASE, no bug: un `channel: api` no tiene filesystem que apuntar
    # (NON-GOAL explicito de la ficha). Se etiqueta para que el scorecard no
    # mezcle dos poblaciones con tasas de acierto distintas.
    if profile.get("channel") == "api":
        return None, "sin-fs"
    # Contrato WOT-2026-038o intacto: un `repo_root` declarado manda y su
    # conducta no cambia.
    declared = backend_cfg.get("repo_root")
    if declared is not None:
        return str(declared), "declarado"
    if profile.get("repo_scope") != "destino":
        return None, "motor"
    candidato = project_root or os.environ.get("AGENT_PROJECT_ROOT") or ""
    if not str(candidato).strip():
        return None, "motor:destino-no-resoluble"
    try:
        resuelto = Path(candidato).resolve()
    except (OSError, ValueError):
        return None, "motor:destino-irresoluble"
    # Mismo invariante que `_resolve_project_root`: el destino-rol NUNCA es el
    # propio motor. Sin esto, un AGENT_PROJECT_ROOT mal puesto daria un
    # "destino" verde que en realidad observa el motor -- el falso verde exacto
    # que el DoD (d) obliga a poder distinguir.
    if resuelto == MOTOR_ROOT:
        return None, "motor:destino-es-el-motor"
    if not resuelto.is_dir():
        return None, "motor:destino-inexistente"
    return str(resuelto), "destino"


def send_to_profile(
    profile_name: str,
    messages: list[dict],
    *,
    config: dict,
    sensitivity: str | None = None,
    transport=None,
    # WOT-2026-042v: el destino-rol desde el que debe observar una lente que
    # declara `repo_scope: destino`. Opcional y por defecto None: los callers
    # que no lo pasan (p.ej. `smoke_profile`) caen a `AGENT_PROJECT_ROOT` y, sin
    # el, a la conducta heredada. Aditivo: cero efecto sobre los perfiles que no
    # declaran `repo_scope`.
    project_root: Path | None = None,
    # 120 s no daba: un reto de review sobre un repo real hace que el backend
    # CLI inspeccione arbol e historial. Medido 2026-07-31: prompt trivial
    # rc=0 en 10,1 s; payload real de 1,9 KB rc=0 en 143,4 s. Con 120 s el
    # dispatch abortaba y el mensaje "backend CLI sin respuesta" atribuia mal
    # la causa -> reviews decorativas.
    timeout: int = 300,
) -> str:
    """UNICO camino de salida hacia un backend; el preflight corre AQUI.

    Before: `profile_name` existe en `ensemble_profiles` (config validada);
        `messages` es la lista chat-completions; `sensitivity` es la del
        payload (CLI) o None (cae al perfil; ausente en ambos = private);
        `project_root` es el destino-rol ya resuelto, o None.
    During: (1) privacy_preflight fail-closed -- si bloquea, lanza
        DispatchBlockedError SIN tocar red; (2) resuelve transporte por
        `channel` (api|agent) salvo `transport` inyectado (tests hermeticos);
        (3) WOT-2026-042v: resuelve el AMBITO de la lente y sella su etiqueta
        en `profile[_LENS_SCOPE_KEY]` para que `_record_round` la registre.
    After: retorna el texto de respuesta del backend (puede ser vacio: el
        caller lo registra como no-aportacion, nunca lo inventa). El `profile`
        queda sellado con el ambito EFECTIVO (no el pedido): si el destino no
        se pudo resolver, la etiqueta lo dice.
    """
    profile = config["ensemble_profiles"][profile_name]
    backend_cfg = config["backends"][profile["backend"]]
    # WOT-2026-042v: el ambito se resuelve AQUI porque este es el UNICO camino
    # de salida hacia un backend (lo declara el docstring, y el canary de
    # WOT-2026-042k midio que 9 de 9 `dispatch.py` de gobierno llaman a esta
    # funcion DIRECTAMENTE sin pasar por el CLI `run`): cualquier otro punto
    # dejaria fuera la ruta por la que circulan los bundles reales.
    cwd_lente, lens_scope = resolve_lens_repo_root(profile, backend_cfg, project_root)
    profile[_LENS_SCOPE_KEY] = lens_scope
    if cwd_lente is not None and backend_cfg.get("repo_root") != cwd_lente:
        # COPIA, nunca mutacion: `backend_cfg` es la entrada COMPARTIDA de
        # `backends` -- 3 perfiles del motor comparten backend --, y escribir el
        # `repo_root` de un vuelo dentro de la config viva se lo colaria a los
        # demas perfiles y persistiria entre llamadas dentro del proceso.
        backend_cfg = {**backend_cfg, "repo_root": cwd_lente}
    # WOT-2026-026t: el techo NO puede ser uno solo para todos los backends. El
    # default de 300 s se fijo con datos de codex. `opencode` (GLM) no tiene una
    # media alta: tiene VARIANZA enorme. Medido 2026-08-04 sobre 14 rondas del
    # scorecard: p50=91 s, max=280 s, desviacion tipica 83 s, ratio max/min 80x.
    # Y la MISMA tarea (un bundle de auditoria de 5,9 KB) se midio TRES veces con
    # resultados distintos: 388 s completo, 500 s completo, y una que agoto 600 s.
    # De ahi 900 s: lo que hay que cubrir no es la media, es la COLA.
    #
    # CINCO hipotesis REFUTADAS por probe antes de llegar aqui -- no repetirlas:
    #   backend caido/geo-bloqueado -> un PONG responde en 7 s;
    #   tamano del payload          -> 5000 chars en 5 s, y hay rondas OK con 17 KB;
    #   acceso a filesystem         -> leer un fichero y contar sus lineas, 9 s;
    #   bug en este modulo          -> el CLI directo `opencode run --model` tarda igual;
    #   concurrencia entre lentes   -> el control con GLM SOLO tardo 500 s, MAS
    #                                  que los 388 s con Codex en paralelo.
    # Lo que si tarda es el TRABAJO que el bundle ordena (leer un contrato de 259
    # lineas, auditar 3 entradas, responder 6 preguntas), no el transporte.
    #
    # Se lee del backend para no regalarle 900 s a `nan_api`, que responde en
    # segundos; el default del parametro sigue mandando si el backend no declara
    # `timeout_s` (aditivo: cero efecto sobre los que no lo usan).
    timeout = int(backend_cfg.get("timeout_s") or timeout)
    payload_text = json.dumps(messages, ensure_ascii=False)
    effective = sensitivity or profile.get("data_sensitivity")
    allowed, reason = privacy_preflight(
        payload_text,
        effective,
        backend_cfg,
        config.get("ensemble_private_roots", []),
    )
    if not allowed:
        raise DispatchBlockedError(
            f"privacy_preflight BLOQUEA el envio via '{profile_name}': {reason}"
        )
    # WOT-2026-042k: el canary observa AQUI, no solo en `run_pipeline`.
    # MEDIDO en el review: 9 de 9 `dispatch.py` de gov_* llaman a esta funcion
    # DIRECTAMENTE y CERO pasan por el CLI `run`, asi que un canary anclado solo
    # a `run_pipeline` vigilaba una ruta por la que no circula ningun bundle real
    # -- "barrera del alcance" de AGENTS.md: cableado, muerde, y no mira donde
    # ocurre el fallo. `send_to_profile` es el UNICO camino de salida hacia un
    # backend (lo declara su propio docstring), luego es el paso obligado.
    # Va DESPUES del preflight a proposito: si el envio se bloquea por privacidad
    # no hay nada que auditar, y el canary nunca debe retrasar un fail-closed.
    receipt_canary(payload_text, root=MOTOR_ROOT, ticket=profile_name)
    if transport is None:
        transport = _transport_api if profile["channel"] == "api" else _transport_agent
    return transport(profile, backend_cfg, messages, timeout)


@contextlib.contextmanager
def _locked_for_append(handle):
    """Lock EXCLUSIVO del SO sobre el fichero abierto, liberado siempre.

    WOT-2026-041b. Es lock de ESCRITURA unicamente: `_read_scorecard` no pasa
    por aqui, asi que la lectura nunca se serializa.

    Before: `handle` esta abierto en modo append binario.
    During: toma el lock (msvcrt en Windows, fcntl en POSIX). Si la plataforma
        no ofrece ninguno de los dos, degrada a no-op en vez de romper: el
        append de una linea corta ya era el comportamiento historico.
    After: libera el lock aunque el bloque levante.
    """
    locker = None
    if msvcrt is not None:
        locker = "msvcrt"
    elif fcntl is not None:
        locker = "fcntl"
    if locker == "fcntl":
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    elif locker == "msvcrt":
        # msvcrt.locking bloquea un RANGO relativo a la POSICION ACTUAL. Hay
        # que anclarlo en un offset FIJO (el byte 0) que todos los procesos
        # compartan: si cada uno bloquea desde su propio fin-de-fichero, los
        # rangos son DISTINTOS y no se excluyen entre si -- el lock no serviria
        # de nada. Medido: con el ancla en el EOF el unlock fallaba con
        # "Permission denied" porque el write habia movido la posicion.
        handle.seek(0)
        while True:
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                break
            except OSError:
                # LK_LOCK reintenta 10 veces y luego lanza: seguimos esperando
                # en vez de perder la fila.
                time.sleep(0.05)
    try:
        yield
    finally:
        # El fallo al LIBERAR no puede enmascarar la excepcion del cuerpo (un
        # disco lleno debe seguir propagando), pero tampoco debe desaparecer en
        # silencio: se avisa por stderr. El cierre del fichero libera el lock
        # de todos modos. Hallazgo del MANAGER_REVIEW: el `except OSError:
        # pass` original se tragaba esta senal entera.
        try:
            if locker == "fcntl":
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            elif locker == "msvcrt":
                # mismo ancla que al tomarlo: el write dejo la posicion al
                # final, y liberar desde ahi apuntaria a OTRO rango.
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError as exc:
            print(
                f"[WARN] no se pudo liberar el lock del scorecard: {exc}",
                file=sys.stderr,
            )


def append_scorecard(project_root: Path, row: dict) -> Path:
    """Append-only, UTF-8 SIN BOM, una linea JSON (claves normalizadas) por evento.

    WOT-2026-041b: la escritura va bajo lock EXCLUSIVO del SO y en UNA sola
    llamada `write` de bytes ya serializados. Con 4 HILOS nunca se corrompio
    (el GIL serializa un write corto: 435 lineas reales, 0 corruptas), pero
    con PROCESOS concurrentes -- hacia donde empuja el sistema-- dos appends
    pueden entrelazarse y partir una linea. El formato de linea y
    SCORECARD_FIELDS no cambian (contrato de WOT-2026-025y).
    """
    path = project_root / SCORECARD_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = {k: row.get(k) for k in SCORECARD_FIELDS}
    payload = (json.dumps(normalized, ensure_ascii=False) + "\n").encode("utf-8")
    # binario a proposito: sin traduccion de saltos de linea y con el payload
    # completo en un unico write, de modo que el lock cubre la linea entera.
    # SIN os.fsync a proposito: el contrato de este ticket es NO CORRUPCION, y
    # eso lo da el lock + el write unico. fsync anade DURABILIDAD ante corte de
    # energia, que es otra propiedad y otro ticket. Medido (200 filas): 1.343
    # ms/fila con fsync vs 1.118 sin el (~20%). Una lente del MANAGER_REVIEW
    # estimo "100x mas lento" y pidio quitarlo; la cifra real es mucho menor,
    # pero se retira igualmente por ALCANCE, no por coste.
    with open(path, "ab") as f, _locked_for_append(f):
        f.write(payload)
        f.flush()
    return path


def emit_nonce(
    project_root: Path,
    *,
    commit_sha: str,
    loop_id: str,
    issuer_role: str,
    issuer_backend_key: str,
    nonce: str | None = None,
) -> tuple[str, Path]:
    """Emite (registra) un challenge_nonce ANTES de un fan-out de gobierno.

    WOT-2026-040b. El nonce nace AQUI, en un paso SEPARADO del fan-out, para que
    `check_loop_execution` pueda exigir que cada receipt de ronda copie un nonce
    que ya existia en `emitted_nonces.jsonl`. La independencia es OPERACIONAL, no
    criptografica (adjudicado por Codex 2026-07-24): en dogfooding el mismo agente
    puede encarnar orquestador y ejecutor, asi que esto NO prueba "otro actor" --
    prueba "paso previo separado, no derivable de los receipts". Por eso el gate
    tambien excluye `issuer_backend_key` del recuento de N lentes distintas: quien
    emite no cuenta como quien ejecuta.

    Before: `project_root` es el destino-rol (no el motor); `commit_sha`/`loop_id`
        identifican el fan-out; `issuer_role`/`issuer_backend_key` declaran quien
        emite (p.ej. orchestrator / BA01). `nonce` se genera si no se pasa.
    During: genera un nonce aleatorio (secrets.token_hex, si no se dio uno) y
        APPENDEA UNA fila con los `EMITTED_NONCE_FIELDS` bajo lock exclusivo del SO
        (mismo mecanismo que el scorecard). `issued_before_ts == ts` de emision.
    After: retorna `(nonce, path)`. La fila es la unica prueba de que la ceremonia
        previa ocurrio; sin ella, un receipt con ese nonce es un nonce fabricado.
    """
    if nonce is None:
        nonce = secrets.token_hex(16)
    ts = _now_iso()
    row = {
        "ts": ts,
        "issuer_role": issuer_role,
        "issuer_backend_key": issuer_backend_key,
        "issued_before_ts": ts,
        "commit_sha": commit_sha,
        "loop_id": loop_id,
        "challenge_nonce": nonce,
    }
    path = project_root / EMITTED_NONCES_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = {k: row.get(k) for k in EMITTED_NONCE_FIELDS}
    payload = (json.dumps(normalized, ensure_ascii=False) + "\n").encode("utf-8")
    with open(path, "ab") as f, _locked_for_append(f):
        f.write(payload)
        f.flush()
    return nonce, path


def read_emitted_nonces(project_root: Path) -> list[dict]:
    """Filas de emision del destino-rol (vacio si el fichero no existe).

    Lectura ESTRICTA de UTF-8: un fichero ilegible NO se lee "a la fuerza" a
    mojibake (que dejaria cero nonces = todo receipt rechazado en falso). Una
    linea corrupta se salta con aviso, nunca se inventa un nonce.
    """
    path = project_root / EMITTED_NONCES_REL
    if not path.exists():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            print(f"[WARN] fila de nonce ilegible, saltada: {exc}", file=sys.stderr)
    return rows


def _read_scorecard(project_root: Path) -> tuple[list[dict], str]:
    path = project_root / SCORECARD_REL
    raw = path.read_bytes() if path.exists() else b""
    sha = hashlib.sha256(raw).hexdigest()
    rows = [
        json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()
    ]
    return rows, sha


def _adjudicated_cells(rows: list[dict]) -> dict:
    """Ultima adjudicacion por (ticket, ronda, rol); supersede pisa por orden."""
    adjudicated: dict = {}
    for row in rows:
        key = (row.get("ticket"), row.get("ronda"), row.get("rol"))
        if row.get("event") in ("adjudicacion", "supersede"):
            if row.get("outcome") in ADJUDICATED_OUTCOMES:
                adjudicated[key] = row
        elif row.get("event") == "ronda" and row.get("outcome") == "no-aportacion":
            adjudicated.setdefault(key, row)
    return adjudicated


def regenerate_leaders(project_root: Path) -> Path:
    """Proyeccion DERIVADA del scorecard: nunca editada a mano, regenerable.

    Lider por task_type SOLO con n>=LEADER_MIN_N; por debajo, 'sin lider,
    rotar'. Incluye hash sha256 de la fuente (proyeccion desfasada =
    detectable) y la politica de exploracion como campo del artefacto.
    """
    rows, sha = _read_scorecard(project_root)
    per_type: dict = {}
    for row in _adjudicated_cells(rows).values():
        task_type = row.get("task_type") or "desconocido"
        cells = per_type.setdefault(task_type, {})
        cell_key = f"{row.get('backend')}|{row.get('model')}"
        cell = cells.setdefault(
            cell_key,
            {
                "backend": row.get("backend"),
                "model": row.get("model"),
                "n": 0,
                "adoptadas": 0,
                "falsos": 0,
            },
        )
        cell["n"] += 1
        if row.get("outcome") == "adoptada":
            cell["adoptadas"] += 1
        if row.get("outcome") in ("falso-positivo", "error-factual"):
            cell["falsos"] += 1

    por_task_type: dict = {}
    for task_type, cells in per_type.items():
        best = max(
            cells.values(),
            key=lambda c: (c["adoptadas"] / c["n"] if c["n"] else 0.0, c["n"]),
        )
        if best["n"] >= LEADER_MIN_N:
            por_task_type[task_type] = {
                "lider": {"backend": best["backend"], "model": best["model"]},
                "n_muestras": best["n"],
                "tasa_adoptadas": round(best["adoptadas"] / best["n"], 3),
                "falsos": best["falsos"],
            }
        else:
            por_task_type[task_type] = {
                "lider": None,
                "nota": f"sin lider, rotar (n={best['n']} < {LEADER_MIN_N})",
                "n_muestras": best["n"],
            }

    out = {
        "generated_at": _now_iso(),
        "scorecard_sha256": sha,
        "leader_min_n": LEADER_MIN_N,
        "exploration_policy": EXPLORATION_POLICY,
        "por_task_type": por_task_type,
        "derivado": "NUNCA editar a mano: regenerado desde scorecard.jsonl",
    }
    out_path = project_root / LEADERS_REL
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    return out_path


def _backend_version(backend_cfg: dict) -> str | None:
    """Version del CLI del backend (best-effort); None para channel=api."""
    executable = backend_cfg.get("executable")
    if not executable:
        return None
    try:
        proc = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            timeout=30,
            shell=False,
            encoding="utf-8",
            errors="replace",
        )
        return (proc.stdout or proc.stderr or "").strip().splitlines()[0][:120]
    except Exception:
        return None


def smoke_profile(
    profile_name: str,
    *,
    config: dict,
    transport=None,
    nonce: str = "PONG-019o",
    timeout: int = 90,
) -> dict:
    """Smoke round-trip por CONTENIDO: el token debe volver en la respuesta."""
    messages = [
        {
            "role": "user",
            "content": (f"Reply with exactly this token and nothing else: {nonce}"),
        }
    ]
    try:
        reply = send_to_profile(
            profile_name,
            messages,
            config=config,
            sensitivity="public",
            transport=transport,
            timeout=timeout,
        )
    except DispatchBlockedError:
        raise
    except Exception as exc:  # STEP_SKIP documentado: backend caido no aborta
        return {
            "profile": profile_name,
            "alive": False,
            "detail": f"{type(exc).__name__}: {exc}",
        }
    alive = nonce in (reply or "")
    return {
        "profile": profile_name,
        "alive": alive,
        "detail": (reply or "")[:200].strip(),
    }


def resolve_fallback_backend(
    pool_backend: str,
    *,
    config: dict,
    check_alive=None,
) -> str:
    """Elige un perfil de backend con `backend` DISTINTO al del pool auditado.

    Before: `pool_backend` es el valor `backend` (p.ej. `nan_api`) del pool
        que se esta auditando; "clase distinta" (WOT-2026-026k) se define
        como `profile["backend"] != pool_backend`, NUNCA una taxonomia mas
        fina. `config` es la config ya cargada (`load_motor_config()` o
        equivalente) con `ensemble_profiles` y `backends`. `check_alive` es
        inyectable para tests hermeticos; por defecto usa `smoke_profile`
        (round-trip real por CONTENIDO, nunca por exit code).
    During: recorre `ensemble_profiles` en orden estable (orden de
        insercion del dict de config), descarta los perfiles cuyo
        `backend` coincide con `pool_backend`, y prueba cada candidato con
        `check_alive(profile_name, config=config)` hasta encontrar uno
        vivo. `check_alive` debe devolver un dict con clave `alive: bool`
        (mismo contrato que `smoke_profile`).
    After: retorna el `profile_name` del primer candidato vivo de clase
        distinta. Si no hay NINGUN candidato de clase distinta (o ninguno
        vivo), lanza `DispatchBlockedError` fail-cerrado: el caller NUNCA
        debe caer de vuelta a `pool_backend` en silencio.
    """
    if check_alive is None:
        check_alive = smoke_profile

    profiles = config.get("ensemble_profiles", {})
    candidates = [
        name
        for name, profile in profiles.items()
        if profile.get("backend") != pool_backend
    ]
    if not candidates:
        raise DispatchBlockedError(
            f"sin candidatos de clase distinta a '{pool_backend}' en "
            "ensemble_profiles: fallback fail-cerrado (WOT-2026-026k)"
        )

    tried: list[str] = []
    for name in candidates:
        result = check_alive(name, config=config)
        tried.append(f"{name}:{'alive' if result.get('alive') else 'dead'}")
        if result.get("alive"):
            return name

    raise DispatchBlockedError(
        f"ningun candidato de clase distinta a '{pool_backend}' esta vivo "
        f"(probados: {', '.join(tried)}); fallback fail-cerrado (WOT-2026-026k)"
    )


def _load_lens_filter():
    """Importa `filter_lens_output` del script hermano (WOT-2026-039c).

    Before: `scripts/filter_lens_output.py` existe (entregado por 027o).
    During: carga por ruta y registra en sys.modules antes de ejecutar
        (el modulo carga a su vez check_bundle_receipts por el mismo patron).
    After: retorna la funcion. Lanza ImportError si no carga: sin filtro NO se
        corre en modo degradado -- un pipeline que declara el filtro y lo
        pierde en silencio seria exactamente el fail-open que este ticket
        cierra.
    """
    path = Path(__file__).resolve().parent / "filter_lens_output.py"
    spec = importlib.util.spec_from_file_location("filter_lens_output", path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensivo
        raise ImportError(f"no se puede cargar {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["filter_lens_output"] = module
    spec.loader.exec_module(module)
    return module.filter_lens_output


def _load_receipt_checker():
    """Importa `check_bundle` de check_bundle_receipts SIN modificarlo (WOT-2026-042k).

    Before: `scripts/check_bundle_receipts.py` existe y define `check_bundle(text, root)`.
    During: carga por ruta y REGISTRA en `sys.modules` antes de ejecutar -- un
        `@dataclass` del modulo lo exige (mismo patron que `filter_lens_output`).
    After: retorna la funcion, o `None` si el modulo no carga. A diferencia del
        filtro de salida, aqui NO es fail-closed: el canary OBSERVA, y perder el
        observador no debe tumbar un fan-out legitimo.
    """
    path = Path(__file__).resolve().parent / "check_bundle_receipts.py"
    try:
        spec = importlib.util.spec_from_file_location("check_bundle_receipts", path)
        if spec is None or spec.loader is None:  # pragma: no cover - defensivo
            return None
        module = importlib.util.module_from_spec(spec)
        sys.modules["check_bundle_receipts"] = module
        spec.loader.exec_module(module)
        return module.check_bundle
    except (OSError, ImportError, AttributeError):  # pragma: no cover - defensivo
        return None


CANARY_LOG_REL = Path(".agent/runtime/ensemble/receipt_canary.jsonl")


def _persist_canary_measurement(measurement: dict) -> None:
    """Anade la medicion del canary como una linea NDJSON. NUNCA lanza.

    WOT-2026-042k, hueco senalado por el MANAGER_REVIEW: sin artefacto, el DoD
    de promocion a bloqueante ("cuando sus mediciones muestren saneado el rojo")
    no es ejecutable, porque no hay mediciones que consultar.

    Before: `measurement` es el dict que devuelve `receipt_canary`.
    During: append con el MISMO patron que el scorecard -- lock del SO +
        write binario unico, de modo que dos fan-outs concurrentes no entrelacen
        lineas. Reutiliza `_locked_for_append` en vez de abrir un segundo
        mecanismo de escritura.
    After: la linea queda en `<motor>/.agent/runtime/ensemble/receipt_canary.jsonl`.
        Ante CUALQUIER error de I/O degrada en silencio: observar es opcional,
        enviar no. Un canary que rompe el envio deja de ser canary.
    """
    try:
        path = MOTOR_ROOT / CANARY_LOG_REL
        path.parent.mkdir(parents=True, exist_ok=True)
        row = dict(measurement)
        row["timestamp"] = _now_iso()
        line = (json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8")
        with open(path, "ab") as handle, _locked_for_append(handle):
            handle.write(line)
            handle.flush()
    except (OSError, ValueError, TypeError):  # pragma: no cover - defensivo
        return


def receipt_canary(
    payload: str,
    *,
    root: Path,
    ticket: str,
    session_id: str | None = None,
) -> dict | None:
    """CANARY de recibos sobre el bundle que sale al fan-out (WOT-2026-042k).

    CONTRATO CANARY -- declarado explicitamente, porque "modo canary" sin estas
    cuatro respuestas es una palabra, no un modo:

    1. QUE AUDITA: el `payload` REAL de ESTE envio, no un glob del arbol. Es la
       diferencia que evita el deadlock de WOT-2026-042h: la deuda historica
       (35 pass / 19 fail sobre 54 bundles con `## PROBE`, medido 2026-07-27 con
       `--root <motor>`) NUNCA es evaluada, porque solo se mira lo que esta
       sesion esta a punto de enviar.
    2. QUE CUENTA COMO ROJO: >=1 seccion `## PROBE` sin recibo valido. Un payload
       SIN secciones `## PROBE` no es rojo: es `n/a` (no todos los pipelines son
       bundles de gobernanza con recibos).
    3. BLOQUEA O AVISA: **NO BLOQUEA**. Emite WARN a stderr y devuelve el conteo.
       Cablear fail-closed nace en rojo (1 de cada 3 bundles historicos falla) y
       reproduciria el deadlock que ya tumbo a 042h. Promover a bloqueante es
       decision posterior, CON los datos que este canary recoge.
    4. QUE ARTEFACTO CONSERVA: una linea NDJSON por medicion en
       `<motor>/.agent/runtime/ensemble/receipt_canary.jsonl`, ademas de
       devolverla al llamante. La primera version solo la devolvia, y el review
       lo marco como hueco con razon: sin artefacto, el DoD que el propio
       `guard_wiring_policy.yaml` escribe -- "promover a bloqueante cuando sus
       mediciones muestren saneado el rojo historico" -- es INEJECUTABLE, porque
       no habria mediciones que consultar. Un WARN a stderr que nadie agrega es
       indistinguible de no hacer nada.

    Before: `payload` es el texto que ira a las lentes; `root` es el repo contra
        el que resuelven los `path:` de los recibos.
    During: read-only. Si el checker no carga, devuelve None (degrada en
        silencio: observar es opcional, enviar no).
    After: devuelve `{"probes", "ok", "failed", "ticket", "session_id"}` o None
        si no aplica. NUNCA lanza ni bloquea el envio.
    """
    check_bundle = _load_receipt_checker()
    if check_bundle is None:
        return None
    try:
        results = check_bundle(payload, root)
    except (OSError, ValueError):  # pragma: no cover - defensivo
        return None
    if not results:
        return None
    failed = [r for r in results if not r.ok]
    measurement = {
        "probes": len(results),
        "ok": len(results) - len(failed),
        "failed": len(failed),
        "ticket": ticket,
        "session_id": session_id,
    }
    _persist_canary_measurement(measurement)
    if failed:
        print(
            f"[receipt-canary] WARN {ticket}: {len(failed)}/{len(results)} probe(s) "
            f"sin recibo valido en el bundle que sale al fan-out (NO bloquea; "
            f"WOT-2026-042k). Revalida: python scripts/check_bundle_receipts.py "
            f"--bundle <bundle.md> --root {root}",
            file=sys.stderr,
        )
        for r in failed:
            print(f"[receipt-canary]   {r.header}", file=sys.stderr)
            for p in r.problems:
                print(f"[receipt-canary]     - {p}", file=sys.stderr)
    else:
        print(
            f"[receipt-canary] OK {ticket}: {len(results)} probe(s) con recibo valido.",
            file=sys.stderr,
        )
    return measurement


def _record_round(
    project_root: Path,
    *,
    ticket: str,
    task_type: str,
    rol: str,
    profile: dict,
    backend_version: str | None,
    ronda: int,
    reply: str,
    input_bytes: int,
    context_kind: str,
    failure_mode: str | None = None,
    session_id: str | None = None,
    latency_ms: int | None = None,
    outcome_override: str | None = None,
    phase: str | None = None,
    loop_id: str | None = None,
    backend_key: str | None = None,
    commit_sha: str | None = None,
    challenge_nonce: str | None = None,
) -> None:
    # WOT-2026-039c: `outcome_override` permite registrar una salida DESCARTADA
    # por el filtro de lente sin vaciar `reply` -- vaciarlo para forzar el
    # outcome mentiria sobre lo que respondio el backend y borraria la
    # evidencia. La derivacion original (texto vacio -> no-aportacion) se
    # conserva intacta cuando no se pasa override.
    text = (reply or "").strip()
    # WOT-2026-048g: un transporte que fallo (rc != 0) NO es una intervencion.
    # Se deriva AQUI, en el registrador, y no solo en el bucle `run`, porque
    # `run_loop_round` -- la ruta que usa el gobierno por chat -- no pasa por el
    # filtro de lente y registraba la basura como aportacion valida. El texto se
    # CONSERVA (es la evidencia de que devolvio el backend); lo que cambia es su
    # clasificacion. Un `outcome_override` explicito del caller sigue mandando.
    if text.startswith(_TRANSPORT_FAILED_PREFIX):
        rc_line = text[len(_TRANSPORT_FAILED_PREFIX) :].split("\n", 1)[0].strip()
        outcome_override = outcome_override or "no-aportacion"
        failure_mode = failure_mode or f"transport_failed: {rc_line}"
    append_scorecard(
        project_root,
        {
            "ts": _now_iso(),
            "event": "ronda",
            "ticket": ticket,
            "rol": rol,
            "task_type": task_type,
            "backend": profile["backend"],
            "model": profile.get("model"),
            "backend_version": backend_version,
            "ronda": ronda,
            "outcome": outcome_override or ("no-aportacion" if not text else None),
            "evidencia": text[:500] or "(respuesta vacia)",
            "input_bytes": input_bytes,
            "context_kind": context_kind,
            "failure_mode": failure_mode,
            "session_id": session_id,
            "latency_ms": latency_ms,
            # WOT-2026-026q: ausentes (None) en las rondas del runner CLI, que
            # no pertenece a ningun bucle del registro citable.
            "phase": phase,
            "loop_id": loop_id,
            "backend_key": backend_key,
            # WOT-2026-040b: None en el runner CLI (no hay challenge emitido);
            # solo los bucles de gobierno atan el receipt al commit + al nonce
            # emitido fuera.
            "commit_sha": commit_sha,
            "challenge_nonce": challenge_nonce,
            # WOT-2026-043q: se mide sobre `text` (crudo, ya stripeado) y NO
            # sobre `evidencia`, que va truncada a 500. 0 == el backend no
            # aporto nada; es el unico observable que distingue "corrio y callo"
            # de "corrio y respondio".
            "output_chars": len(text),
            # WOT-2026-048g: el DECLARADO va en `model`; este es el que el
            # backend dijo usar. Que difieran es la senal que 047y no podia dar.
            "model_reported": profile.get(_REPORTED_MODEL_KEY),
            # WOT-2026-042v: lo sella `send_to_profile` sobre el profile. None =
            # la ronda no paso por el dispatcher (fila historica o caller que no
            # despacha): AUSENCIA de dato, que no es lo mismo que `motor`.
            "lens_scope": profile.get(_LENS_SCOPE_KEY),
        },
    )


def run_loop_round(
    profile_name: str,
    content: str,
    *,
    config: dict,
    project_root: Path,
    ticket: str,
    task_type: str,
    rol: str,
    phase: str,
    loop_id: str,
    backend_key: str,
    sensitivity: str,
    ronda: int = 0,
    context_kind: str = "diff",
    transport=None,
    session_id: str | None = None,
    commit_sha: str | None = None,
    challenge_nonce: str | None = None,
) -> str:
    """UNA ronda de un bucle de GOBIERNO (`launched_from: chat`), registrada.

    WOT-2026-026q. `run_pipeline` es el runner de la CLI y registra SOLO sus
    propias rondas; los bucles `1->9->2` (CONTRACT_AUDIT, MANAGER_REVIEW,
    CLOSE) los despacha el chat paso a paso, sin pasar por ese bucle, y por
    eso su telemetria se perdia entera: el scorecard quedaba MUDO y los campos
    `phase`/`loop_id`/`backend_key` del schema (WOT-2026-037b) no tenian ni un
    escritor. Esta funcion es el hueco que faltaba en el RUNNER.

    El registro va AQUI y NO en `send_to_profile` a proposito: esa primitiva la
    comparte el smoke check (`_premise_check`), cuyo trafico NO debe contar --
    un backend caido no puede ensuciar el ranking-- y los callers de
    `run_pipeline` ya registran via `_record_round`. Cablearlo en la primitiva
    produciria doble-conteo mas ruido de smoke.

    Before: `profile_name` existe en `ensemble_profiles`; `task_type` pertenece
        a `TASK_TYPES`; `phase`/`loop_id`/`backend_key` son los del registro
        citable de bucles (`.agent/config/agents.json::ensemble_registry`, ver
        `scripts/discover_loops.py`). `commit_sha`/`challenge_nonce`
        (WOT-2026-040b), cuando el caller los pasa, atan el receipt al commit
        bajo review y al nonce EMITIDO FUERA (`emit-nonce` ->
        `emitted_nonces.jsonl`), NO uno que esta funcion invente.
    During: despacha por `send_to_profile` (el preflight de privacidad corre
        alli, fail-closed) cronometrando con `time.perf_counter()`; luego
        APPENDEA exactamente UNA fila via `_record_round`, copiando
        `challenge_nonce` al receipt para que `check_loop_execution` pruebe que
        esta ronda respondio a ESE challenge. Una respuesta vacia se registra
        como `no-aportacion`, nunca como fila ausente.
    After: retorna el texto del backend tal cual (el consolidador es el chat,
        nivel 0: esta funcion no interpreta ni adjudica). Propaga
        `DispatchBlockedError` si el preflight bloquea -- en ese caso NO hay
        fila, porque no hubo ronda.
    """
    if task_type not in TASK_TYPES:
        raise ValueError(
            f"task_type '{task_type}' invalido; usa uno de {sorted(TASK_TYPES)}"
        )
    profile = config["ensemble_profiles"][profile_name]
    # WOT-2026-026t: `backend_key` es el RECIBO de quien ejecuto la ronda, y
    # `check_loop_execution` cuenta claves DISTINTAS para acreditar la
    # independencia del bucle. Una clave que no es la del perfil no "elige" nada
    # -- el transporte resuelve backend y modelo desde el PERFIL -- pero deja un
    # receipt que MIENTE sobre que lente audito. Medido 2026-08-04: dos rondas
    # de `challenger_opencode_glm_5_2` quedaron archivadas como BA12 (nan_api /
    # mimo-v2.5) por pasar la clave equivocada; el fallo no dio ningun sintoma.
    #
    # La comparacion es de IDENTIDAD EXACTA, no de backend: los cuatro perfiles
    # `nan_api` comparten backend, asi que un check por backend aceptaria
    # `challenger_nan_qwen3_6 + BA12` y fabricaria independencia entre dos
    # rondas del MISMO modelo. Se valida ANTES de despachar para no gastar una
    # llamada al backend en una ronda cuyo receipt ya nace invalido.
    expected_key = profile.get("backend_key")
    if expected_key and backend_key != expected_key:
        actual = (
            config.get("ensemble_registry", {}).get("backend_keys", {}).get(backend_key)
        ) or {}
        detalle = (
            f" ('{backend_key}' es {actual.get('backend')}/{actual.get('model')})"
            if actual
            else f" ('{backend_key}' no existe en el registro)"
        )
        raise ValueError(
            f"backend_key '{backend_key}' no corresponde al perfil "
            f"'{profile_name}', cuya clave es '{expected_key}'{detalle}. El "
            "receipt de la ronda quedaria atribuido a una lente que no ejecuto, "
            f"y la barrera de independencia cuenta esa columna. Usa "
            f"--backend-key {expected_key}."
        )
    _t0 = time.perf_counter()
    reply = send_to_profile(
        profile_name,
        [{"role": "user", "content": content}],
        config=config,
        sensitivity=sensitivity,
        transport=transport,
        project_root=project_root,
    )
    latency_ms = round((time.perf_counter() - _t0) * 1000)
    _record_round(
        project_root,
        ticket=ticket,
        task_type=task_type,
        rol=rol,
        profile=profile,
        backend_version=_backend_version(config["backends"][profile["backend"]]),
        ronda=ronda,
        reply=reply,
        input_bytes=len(content.encode("utf-8")),
        context_kind=context_kind,
        session_id=session_id,
        latency_ms=latency_ms,
        phase=phase,
        loop_id=loop_id,
        backend_key=backend_key,
        commit_sha=commit_sha,
        challenge_nonce=challenge_nonce,
    )
    return reply


def run_pipeline(
    pipeline_name: str,
    *,
    config: dict,
    project_root: Path,
    ticket: str,
    task_type: str,
    payload: str,
    sensitivity: str,
    context_kind: str = "diff",
    transport=None,
    max_rounds: int | None = None,
    session_id: str | None = None,
) -> list[dict]:
    """Ejecuta un bucle proposer/challenger. ROUND 0 = premise_check SIEMPRE.

    Before: `task_type` debe pertenecer a `TASK_TYPES` (enum cerrado); es la
        UNICA puerta de validacion (D2b: gobierna el 100% de la provenance,
        `append_scorecard` no revalida).
    During: B2 (default): las respuestas de los backends se capturan como
        PROPUESTAS (retorno + scorecard); este dispatcher no aplica nada al
        arbol. Cada envio a `send_to_profile` se cronometra con
        `time.perf_counter()` (monotonico) y el delta en ms entero se
        persiste como `latency_ms` de la fila. `session_id` (opcional) se
        propaga tal cual a cada fila de ronda.
    After: retorna el transcript en memoria; `ValueError` si `task_type` es
        invalido (WOT-2026-025y, D2), listando `sorted(TASK_TYPES)`.
    """
    if task_type not in TASK_TYPES:
        raise ValueError(
            f"task_type '{task_type}' invalido; usa uno de {sorted(TASK_TYPES)}"
        )
    pipe = config["ensemble_pipelines"][pipeline_name]
    rounds_cap = int(pipe.get("max_rounds", 2))
    total_rounds = min(max_rounds or rounds_cap, rounds_cap)
    participants = (
        ("proposer", pipe["proposer"]),
        ("challenger", pipe["challenger"]),
    )
    versions = {
        rol: _backend_version(
            config["backends"][config["ensemble_profiles"][prof]["backend"]]
        )
        for rol, prof in participants
    }
    input_bytes = len(payload.encode("utf-8"))
    transcript: list[dict] = []

    # CANARY de recibos (WOT-2026-042k): observa el bundle REAL antes de que
    # llegue a las lentes -- el momento exacto en que un probe sin recibo
    # propaga una premisa falsa a las 9 lentes (HUECO-1). NO bloquea: ver el
    # contrato canary completo en `receipt_canary`.
    receipt_canary(
        payload,
        root=project_root,
        ticket=ticket,
        session_id=session_id,
    )

    # ROUND 0: premise_check -- INVARIANTE del dispatcher, no configurable.
    for rol, prof_name in participants:
        profile = config["ensemble_profiles"][prof_name]
        content = f"{PREMISE_CHECK_PREAMBLE}\n\n{payload}"
        _t0 = time.perf_counter()
        reply = send_to_profile(
            prof_name,
            [{"role": "user", "content": content}],
            config=config,
            sensitivity=sensitivity,
            transport=transport,
            project_root=project_root,
        )
        latency_ms = round((time.perf_counter() - _t0) * 1000)
        _record_round(
            project_root,
            ticket=ticket,
            task_type=task_type,
            rol=rol,
            profile=profile,
            backend_version=versions[rol],
            ronda=0,
            reply=reply,
            input_bytes=input_bytes,
            context_kind=context_kind,
            session_id=session_id,
            latency_ms=latency_ms,
        )
        transcript.append({"ronda": 0, "rol": rol, "reply": reply})

    # WOT-2026-039c: filtro de salida de lente. Clave AUSENTE = OFF = conducta
    # heredada (aditividad real: los pipelines que no la declaran no cambian).
    # Solo aplica al CHALLENGER y solo en rondas >=1: la ronda 0 es el
    # premise_check, invariante del dispatcher, cuya respuesta legitima no
    # trae bloque cite y quedaria siempre descartada.
    lens_filter_on = bool(pipe.get("lens_output_filter", False))
    filter_lens_output = _load_lens_filter() if lens_filter_on else None

    rubric = pipe.get("rubric", "")
    for ronda in range(1, total_rounds + 1):
        for rol, prof_name in participants:
            profile = config["ensemble_profiles"][prof_name]
            if rol == "proposer":
                instruction = (
                    f"Ronda {ronda} (proposer). Rubrica canonica: {rubric}. "
                    "PROPON tu analisis/patch como texto (B2: el orquestador "
                    "aplica tras diff-review; tu NO escribes ficheros)."
                )
            else:
                instruction = (
                    f"Ronda {ronda} (challenger). Rubrica canonica: {rubric}. "
                    "REFUTA la propuesta anterior con evidencia concreta; si "
                    "no hay objecion CONFIRMADA con evidencia, dilo."
                )
            prior = "\n\n".join(
                f"[{t['rol']} r{t['ronda']}]\n{t['reply']}"
                for t in transcript
                if t["reply"] and not t.get("discarded_reason")
            )
            content = f"{instruction}\n\n=== MATERIAL ===\n{payload}\n\n=== RONDAS PREVIAS ===\n{prior}"
            _t0 = time.perf_counter()
            reply = send_to_profile(
                prof_name,
                [{"role": "user", "content": content}],
                config=config,
                sensitivity=sensitivity,
                transport=transport,
                project_root=project_root,
            )
            latency_ms = round((time.perf_counter() - _t0) * 1000)

            discarded_reason = None
            if filter_lens_output is not None and rol == "challenger" and reply:
                # WOT-2026-041c: las lentes auditan artefactos del MOTOR
                # (`scripts/`, `bus/`, `prompts/`, `tests/`) mientras el runtime
                # vive en el DESTINO. Con `project_root` como UNICO root, toda
                # cita legitima al motor se descartaba como
                # `fabricated_citation` -- justo la contribucion mas valiosa (la
                # que cita codigo real), dejando pasar las respuestas vagas.
                # Los dos roots son estructuralmente distintos: como
                # `_resolve_project_root` PROHIBE `project_root == MOTOR_ROOT`,
                # la lista es cerrada, no un registro de N roots arbitrarios.
                accepted, reason, problems = filter_lens_output(
                    reply, project_root, cite_only=True, extra_roots=[MOTOR_ROOT]
                )
                if not accepted:
                    discarded_reason = reason
                    if problems:
                        discarded_reason = f"{reason}: {problems[0]}"

            _record_round(
                project_root,
                ticket=ticket,
                task_type=task_type,
                rol=rol,
                profile=profile,
                backend_version=versions[rol],
                ronda=ronda,
                reply=reply,
                input_bytes=input_bytes,
                context_kind=context_kind,
                session_id=session_id,
                latency_ms=latency_ms,
                failure_mode=discarded_reason,
                outcome_override="no-aportacion" if discarded_reason else None,
            )
            entry = {"ronda": ronda, "rol": rol, "reply": reply}
            if discarded_reason:
                # Se APPENDEA con marca (no se omite ni se vacia): el consumidor
                # conserva la salida descartada -- sin ceros hay sesgo de
                # supervivencia -- y el prior de la ronda siguiente la excluye.
                entry["discarded_reason"] = discarded_reason
            transcript.append(entry)
    return transcript


def adjudicate(
    project_root: Path,
    *,
    ticket: str,
    ronda: int,
    rol: str,
    outcome: str,
    evidence: str,
    adjudicator_backend: str | None = None,
    adjudicator_model: str | None = None,
    finding_confirmed_by: str | None = None,
    session_id: str | None = None,
    supersede: bool = False,
) -> Path:
    """Adjudicacion del TERCER rol (o veto humano via --supersede).

    Before: existe una fila `event=ronda` previa para (ticket, ronda, rol);
        `evidence` y `adjudicator_backend` son OBLIGATORIOS (idiom de
        evidence, WOT-2026-025y D4): una adjudicacion sin evidencia es
        relato y una sin adjudicador es anonima.
    During: La evidencia (comando + salida / artefacto) es OBLIGATORIA. El
        evento se APPENDEA (nunca muta filas previas) y regenera la
        proyeccion. `adjudicator_backend`/`adjudicator_model` registran QUIEN
        adjudico en columnas NUEVAS, sin tocar `backend`/`task_type`
        (siguen copiados del SOURCE: HALLAZGO 1, mover la identidad ahi
        corrompe el bucket/cell_key de `regenerate_leaders`).
        `session_id` se toma del FLAG de esta llamada, NUNCA de
        `source.get('session_id')` (es la sesion en que se ADJUDICA, no la
        de la ronda original).
    After: retorna la ruta de `backend_leaders.json` regenerado; lanza
        `ValueError` si `outcome`, `evidence` o `adjudicator_backend` son
        invalidos/ausentes, o si no existe la fila de ronda fuente.
    """
    if outcome not in ADJUDICATED_OUTCOMES:
        raise ValueError(
            f"outcome '{outcome}' invalido; usa uno de {sorted(ADJUDICATED_OUTCOMES)}"
        )
    if not evidence or not evidence.strip():
        raise ValueError(
            "adjudication_evidence es OBLIGATORIA (comando + salida o "
            "artefacto verificable); una adjudicacion sin evidencia es relato"
        )
    if not adjudicator_backend or not adjudicator_backend.strip():
        raise ValueError(
            "adjudicator_backend es OBLIGATORIO (WOT-2026-025y D4): la fila "
            "REGISTRA la identidad de quien adjudico (veto humano usa "
            "--adjudicator-backend human); una adjudicacion sin adjudicador "
            "es anonima"
        )
    rows, _sha = _read_scorecard(project_root)
    source = next(
        (
            r
            for r in reversed(rows)
            if r.get("event") == "ronda"
            and r.get("ticket") == ticket
            and r.get("ronda") == ronda
            and r.get("rol") == rol
        ),
        None,
    )
    if source is None:
        raise ValueError(
            f"no existe fila de ronda para (ticket={ticket}, ronda={ronda}, "
            f"rol={rol}): no se adjudica lo que no se registro"
        )
    append_scorecard(
        project_root,
        {
            "ts": _now_iso(),
            "event": "supersede" if supersede else "adjudicacion",
            "ticket": ticket,
            "rol": rol,
            "task_type": source.get("task_type"),
            "backend": source.get("backend"),
            "model": source.get("model"),
            "backend_version": source.get("backend_version"),
            "ronda": ronda,
            "outcome": outcome,
            "finding_confirmed_by": finding_confirmed_by,
            "adjudication_evidence": evidence,
            "input_bytes": source.get("input_bytes"),
            "context_kind": source.get("context_kind"),
            "session_id": session_id,
            "adjudicator_backend": adjudicator_backend,
            "adjudicator_model": adjudicator_model,
        },
    )
    return regenerate_leaders(project_root)


def _cmd_smoke(args, config) -> int:
    names = (
        [args.profile] if args.profile else sorted(config.get("ensemble_profiles", {}))
    )
    results = [smoke_profile(name, config=config) for name in names]
    print(json.dumps({"smoke": results}, ensure_ascii=False, indent=2))
    alive = sum(1 for r in results if r["alive"])
    print(
        f"[smoke] {alive}/{len(results)} backends vivos (veredicto por "
        "CONTENIDO, no por exit code)",
        file=sys.stderr,
    )
    return 0 if alive else 1


def _cmd_run(args, config) -> int:
    project_root = _resolve_project_root(args.project_root)
    # WOT-2026-027s CAPA 1: la allowlist decide ANTES de leer. Fail-closed con
    # la MISMA semantica que la barrera ya existente en `send_to_profile`
    # (DispatchBlockedError antes de tocar red); no se introduce una tercera
    # semantica tipo skip-con-warn. Mutation: sin este bloque, un payload de
    # cualquier ruta entra al pipeline.
    payload_path = Path(args.payload_file)
    allowed, reason = payload_read_allowed(
        payload_path, config.get("ensemble_payload_allowlist", [])
    )
    if not allowed:
        raise DispatchBlockedError(f"lectura de payload BLOQUEADA: {reason}")
    payload = payload_path.read_text(encoding="utf-8")
    transcript = run_pipeline(
        args.pipeline,
        config=config,
        project_root=project_root,
        ticket=args.ticket,
        task_type=args.task_type,
        payload=payload,
        sensitivity=args.data_sensitivity,
        context_kind=args.context_kind,
        max_rounds=args.max_rounds,
        session_id=args.session_id,
    )
    print(json.dumps({"transcript": transcript}, ensure_ascii=False, indent=2))
    return 0


def _cmd_loop_round(args, config) -> int:
    """UNA ronda de un bucle de GOBIERNO por CLI (WOT-2026-043z).

    `run_loop_round` existia y propagaba los 4 campos que lee la barrera
    (WOT-2026-026q) pero no tenia puerta: los bucles `1->9->2` la importaban a
    mano, asi que ninguna ruta DOCUMENTADA dejaba un bucle atestiguable. Este
    subcomando es esa puerta -- nada mas. NO toca `run_pipeline`: su ronda 0 es
    `premise_check` (INVARIANTE) y su trafico de smoke no debe contar como
    ronda de gobierno (:1465-1469).

    UNA invocacion = UNA ronda = UN `backend_key`. El fan-out de N lentes son N
    invocaciones: es lo que hace que el recuento de claves DISTINTAS de
    `check_loop_execution` sea significativo en vez de decorativo.

    Before: `--content-file` pasa la allowlist de payload (misma barrera que
        `run`); `--project-root` es el destino-rol, nunca el motor.
    During: delega en `run_loop_round`, que despacha via `send_to_profile`
        (preflight de privacidad fail-closed) y APPENDEA exactamente UNA fila.
    After: imprime la respuesta del backend tal cual (el consolidador es el
        chat, nivel 0) y retorna 0. Propaga `DispatchBlockedError` /
        `ValueError` a `main`, que los mapea a exit != 0.
    """
    project_root = _resolve_project_root(args.project_root)
    content_path = Path(args.content_file)

    # PROTOCOLO DE BUNDLE (2026-08-05): avisa ANTES de gastar la ronda si el
    # encargo no declara sus invariantes de suficiencia.
    #
    # Medido con la MISMA lente (BA06), el MISMO cwd y ficheros del MISMO repo:
    # bundle SIN protocolo -> 106 bytes sin veredicto; CON protocolo -> 4708 y
    # un informe completo. Una lente muda es indistinguible de una que no
    # encontro nada, asi que el fallo NO es ruidoso: por eso se avisa aqui.
    #
    # WARN y NO bloqueo, a proposito: el guard verifica FORMA (que los
    # invariantes esten declarados), no que sean CIERTOS. Bloquear con un
    # detector de cadenas obligaria a escribir las palabras magicas y
    # convertiria el protocolo en cargo cult. El aviso llega cuando aun es
    # barato corregir; la decision sigue siendo del operador.
    if content_path.is_file():
        try:
            from scripts.check_loop_bundle_protocol import check_bundle

            _missing = check_bundle(
                content_path.read_text(encoding="utf-8", errors="replace")
            )
            if _missing:
                print(
                    f"[loop-bundle] WARN: el bundle no declara {len(_missing)} "
                    f"invariante(s) del protocolo: {', '.join(_missing)}. "
                    "Medido: una lente sin protocolo devolvio 106 bytes; con el, 4708.",
                    file=sys.stderr,
                )
        except Exception as exc:  # un aviso NUNCA rompe el despacho
            # Se REPORTA en vez de tragarse: un `except: pass` silencioso es el
            # mismo modo de fallo que este guard existe para cazar (algo que
            # calla es indistinguible de algo que no encontro nada).
            print(f"[loop-bundle] aviso no disponible: {exc}", file=sys.stderr)
    # WOT-2026-048i: un error de USO deja RASTRO, no solo un stderr.
    #
    # El exit code YA era correcto (`main` mapea ValueError -> 1) y NO se toca:
    # ese es el NON-GOAL de la ficha. Lo que faltaba es la FILA. Sin ella, el
    # scorecard no distingue "nadie consulto a esta lente" de "la invocacion
    # estaba mal escrita", y un consolidador que cuente filas para acreditar N
    # lentes distintas cuenta de menos SIN sintoma.
    #
    # POR QUE AQUI Y NO EN `run_loop_round`: alli la validacion de `task_type`
    # (`:1749`) corre ANTES de resolver `profile` (`:1753`), y `_record_round`
    # EXIGE un `profile` dict. En este handler el perfil SI es resoluble desde
    # la config, asi que la fila puede ser ATRIBUIBLE (ticket, loop_id,
    # backend_key) en vez de un registro huerfano.
    #
    # Se registra y se RE-LANZA: el contrato de `main` sigue mapeando el
    # ValueError a exit 1. La fila es aditiva, no sustituye al fallo.
    if args.task_type not in TASK_TYPES:
        profile = (config.get("ensemble_profiles") or {}).get(args.profile)
        if profile is not None:
            _record_round(
                project_root,
                ticket=args.ticket,
                task_type=args.task_type,
                rol=args.rol,
                profile=profile,
                backend_version=None,
                ronda=args.ronda,
                reply="",
                input_bytes=0,
                context_kind=args.context_kind,
                failure_mode="usage-error",
                session_id=args.session_id,
                phase=args.phase,
                loop_id=args.loop_id,
                backend_key=args.backend_key,
                commit_sha=args.commit_sha,
                challenge_nonce=args.challenge_nonce,
            )
        raise ValueError(
            f"task_type '{args.task_type}' invalido; usa uno de {sorted(TASK_TYPES)}"
        )
    allowed, reason = payload_read_allowed(
        content_path, config.get("ensemble_payload_allowlist", [])
    )
    if not allowed:
        raise DispatchBlockedError(f"lectura de payload BLOQUEADA: {reason}")
    content = content_path.read_text(encoding="utf-8")
    # WOT-2026-048x: una ronda que muere por el TRANSPORTE no dejaba NINGUNA
    # fila, asi que en el scorecard "nadie consulto a esta lente" y "la lente no
    # llego a responder" eran indistinguibles -- y el silencio se lee como
    # acuerdo. Medido 2026-08-11 en los bucles L1100/L1102 de esta misma sesion:
    # 12 rondas lanzadas, 8 registradas; las 4 caidas (HTTP 524) no dejaron
    # rastro. La cobertura efectiva de un bucle era INCOMPUTABLE desde su propio
    # artefacto.
    #
    # POR QUE AQUI Y NO EN `run_loop_round`: identica razon que el pre-check de
    # `task_type` de mas arriba (WOT-2026-048i) -- `_record_round` EXIGE un
    # `profile` dict, y en este handler el perfil SI es resoluble desde la
    # config, asi que la fila queda ATRIBUIBLE (ticket, loop_id, backend_key) en
    # vez de ser un registro huerfano.
    #
    # POR QUE `_record_round` NO BASTABA: ya clasifica `transport_failed`
    # (`:1651`), pero solo cuando el transporte DEVUELVE texto marcado con
    # `_TRANSPORT_FAILED_PREFIX` -- la ruta del canal `agent` (`:1022`). El canal
    # `api` LANZA `TransportError` (`:640-673`), que sube por encima de
    # `_record_round` y nunca llega a escribir. Ese es el hueco exacto, y es el
    # que cerro este ticket.
    #
    # `DispatchBlockedError` se EXCLUYE a proposito: el docstring de
    # `run_loop_round` declara que un bloqueo del preflight de privacidad NO deja
    # fila "porque no hubo ronda", y eso es correcto -- el payload nunca salio.
    # Registrarlo aqui inventaria una ronda que no existio.
    #
    # Se registra y se RE-LANZA: `main` sigue mapeando la excepcion a su exit
    # code (2 para las de transporte). La fila es ADITIVA, no sustituye al fallo.
    try:
        reply = run_loop_round(
            args.profile,
            content,
            config=config,
            project_root=project_root,
            ticket=args.ticket,
            task_type=args.task_type,
            rol=args.rol,
            phase=args.phase,
            loop_id=args.loop_id,
            backend_key=args.backend_key,
            sensitivity=args.data_sensitivity,
            ronda=args.ronda,
            context_kind=args.context_kind,
            session_id=args.session_id,
            commit_sha=args.commit_sha,
            challenge_nonce=args.challenge_nonce,
        )
    except DispatchBlockedError:
        raise
    except Exception as exc:
        # La captura es ANCHA a proposito (no perder NINGUNA fila), pero la
        # ETIQUETA es PRECISA. Adjudicado por el bucle L1104, donde dos lentes
        # chocaron y las dos tenian razon sobre cosas distintas: el lector-FS
        # defendio la anchura ("el hueco era exactamente ese: excepciones
        # inesperadas que subian sin rastro") y BA14 ataco la etiqueta ("si
        # `run_loop_round` lanza un KeyError, el fix lo registra como
        # `transport_failed` y la fila de auditoria queda mintiendo").
        #
        # Clasificar mal es PEOR que no registrar en un ticket cuyo proposito es
        # hacer el registro fiable: un `transport_failed` falso manda a buscar
        # una caida de red donde hay un bug de programacion.
        clase = (
            "transport_failed"
            if isinstance(exc, (TransportError, OSError))
            else "unexpected"
        )
        profile = (config.get("ensemble_profiles") or {}).get(args.profile)
        if profile is not None:
            _record_round(
                project_root,
                ticket=args.ticket,
                task_type=args.task_type,
                rol=args.rol,
                profile=profile,
                backend_version=None,
                ronda=args.ronda,
                reply="",
                input_bytes=len(content.encode("utf-8")),
                context_kind=args.context_kind,
                failure_mode=f"{clase}: {type(exc).__name__}: {exc}"[:300],
                session_id=args.session_id,
                phase=args.phase,
                loop_id=args.loop_id,
                backend_key=args.backend_key,
                commit_sha=args.commit_sha,
                challenge_nonce=args.challenge_nonce,
            )
        raise
    print(reply)
    return 0


def _cmd_adjudicate(args, config) -> int:
    project_root = _resolve_project_root(args.project_root)
    out_path = adjudicate(
        project_root,
        ticket=args.ticket,
        ronda=args.ronda,
        rol=args.rol,
        outcome=args.outcome,
        evidence=args.evidence,
        adjudicator_backend=args.adjudicator_backend,
        adjudicator_model=args.adjudicator_model,
        finding_confirmed_by=args.finding_confirmed_by,
        session_id=args.session_id,
        supersede=args.supersede,
    )
    print(f"[adjudicate] evento registrado; proyeccion regenerada: {out_path}")
    return 0


def _cmd_leaders(args, config) -> int:
    project_root = _resolve_project_root(args.project_root)
    out_path = regenerate_leaders(project_root)
    print(f"[leaders] proyeccion regenerada: {out_path}")
    return 0


# WOT-2026-059c: markers de stderr (MEDIDOS 2026-08-25 sobre git del motor real)
# que clasifican un `git rev-parse --verify <sha>^{commit}` fallido como INVALIDO
# ("el sha no resuelve a un commit") frente a UNKNOWN ("no pude comprobar"):
#   - "fatal: Needed a single revision"      <- sha inexistente o abbrev irresoluble
#   - "expected commit type, but the object" <- objeto existe pero no es commit
#   - "unknown revision" / "not a valid object name" / "ambiguous argument"
# Un rc != 0 SIN estos markers es infraestructura (repos danado, config rota):
# la doctrina de WOT-2026-059b es "un git que no arranca es DESCONOCIDO, no
# INVALIDO", y reportarlo como "no existe" es falso-rojo con causa falsa.
_INVALID_SHA_MARKERS = (
    "needed a single revision",
    "unknown revision",
    "not a valid object name",
    "ambiguous argument",
    "expected commit type",
)


def _canonical_motor_commit_sha(motor_root: Path, commit_sha: str) -> tuple[bool, str]:
    """WOT-2026-059c: resuelve y normaliza un --commit-sha contra el MOTOR.

    Before: `motor_root` es un repo git (resuelto del link del destino);
        `commit_sha` es la forma que el CLI recibio (puede ser abreviada).
    During: una lectura `git rev-parse --verify <sha>^{commit}` contra el motor
        (timeout 10s). Sin escrituras.
    After: (True, sha40 pleno) si el sha resuelve a un commit; (False, razon)
        si no. La razon distingue INVALIDO (markers medidos) de UNKNOWN
        (infraestructura: OSError/SubprocessError, o rc sin markers) -- nunca
        un fallo de git se reporta como "el sha no existe".
    """
    try:
        probe = subprocess.run(
            [  # noqa: S607 - git es el binario canonico del motor
                "git",
                "-C",
                str(motor_root),
                "rev-parse",
                "--verify",
                f"{commit_sha}^{{commit}}",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"UNKNOWN: git no pudo ejecutarse contra el motor ({exc})"
    if probe.returncode == 0:
        return True, probe.stdout.strip()
    err = (probe.stderr or "").lower()
    if any(marker in err for marker in _INVALID_SHA_MARKERS):
        return False, f"'{commit_sha}' no resuelve a un commit del motor"
    return False, (
        f"UNKNOWN: no pude comprobar '{commit_sha}' contra el motor (git "
        f"rc={probe.returncode}: {(probe.stderr or '').strip()[:120]})"
    )


def _cmd_emit_nonce(args, config) -> int:
    project_root = _resolve_project_root(args.project_root)
    # WOT-2026-059c: el emisor NUNCA registra un sha que el motor no puede
    # resolver (la contraparte productiva de la barrera de WOT-2026-059b que ya
    # falla cerrado en prepush). La validacion vive AQUI, en la unica ruta
    # productiva hacia el ledger: `emit_nonce()` es primitiva interna del estilo
    # `append_scorecard` (grep verificado: solo `_cmd_emit_nonce` la invoca en
    # produccion; los tests de join existentes la usan con shas sinteticos).
    try:
        from runtime.motor_link import resolve_motor_root
    except ImportError:  # pragma: no cover - ruta de import alternativa
        from runtime.motor_link import (  # type: ignore[no-redef]
            resolve_motor_root,
        )
    motor_root = resolve_motor_root(project_root)
    if motor_root is None:
        raise ValueError(
            f"emit-nonce bloqueado (WOT-2026-059c): no pude comprobar "
            f"'{args.commit_sha}' -- sin motor_destination_link.json valido para "
            f"{project_root} (UNKNOWN, no INVALIDO)"
        )
    ok, canonical_or_reason = _canonical_motor_commit_sha(motor_root, args.commit_sha)
    if not ok:
        raise ValueError(f"emit-nonce bloqueado (WOT-2026-059c): {canonical_or_reason}")
    canonical_sha = canonical_or_reason
    if canonical_sha != args.commit_sha:
        print(
            f"[emit-nonce] sha normalizado: {args.commit_sha} -> {canonical_sha}",
            file=sys.stderr,
        )
    nonce, out_path = emit_nonce(
        project_root,
        commit_sha=canonical_sha,
        loop_id=args.loop_id,
        issuer_role=args.issuer_role,
        issuer_backend_key=args.issuer_backend_key,
        nonce=args.nonce,
    )
    # El nonce va a stdout para que el orquestador lo pase al fan-out; la fila
    # ya quedo registrada en emitted_nonces.jsonl (la prueba de la ceremonia).
    print(nonce)
    print(f"[emit-nonce] registrado en {out_path}", file=sys.stderr)
    return 0


def _force_utf8_stdio() -> None:
    """Fuerza UTF-8 en los streams del PROPIO proceso (WOT-2026-054j).

    Before: `sys.stdout`/`sys.stderr` son los que herede el proceso. En Windows
        eso es `cp1252` (medido en esta maquina: `sys.stdout.encoding` ->
        `cp1252`, `locale.getpreferredencoding()` -> `cp1252`).
    During: reconfigura ambos a UTF-8 si el stream lo soporta. No toca red, no
        escribe, no lee configuracion.
    After: cualquier `print` posterior admite el repertorio Unicode completo.
        Idempotente y sin efecto observable cuando el stream ya es UTF-8.

    POR QUE AQUI Y NO EN EL ENTORNO DEL LLAMANTE: el DoD original pedia
    `PYTHONIOENCODING=utf-8` en el entorno del subproceso, lo que deja el
    arreglo en manos de QUIEN INVOCA. Este repo distingue NORMA de BARRERA
    CABLEADA, y una norma "depende de que alguien se acuerde": basta un
    llamante que no exporte la variable para perder la ronda. La reconfiguracion
    DENTRO del proceso que falla es la barrera, y ademas cubre los TRES puntos
    de impresion afectados (`:2084` smoke, `:2120` transcript, `:2245` reply),
    no solo el que la ficha nombraba. `PYTHONIOENCODING` sigue siendo valido y
    complementario: esta cableado para los SUBPROCESOS en
    `bus/subprocess_env.py` (`_BASE_ALLOWLIST`).

    `errors="backslashreplace"` es DEFENSA EN PROFUNDIDAD DECLARADA, no la
    correccion de una violacion probada: con `encoding="utf-8"` el parametro es
    practicamente inerte porque UTF-8 codifica cualquier codepoint. Importa solo
    si el stream NO es reconfigurable y queda en cp1252; entonces
    `backslashreplace` deja `\\u2192` -- legible y reversible -- en vez del `?`
    que produciria `replace`, que es justo la "question-mark corruption" que
    persigue `scripts/check_encoding_guard.py`.

    La guarda `hasattr` NO es decorativa: bajo captura de pytest `sys.stdout` es
    un objeto tipo `io.StringIO`, que carece de `reconfigure` (verificado).
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="backslashreplace")


def main(argv: list[str] | None = None) -> int:
    _force_utf8_stdio()
    parser = argparse.ArgumentParser(
        description="Ensemble dispatcher (WOT-2026-019o): proposer/challenger "
        "multi-backend con scorecard adjudicado."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_smoke = sub.add_parser("smoke", help="round-trip por contenido")
    p_smoke.add_argument("--profile", help="perfil concreto (default: todos)")

    p_run = sub.add_parser("run", help="ejecuta un pipeline")
    p_run.add_argument("--pipeline", required=True)
    p_run.add_argument("--ticket", required=True)
    p_run.add_argument("--task-type", required=True)
    p_run.add_argument("--payload-file", required=True)
    p_run.add_argument(
        "--data-sensitivity",
        required=True,
        choices=["public", "private", "secret"],
    )
    p_run.add_argument("--context-kind", default="diff")
    p_run.add_argument("--max-rounds", type=int, default=None)
    p_run.add_argument("--project-root", required=True)
    p_run.add_argument(
        "--session-id",
        default=None,
        help="sesion scratch opcional (D5: legitimo correr fuera de una)",
    )

    p_loop = sub.add_parser(
        "loop-round",
        help="UNA ronda de un bucle de gobierno 1->9->2, registrada y atestiguable",
    )
    p_loop.add_argument("--profile", required=True)
    p_loop.add_argument("--content-file", required=True)
    p_loop.add_argument("--ticket", required=True)
    p_loop.add_argument("--task-type", required=True)
    p_loop.add_argument("--rol", required=True, choices=["proposer", "challenger"])
    p_loop.add_argument(
        "--phase", required=True, help="etapa de gobierno (CONTRACT_AUDIT, ...)"
    )
    p_loop.add_argument(
        "--loop-id", required=True, help="registro citable del bucle (Lxxxx)"
    )
    p_loop.add_argument(
        "--backend-key",
        required=True,
        help="clave del backend de ESTA ronda; la barrera cuenta claves DISTINTAS",
    )
    p_loop.add_argument(
        "--data-sensitivity",
        required=True,
        choices=["public", "private", "secret"],
    )
    p_loop.add_argument("--ronda", type=int, default=1)
    p_loop.add_argument("--context-kind", default="diff")
    p_loop.add_argument(
        "--commit-sha", default=None, help="commit bajo review (WOT-2026-040b)"
    )
    p_loop.add_argument(
        "--challenge-nonce",
        default=None,
        help="nonce emitido FUERA por `emit-nonce`, ANTES de esta ronda",
    )
    p_loop.add_argument("--session-id", default=None)
    p_loop.add_argument("--project-root", required=True)

    p_adj = sub.add_parser("adjudicate", help="adjudicar outcome de una ronda")
    p_adj.add_argument("--ticket", required=True)
    p_adj.add_argument("--ronda", type=int, required=True)
    p_adj.add_argument("--rol", required=True, choices=["proposer", "challenger"])
    p_adj.add_argument("--outcome", required=True)
    p_adj.add_argument("--evidence", required=True)
    p_adj.add_argument(
        "--adjudicator-backend",
        required=True,
        help="identidad de quien adjudico (OBLIGATORIO, D4); veto humano usa 'human'",
    )
    p_adj.add_argument("--adjudicator-model", default=None)
    p_adj.add_argument("--finding-confirmed-by", default=None)
    p_adj.add_argument(
        "--session-id",
        default=None,
        help="sesion en la que se ADJUDICA (nunca la del source)",
    )
    p_adj.add_argument(
        "--supersede",
        action="store_true",
        help="veto humano: evento supersede (nunca mutacion de filas)",
    )
    p_adj.add_argument("--project-root", required=True)

    p_lead = sub.add_parser("leaders", help="regenerar backend_leaders.json")
    p_lead.add_argument("--project-root", required=True)

    p_nonce = sub.add_parser(
        "emit-nonce",
        help="emitir un challenge_nonce ANTES de un fan-out de gobierno (WOT-2026-040b)",
    )
    p_nonce.add_argument("--commit-sha", required=True)
    p_nonce.add_argument("--loop-id", required=True, help="p.ej. L700 / L800")
    p_nonce.add_argument(
        "--issuer-role",
        default="orchestrator",
        help="rol que emite (NO cuenta como lente ejecutora para N)",
    )
    p_nonce.add_argument(
        "--issuer-backend-key",
        required=True,
        help="backend_key del emisor (excluido del recuento de N lentes distintas)",
    )
    p_nonce.add_argument(
        "--nonce",
        default=None,
        help="nonce explicito (default: aleatorio); util para tests reproducibles",
    )
    p_nonce.add_argument("--project-root", required=True)

    args = parser.parse_args(argv)
    config = load_motor_config()

    handlers = {
        "smoke": _cmd_smoke,
        "run": _cmd_run,
        "loop-round": _cmd_loop_round,
        "adjudicate": _cmd_adjudicate,
        "leaders": _cmd_leaders,
        "emit-nonce": _cmd_emit_nonce,
    }
    try:
        return handlers[args.command](args, config)
    except (DispatchBlockedError, ValueError) as exc:
        print(f"[BLOCKED] {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"[ERROR] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
