#!/usr/bin/env python3
r"""Barrera de EJECUCION del bucle de gobierno 1->9->2 (WOT-2026-040b).

El problema que cierra (medido DOS veces)
-----------------------------------------
El bucle adversarial `1->9->2` (CONTRACT_AUDIT, MANAGER_REVIEW, CLOSE) vivia SOLO
en un prompt (`orchestrator_autonomous_ticket_batch.md`): texto que el ejecutor
debe ACORDARSE de honrar. Medido 2026-07-23: un ejecutor commiteo DOS tickets sin
correr el bucle y NINGUN gate lo detuvo -- lo cazo el usuario. 2a ocurrencia
2026-07-24, PEOR: el bucle SI corrio pero DEGRADADO -- 8 instancias del MISMO
modelo en vez de 4 perfiles x 2 ramas. Cero rastro verificable. Es el patron que
AGENTS.md llama "barrera cableada vs norma": una norma depende de que alguien se
acuerde; una barrera corre sola.

Que verifica (y que NO)
-----------------------
Por cada `commit_sha` de ticket que se le pasa, este guard exige en el scorecard
`>=N` receipts de EJECUCION (`event=="ronda"`) de ese SHA con `backend_key`
DISTINTO, un `challenge_nonce` que fue EMITIDO FUERA del ejecutor
(`emitted_nonces.jsonl`) ANTES de la ronda, y CONTENIDO en la respuesta. `N` es
proporcional al `deliverable_type` (un typo/doc no exige 9 lentes).

CONTAR POR INSTANCIA (C', DEC-bucle-doc-001)
--------------------------------------------
"N lentes distintas" significa N lentes en la MISMA corrida. Las rondas validas
de un sha se agrupan por `challenge_nonce` (cada nonce emitido fuera identifica
UNA corrida); el commit pasa sii ALGUNA instancia alcanza N con lentes
sustantivas, y las instancias que no llegan se NOMBRAN en el veredicto
(`per_nonce`), como ya se hacia con las mudas. Defecto que cierra (medido
2026-09-07): L730/L731/L732 comparten `c54b9deb...` y su UNION sumaba `4/4` sin
que ninguna corrida llegara sola a N -- el guard fusionaba fan-outs distintos.
Ademas, una ronda cuyo nonce no fue emitido para este commit se reporta en
`fabricated_rounds` (antes se descartaba con un `continue` mudo), y `loop-round`
rechaza un nonce ya usado con otro sha u otro `loop_id` (los 3 casos sucios de
la DEC).

SUSTANCIA, no solo independencia (WOT-2026-043q)
------------------------------------------------
`WOT-2026-040b` cerro la INDEPENDENCIA (N `backend_key` distintos) pero no la
SUSTANCIA: una lente que NO RESPONDE y una que RESPONDE VACIO eran
INDISTINGUIBLES para esta barrera -- ninguna condicion exigia contenido, asi que
N backends devolviendo cero bytes contaban como bucle EJECUTADO y el guard daba
rc=0. Ahora una ronda muda no cuenta como lente (`is_substantive`) y ademas se
NOMBRA en la salida, distinguiendo TRANSPORTE (no hubo llamada) de BACKEND (hubo
llamada y respondio vacio), porque exigen accion distinta.

El caso real que lo origino: un `service_tier` global invalido mataba a codex-cli
SIN emitir veredicto y SIN consumir tokens -- no llegaba a haber llamada-- y el
bucle se contabilizaba igual.

Adjudicado por el propio bucle 1->9->2 sobre esta cuestion de diseño (Codex final,
2026-07-24):
- El vector que MUERDE de verdad es "bucle DEGRADADO" (N llamadas al mismo modelo):
  lo cierra el recuento de `backend_key` DISTINTOS, no el nonce. El nonce es
  SECUNDARIO -- fuerza una ceremonia previa auditable y evita que el scorecard
  parezca evidencia sin challenge emitido.
- La independencia es OPERACIONAL, no criptografica: en dogfooding el mismo agente
  puede emitir y ejecutar. Por eso NO probamos "otro actor"; probamos "paso previo
  separado, no derivable de los receipts". El `issuer_backend_key` del emisor NO
  cuenta como lente ejecutora para satisfacer N, y la emision debe ser ANTERIOR a
  los receipts (`issued_before_ts < receipt.ts`).
- Se EXIGE el join DUAL: nonce emitido fuera Y copiado dentro de cada receipt. Si
  viviera solo fuera, el join por commit probaria que hubo UN nonce, no que cada
  backend respondio a ESE challenge.

NON-GOALS (STOP de degeneracion, WOT-2026-024u/025c honrado en vivo)
--------------------------------------------------------------------
Este guard NO juzga la CALIDAD semantica del review (imposible sin oraculo, es
025f-shaped). NO descubre por su cuenta que commits pertenecen al vuelo ni deriva
N adivinando: recibe `commit_sha` y `min_distinct_backends` como ENTRADAS. NO
tokeniza prosa ni analiza invocaciones. Es un CONTADOR estructural con un join,
nada mas: por eso cabe entero y no degenera en un subsistema.

Rechazos explicitos (fail-closed)
---------------------------------
- Una fila con `event != "ronda"` (p.ej. `adjudicate`) NO cuenta como ejecucion:
  `adjudicate` appendea campos controlados por CLI (`--evidence`,
  `--adjudicator-backend`), es fabricable a mano. Solo `event=="ronda"` -- que
  escribe `_record_round` tras un `send_to_profile` real-- prueba ejecucion.
- Un receipt cuyo `challenge_nonce` no esta en `emitted_nonces.jsonl` (para ese
  commit+loop) se DESCARTA: es un nonce fabricado.
- Un receipt cuyo nonce se emitio DESPUES de la ronda se descarta (la ceremonia
  previa no ocurrio).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


MOTOR_ROOT = Path(__file__).resolve().parent.parent
if str(MOTOR_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(MOTOR_ROOT / "scripts"))

from ensemble_dispatch import (  # noqa: E402
    _read_scorecard,
    load_motor_config,
    read_emitted_nonces,
    resolve_governed_commit_sha,
)


# N minimo de lentes distintas por deliverable_type. El 1->9->2 canonico son 9
# lentes (4 perfiles x 2 ramas + 1 lector-FS) pero como MUCHO 6 backend_key
# DISTINTOS (BA01,BA05,BA10-13). Exigir 9 backends distintos parte de premisa
# falsa (solo hay 6): el minimo real de INDEPENDENCIA es "no todo el mismo
# modelo". Rigor proporcional: un typo no exige la ceremonia completa.
DEFAULT_MIN_DISTINCT_BACKENDS = {
    "code": 4,
    "mixed": 4,
    "analysis": 3,
    "research": 2,
    "documentation": 2,
}
# Fallback conservador cuando el deliverable_type es desconocido: el mas estricto.
FALLBACK_MIN_DISTINCT = 4


def min_distinct_for(deliverable_type: str | None) -> int:
    """N minimo de backend_key distintos para un deliverable_type.

    Un tipo desconocido cae al fallback ESTRICTO (fail-closed): mejor exigir de
    mas y que el orquestador declare el tipo, que colar un bucle degradado.
    """
    if not deliverable_type:
        return FALLBACK_MIN_DISTINCT
    return DEFAULT_MIN_DISTINCT_BACKENDS.get(
        deliverable_type.strip().lower(), FALLBACK_MIN_DISTINCT
    )


# WOT-2026-143a (opcion B del usuario, 2026-10-30): el bucle se exige por TICKET
# sobre su ultimo commit (el escritor de objetivos emite solo ese). Estos 15 SHA
# son el ultimo commit de tickets del vuelo vuelo-20261026b que se integraron SIN
# bucle de >=N lentes: DEUDA HISTORICA declarada por SHA40 EXACTO (igualdad, nunca
# prefijo ni patron) con su ficha como criterio de salida (el valor). Un SHA que no
# este aqui y quede bajo el minimo sigue FALLANDO. Una entrada sale de aqui cuando
# su ficha la salda con un bucle real; reescribir historia invalida la entrada
# (remapear con scripts/remap_evidence_shas.py).
HISTORIC_LOOP_DEBT: dict[str, str] = {
    "10f1f2f69612445bcc1dbdcc403423844a01d126": "WOT-2026-143b",  # 125b
    "43f973f22c97ead0f725a91e2ec50c4d77659c05": "WOT-2026-143b",  # 125c
    "6e8d0e5c1a2049ba72e42874de65f9ba8912af25": "WOT-2026-143b",  # 129b
    "8c30c2c02131103fede8ef9347b9b91826a21663": "WOT-2026-143b",  # 129l
    "4979505062ff26f64ea70771510a69c2a1ce5460": "WOT-2026-143b",  # 129u
    "484f5bb1285c3c638ba0e5292bb93996320555d8": "WOT-2026-143b",  # 129y
    "024306127b2d8fa41d6c17e907a7130c95f565ae": "WOT-2026-143b",  # 131a
    "4760368e37c57d7e000f4a8309eeb3caece4d511": "WOT-2026-143b",  # 136a
    "c16cdb505ddb6013d40f9fce3be35f6974771731": "WOT-2026-143b",  # 136b
    "2785da27ada9e6c2db7b3b91753947cfb198c07c": "WOT-2026-143b",  # 136c
    "00a01d848ee2805ef0d9030395cef6f09ca55e45": "WOT-2026-143b",  # 136d
    "749e8eb8c16704006c7552fa8f484f36745afabb": "WOT-2026-143b",  # 136e
    "63ddd2a0484897cbe30e57f7c1c41f432452e1e8": "WOT-2026-143b",  # 136f
    "83cd618c378579a0d91fd901ab7137617193db6a": "WOT-2026-143b",  # 136g
    "bb9cb51890c6d3756f50010d50a7d280b93b2bc9": "WOT-2026-143b",  # 136j
}


def historic_debt_ficha(commit_sha: str) -> str | None:
    """Ficha de salida si `commit_sha` es deuda historica DECLARADA, si no None.

    Before: `commit_sha` es el sha tal cual lo declara el objetivo.
    During: igualdad EXACTA contra `HISTORIC_LOOP_DEBT` (un sha abreviado o con
        el mismo prefijo NO casa: fail-closed).
    After: el valor (ficha) o None. Sin I/O.
    """
    return HISTORIC_LOOP_DEBT.get(commit_sha)


# WOT-2026-129y: cobertura elegible DECLARADA (fuente unica, D1 del
# work_plan). La fuente es `agents.json::ensemble_registry.eligible_coverage`,
# campo versionado del motor, NO el roster del vuelo (externo no versionado;
# ver D1 por el motivo completo). El roster sigue siendo la expectativa de
# sesion; este gate no lo lee.
COVERAGE_POLICIES = frozenset({"declared", "strict"})
COVERAGE_SOURCE_LABEL = "agents.json::ensemble_registry.eligible_coverage"


def _coverage_key(phase: str | None, delivery_authority: str | None) -> str | None:
    """Clave ``"<PHASE>:<DELIVERY_AUTHORITY>"``; None => sin cobertura (legacy)."""
    if not phase or not delivery_authority:
        return None
    return f"{phase}:{delivery_authority}"


def _validate_coverage_keys(entry: dict, config: dict) -> str | None:
    """Parte de claves de ``validate_coverage_entry`` (backend_keys + excluded).

    Before: entry ya sabido que es dict.
    During: valida tipo/contenido de ``backend_keys`` (strings no vacios, sin
        duplicados, todas en ``ensemble_registry.backend_keys``) y la forma de
        ``excluded_backend_keys`` sin solape.
    After: reason ``invalid_coverage: ...`` o None.
    """
    backend_keys = entry.get("backend_keys")
    if not isinstance(backend_keys, list) or not backend_keys:
        return "invalid_coverage: backend_keys ausente o vacio"
    if any(not isinstance(k, str) or not k.strip() for k in backend_keys):
        return "invalid_coverage: backend_keys contiene valores que no son strings no vacios"
    if len(set(backend_keys)) != len(backend_keys):
        return "invalid_coverage: backend_keys con duplicados"
    registry = (config.get("ensemble_registry") or {}).get("backend_keys") or {}
    unknown = sorted(k for k in backend_keys if k not in registry)
    if unknown:
        return (
            "invalid_coverage: claves ausentes de "
            f"ensemble_registry.backend_keys: {unknown}"
        )
    excluded = entry.get("excluded_backend_keys") or []
    if not isinstance(excluded, list) or any(not isinstance(k, str) for k in excluded):
        return "invalid_coverage: excluded_backend_keys debe ser lista de strings"
    both = sorted(set(backend_keys) & set(excluded))
    if both:
        return f"invalid_coverage: claves a la vez elegibles y excluidas: {both}"
    return None


def validate_coverage_entry(entry: object, config: dict) -> str | None:
    """Valida la DECLARACION de una entrada de cobertura (D2, fail-closed).

    Before: ``entry`` es el valor declarado en
        ``ensemble_registry.eligible_coverage[key]``; ``config`` el motor
        config cargado (para contrastar con ``ensemble_registry.backend_keys``).
    During: valida las claves via ``_validate_coverage_keys`` y despues
        ``policy`` en {declared, strict} (default strict), ``min_distinct``
        entero en [2, len(backend_keys)] y ``exempt_tickets`` opcional de
        strings.
    After: None si la declaracion es valida; si no, un reason ``invalid_*``
        que el veredicto publica (nunca se degrada a legacy en silencio).
    """
    if not isinstance(entry, dict):
        return "invalid_coverage: la entrada no es un objeto JSON"
    keys_reason = _validate_coverage_keys(entry, config)
    if keys_reason is not None:
        return keys_reason
    policy = entry.get("policy", "strict")
    if policy not in COVERAGE_POLICIES:
        return f"invalid_coverage: policy {policy!r} fuera de declared|strict"
    min_distinct = entry.get("min_distinct")
    if isinstance(min_distinct, bool) or not isinstance(min_distinct, int):
        return "invalid_coverage: min_distinct debe ser un entero"
    backend_keys = entry.get("backend_keys") or []
    if min_distinct < 2 or min_distinct > len(backend_keys):
        return (
            f"invalid_coverage: min_distinct {min_distinct} fuera de "
            f"[2, {len(backend_keys)}]"
        )
    exempt = entry.get("exempt_tickets") or []
    if not isinstance(exempt, list) or any(not isinstance(t, str) for t in exempt):
        return "invalid_coverage: exempt_tickets debe ser lista de strings"
    return None


def load_eligible_coverage(
    config: dict, phase: str | None, delivery_authority: str | None
) -> tuple[dict | None, str | None, str | None]:
    """Carga y valida la entrada de cobertura para (fase, delivery_authority).

    Before: ``config`` ya cargado; phase/authority vienen del caller (CLI o
        audit; sin AMBOS no hay cobertura -> camino legacy intacto).
    During: busca ``ensemble_registry.eligible_coverage["<PHASE>:<AUTHORITY>"]``
        y lo pasa por ``validate_coverage_entry``.
    After: ``(entry, None, key)`` valida; ``(None, None, None)`` sin cobertura
        declarada (legacy); ``(None, reason, key)`` declarada pero INVALIDA
        (fail-closed: el veredicto publica el reason, no degrada).
    """
    key = _coverage_key(phase, delivery_authority)
    if key is None:
        return None, None, None
    registry = config.get("ensemble_registry") or {}
    coverage = registry.get("eligible_coverage")
    if not isinstance(coverage, dict) or key not in coverage:
        return None, None, None
    entry = coverage[key]
    reason = validate_coverage_entry(entry, config)
    if reason is not None:
        return None, reason, key
    return entry, None, key  # type: ignore[return-value]


def effective_eligible(
    entry: dict, config: dict
) -> tuple[set[str], list[dict[str, str]]]:
    """Elegibles efectivos de una entrada VALIDA y las declaradas retiradas (D3).

    Before: ``entry`` paso ``validate_coverage_entry`` (D2 garantiza
        ``backend_keys`` disjuntas de ``excluded_backend_keys``).
    During: elegible = cada ``backend_keys`` cuyo registry ``status`` sea
        ``active``; una declaracion vencida (status deprecated/archived) NO
        cuenta aunque siga en la lista. Las ``excluded_backend_keys`` son
        disjuntas por validacion: su efecto es dar reason ``excluded`` a las
        RONDAS de esas claves (ver ``apply_eligible_reasons``), no remover
        declaradas.
    After: ``(elegibles, removed)`` con ``removed`` =
        ``[{backend_key, reason: retired(status=...)}]``.
    """
    registry = config["ensemble_registry"]["backend_keys"]
    eligible: set[str] = set()
    removed: list[dict[str, str]] = []
    for key in entry["backend_keys"]:
        status = (registry.get(key) or {}).get("status")
        if status != "active":
            removed.append({"backend_key": key, "reason": f"retired(status={status})"})
            continue
        eligible.add(key)
    return eligible, removed


def apply_eligible_reasons(
    entry: dict, removed: list[dict[str, str]]
) -> dict[str, str]:
    """Mapa backend_key -> reason para rondas que NO cuentan (D3).

    Before: entrada valida (disjuncion D2 ya garantizada) + ``removed`` de
        ``effective_eligible``.
    During: prioridad ``retired(status=...)`` (declarada vencida) sobre
        ``excluded`` (declarada prohibida para esta clave, p. ej. BA05 por
        WOT-2026-129r); lo demas cae a ``not_in_eligible_set`` en el caller.
    After: dict lookup por clave.
    """
    reasons = {r["backend_key"]: r["reason"] for r in removed}
    for key in entry.get("excluded_backend_keys") or []:
        reasons.setdefault(key, "excluded")
    return reasons


def apply_eligibility(
    verdict: dict, eligible: set[str], reason_map: dict[str, str]
) -> dict:
    """Filtra el veredicto a las claves ELEGIBLES (D3) sin tocar audit_commit.

    Before: ``verdict`` recien devuelto por ``audit_commit`` con
        ``min_distinct`` = minimo YA aplicado; ``eligible`` de
        ``effective_eligible``; ``reason_map`` de ``apply_eligible_reasons``.
    During: por cada instancia (nonce) separa backends elegibles de los que
        corrieron pero no cuentan (reason: ``reason_map`` si la conoce, si no
        ``not_in_eligible_set``); recalcula ``distinct`` e ``ok`` POR
        INSTANCIA (C' intacto) y la union diagnosticable.
    After: mismo dict mutado con ``distinct_backends`` filtrado,
        ``not_eligible_backends``, ``declared_removed`` y ``ok`` recalculado.
    """
    seen: dict[str, str] = {}
    for entry in verdict.get("per_nonce", []):
        keep: list[str] = []
        for bk in entry.get("backends", []):
            if bk in eligible:
                keep.append(bk)
            else:
                seen.setdefault(bk, reason_map.get(bk, "not_in_eligible_set"))
        entry["ineligible"] = [
            bk for bk in entry.get("backends", []) if bk not in eligible
        ]
        entry["backends"] = keep
        entry["distinct"] = len(keep)
        entry["ok"] = len(keep) >= verdict["min_distinct"]
    verdict["distinct_backends"] = [
        bk for bk in verdict.get("distinct_backends", []) if bk in eligible
    ]
    verdict["not_eligible_backends"] = [
        {"backend_key": k, "reason": r} for k, r in sorted(seen.items())
    ]
    verdict["ok"] = any(entry.get("ok") for entry in verdict.get("per_nonce", []))
    return verdict


def _apply_declared_policy(
    plan: dict,
    entry: dict,
    min_distinct: int | None,
    coverage_key: str,
    *,
    phase: str | None,
    delivery_authority: str | None,
) -> None:
    """policy=declared: minimo aplicado = el declarado, con piso 2 (DoD 3).

    Before: plan/base ya inicializado; entry valida con policy declared.
    During: sin override -> aplica el declarado (origen eligible_coverage);
        override < declarado -> BLOQUEO (D5: no invalida el minimo derivado);
        override >= declarado -> se aplica (mas estricto, origen cli-override).
    After: plan mutado (applied_min, min_origen, block_reason).
    """
    declared_min = max(2, int(entry["min_distinct"]))
    if min_distinct is None:
        plan["applied_min"] = declared_min
        plan["min_origen"] = "eligible_coverage"
        return
    if min_distinct < declared_min:
        plan["applied_min"] = declared_min
        plan["min_origen"] = "eligible_coverage"
        plan["block_reason"] = (
            f"override_below_declared_min: --min-distinct {min_distinct} < "
            f"minimo declarado {declared_min} de {coverage_key} "
            f"({COVERAGE_SOURCE_LABEL}); el override no puede invalidar el "
            f"minimo derivado (fase={phase}, delivery_authority="
            f"{delivery_authority}, WOT-2026-129y D5)"
        )
        return
    plan["applied_min"] = min_distinct
    plan["min_origen"] = "cli-override"


def _apply_strict_policy(
    plan: dict,
    eligible: set[str],
    min_distinct: int | None,
    policy_min: int,
    coverage_key: str,
    *,
    phase: str | None,
    deliverable_type: str | None,
) -> None:
    """policy=strict: minimo = policy(deliverable); elegibles < policy -> DoD 2.

    Before: plan/base inicializado; eligible ya calculado.
    During: si la cobertura declarada tiene MENOS claves elegibles que las que
        el contrato exige -> ``contrato_inalcanzable`` ANTES de mirar rondas
        (fase, tipo, cobertura, elegibles y minimo nombrados; sin union de
        nonces ni precedentes: la unica exencion es la lista declarada).
    After: plan mutado (block_reason cuando el contrato es inalcanzable).
    """
    if len(eligible) < policy_min:
        plan["block_reason"] = (
            f"contrato_inalcanzable: fase={phase} "
            f"tipo={deliverable_type or 'desconocido'} "
            f"cobertura={COVERAGE_SOURCE_LABEL} clave={coverage_key} "
            f"elegibles={sorted(eligible)} minimo_exigido={policy_min}; "
            "el contrato exige mas claves que las elegibles (conteo por "
            "nonce/instancia, sin union ni reutilizacion de precedentes)"
        )


def _coverage_plan(
    *,
    coverage_entry: dict | None,
    coverage_reason: str | None,
    coverage_key: str | None,
    exempt: bool,
    cfg: dict | None,
    phase: str | None,
    delivery_authority: str | None,
    deliverable_type: str | None,
    min_distinct: int | None,
    policy_min: int,
) -> dict:
    """Resuelve el minimo a aplicar y el motivo de bloqueo de UN commit (D4-D6).

    Before: cobertura ya cargada (o None), exempt ya calculado por ticket,
        cfg cargado cuando hubo fase+authority.
    During: orden: declaracion invalida -> bloqueo; sin cobertura o ticket
        EXENTO -> plan legacy (policy/cli, piso absoluto 2, sin filtro);
        policy declared -> minimo declarado con reglas de override (D5);
        policy strict -> policy(deliverable) + DoD 2 si elegibles < policy.
    After: dict {applied_min, min_origen, block_reason, eligible, removed,
        override_below_policy}.
    """
    plan: dict = {
        "applied_min": min_distinct if min_distinct is not None else policy_min,
        "min_origen": "cli-override" if min_distinct is not None else "policy",
        "block_reason": None,
        "eligible": None,
        "removed": [],
        "override_below_policy": min_distinct is not None and min_distinct < policy_min,
    }
    if plan["applied_min"] < 2:
        # Piso absoluto de independencia (D5): el override nunca baja de 2.
        plan["applied_min"] = 2
    if coverage_reason is not None:
        plan["block_reason"] = coverage_reason
        return plan
    if coverage_entry is None or coverage_key is None or exempt or cfg is None:
        return plan
    eligible, removed = effective_eligible(coverage_entry, cfg)
    plan["eligible"] = eligible
    plan["removed"] = removed
    if coverage_entry.get("policy", "strict") == "declared":
        _apply_declared_policy(
            plan,
            coverage_entry,
            min_distinct,
            coverage_key,
            phase=phase,
            delivery_authority=delivery_authority,
        )
    else:
        _apply_strict_policy(
            plan,
            eligible,
            min_distinct,
            policy_min,
            coverage_key,
            phase=phase,
            deliverable_type=deliverable_type,
        )
    return plan


# Marcador que `_record_round` escribe en `evidencia` cuando el backend no
# devolvio texto. Es el observable HISTORICO de una ronda muda: existe en el
# scorecard desde antes de `output_chars`, y por eso el criterio lo acepta como
# senal equivalente en filas antiguas.
EMPTY_EVIDENCIA_MARKER = "(respuesta vacia)"

# Invisibles Unicode que `str.strip()` NO elimina y que, solos, no son una
# aportacion: zero-width space/non-joiner/joiner, BOM/zero-width no-break y el
# espacio ideografico. No es un umbral de longitud (ver `is_substantive`): es la
# misma nocion de "vacio" que ya aplica `_record_round`, extendida a los
# caracteres que su `.strip()` deja pasar.
_INVISIBLE_CHARS = "".join(
    (
        # escapes, no literales: en el fuente son indistinguibles de un espacio
        # normal y ruff los marca como ambiguos (RUF001).
        chr(0x200B),  # zero-width space
        chr(0x200C),  # zero-width non-joiner
        chr(0x200D),  # zero-width joiner
        chr(0xFEFF),  # zero-width no-break space (BOM)
        chr(0x3000),  # ideographic space
        chr(0x00A0),  # no-break space
    )
)


def is_substantive(row: dict) -> bool:
    """True sii la ronda APORTO contenido. Falso sii corrio y callo.

    DESVIACION DECLARADA DEL DoD (b) de WOT-2026-043q. El DoD pedia "umbral =
    constante declarada, justificada con BARRIDO sobre el scorecard REAL,
    publicando AMBOS bordes de la meseta". **Aqui NO hay umbral de longitud, y la
    desviacion es deliberada**: el barrido se hizo y REFUTO la premisa del DoD.
    `evidencia` -- el unico campo de tamano que existia-- se guarda truncada a 500
    caracteres (249 de 472 rondas historicas caen EXACTAMENTE en el tope) y una
    respuesta sustantiva almacenada fuera de linea ocupa ~46 caracteres
    ("raw/router__lectura__dif__qwen3.6.json (2134c)"): cualquier umbral sobre ese
    campo marcaria muda una ronda de 2134 caracteres, un falso positivo POR
    CONSTRUCCION. Por eso se anadio `output_chars` (medida EXACTA) y el criterio
    es `== 0`, que es una MEDICION, no una constante ajustable a ojo.

    LIMITE CONOCIDO de esa decision (declarado, no descubierto luego): una
    respuesta de RUIDO no vacia ("ok", "si") cuenta como sustantiva. Filtrar eso
    es juzgar CALIDAD SEMANTICA, que es competencia del adjudicador
    (`failure_mode`, que este criterio ya respeta) y que en el gate reproduciria
    el muro de WOT-2026-025c. Si algun dia se quiere un `MIN_OUTPUT_CHARS`, ahora
    SI hay con que barrerlo: `output_chars` empieza a acumular datos desde este
    ticket -- antes no existia el dato, asi que el barrido pedido por el DoD era
    literalmente imposible sobre el historico.

    Criterio (fail-OPEN ante ausencia de dato, a proposito):
    - `output_chars == 0` -> muda.
    - `outcome == "no-aportacion"` -> muda (lo deriva `_record_round` desde el
      texto vacio, y tambien lo fija el filtro de lente).
    - `evidencia == "(respuesta vacia)"` -> muda.
    - Sin ninguna de esas senales -> SUSTANTIVA.

    La ultima clausula es el anti-falso-positivo: las filas anteriores a este
    ticket no llevan `output_chars`, y tratar "campo ausente" como muda
    invalidaria RETROACTIVAMENTE bucles ya corridos -- un gate que hace eso es
    inservible y se le rodea (leccion WOT-2026-042x). Medido sobre el scorecard
    real ANTES de endurecer: de 16 commits con fan-out, solo 2 pierden una lente
    (5990486: 5->4, ea02701: 7->6) y NINGUNO cae por debajo de su min_distinct.
    Por eso este ticket NO necesita constante de cutoff: no hay deuda historica
    que grandfatherear.
    """
    if row.get("output_chars") == 0:
        return False
    if row.get("outcome") == "no-aportacion":
        return False
    evidencia = row.get("evidencia") or ""
    if evidencia.strip() == EMPTY_EVIDENCIA_MARKER:
        return False
    # Respuesta INVISIBLE: `_record_round` mide sobre `text.strip()`, que deja
    # fuera espacios y saltos (una respuesta de solo blancos ya llega con
    # output_chars=0), pero `str.strip()` NO quita los invisibles Unicode --
    # un zero-width space sigue midiendo 1. Sin esto, un backend que devuelve un
    # invisible cuenta como lente que aporta.
    #
    # Solo se aplica cuando la fila TIENE texto: una `evidencia` ausente o vacia
    # es una fila legacy sin ese campo, y tratarla como muda invertiria el
    # fail-OPEN de arriba (lo pinea `test_legacy_rows_without_output_chars_stay_substantive`).
    visible = evidencia.strip(_INVISIBLE_CHARS).strip()
    return bool(visible) or not evidencia.strip()


def diagnose_silence(row: dict) -> str:
    """Por que callo esta ronda, y donde NO hay que buscar.

    ACTUALIZADO (WOT-2026-046h, 2026-09-27): la premisa original de esta
    funcion ("un fallo de transporte NO deja fila, `run_loop_round` no
    captura excepciones") DEJO DE SER CIERTA a proposito. Medido en vivo
    2026-09-26: 4 llamadas con HTTP 402 (cuota agotada) no dejaron NINGUNA
    fila -- indistinguible de "nadie lo intento" -- y ese hueco (real, no
    solo en `_cmd_loop_round`/WOT-2026-048x, sino tambien en la ruta Python
    directa que usan los bucles de gobierno por chat) se cerro: ahora
    `run_loop_round` registra ANTES de re-lanzar, con `failure_mode`
    clasificado (`transport_failed` vs `unexpected`, adjudicado en L1104).

    ALCANCE REAL, re-medido tras el fix: una ronda muda SIN `failure_mode` es
    "hubo llamada y la respuesta llego vacia" (la rama de abajo). Una ronda
    con `failure_mode` poblado por un fallo de TRANSPORTE ahora SI aparece
    aqui -- la rama `if failure_mode:` de mas abajo ya la cubre correctamente,
    porque esa rama nunca asumio nada sobre EL ORIGEN del failure_mode, solo
    que la adjudicacion (en sentido amplio: el propio registrador) ya
    clasifico la ronda. Lo que SIGUE sin dejar fila es `DispatchBlockedError`
    (el preflight de privacidad bloqueo ANTES de tocar red: no hubo ronda) --
    ese caso se observa en la AUSENCIA de fila, cosa del recuento de lentes
    (`min_distinct`), no de este diagnostico.
    """
    failure_mode = (row.get("failure_mode") or "").strip()
    if failure_mode:
        # La adjudicacion (o el registrador, tras WOT-2026-046h) ya clasifico
        # esta ronda; su etiqueta manda sobre cualquier inferencia nuestra.
        return f"respuesta descartada por la adjudicacion: {failure_mode}"
    return (
        "hubo llamada y la respuesta llego VACIA: revisa el BACKEND o el bundle "
        "enviado (tamano, formato). Un rechazo del preflight de privacidad "
        "(DispatchBlockedError) no deja fila: se manifiesta como lente "
        "AUSENTE del recuento, no como ronda muda"
    )


def _valid_nonces_for(
    emitted: list[dict], commit_sha: str, loop_id: str | None
) -> dict[str, str]:
    """nonce -> issued_before_ts, para las emisiones de este commit (y loop si se da).

    Solo las emisiones cuyo `commit_sha` casa cuentan: un nonce emitido para OTRO
    commit no autoriza este. Si se pasa `loop_id`, tambien debe casar (un nonce de
    L700 no vale para L800).

    WOT-2026-067i -- POR QUE NO SE FILTRA POR `resolved_against`, habiendolo:
    el ledger registra contra que raiz se resolvio el sha (motor o destino), y el
    DoD inicial de 067i pedia CONTRASTARLO aqui. Se implemento y se RETIRO al
    medir que no aporta: el casado es por **sha40**, que identifica un objeto git
    UNIVOCO. Si dos raices contienen ese mismo sha40 es el MISMO commit (historia
    compartida), asi que ninguna acreditacion cruzada es posible. El riesgo real
    era la ABREVIATURA que resuelve a objetos DISTINTOS en cada raiz, y esa la
    cierra `resolve_governed_commit_sha` en origen con su rama `AMBIGUO` -- antes
    de que ningun sha llegue al ledger. Filtrar aqui habria exigido propagar la
    raiz por CINCO firmas para una comprobacion vacua: es el STOP de degeneracion
    de AGENTS.md, no una omision. El campo se conserva como TRAZA auditable (que
    raiz acredito cada nonce), que es su valor real.
    """
    valid: dict[str, str] = {}
    for row in emitted:
        if row.get("commit_sha") != commit_sha:
            continue
        if loop_id is not None and row.get("loop_id") not in (None, loop_id):
            continue
        nonce = row.get("challenge_nonce")
        ts = row.get("issued_before_ts") or row.get("ts")
        if nonce and ts:
            # si el mismo nonce se emitio varias veces, quedarse con el mas TEMPRANO
            prev = valid.get(nonce)
            if prev is None or ts < prev:
                valid[nonce] = ts
    return valid


def distinct_execution_backends(
    scorecard_rows: list[dict],
    emitted: list[dict],
    *,
    commit_sha: str,
    loop_id: str | None = None,
) -> set[str]:
    """Conjunto de `backend_key` DISTINTOS que ejecutaron una ronda VALIDA de este
    commit. Una ronda es valida sii:

      - `event == "ronda"` (no `adjudicate` ni cualquier otro evento);
      - su `commit_sha` casa (el receipt declara para que commit corrio);
      - lleva un `backend_key` no vacio;
      - su `challenge_nonce` fue emitido FUERA para este commit (y loop, si se da);
      - la emision del nonce es ANTERIOR a la ronda (`issued_before_ts <= ronda.ts`).

    EXCLUSION DEL EMISOR (criterio adjudicado por Codex): el `issuer_backend_key`
    no cuenta como lente ejecutora para N. En dogfooding el mismo backend (BA01 =
    Claude) emite el nonce Y es la lente lector-FS -- SI ejecuta una ronda-- pero
    contarlo inflaria N con una independencia que no existe: quien conoce el
    challenge de antemano no es una lente ciega. Descontamos todos los emisores de
    este commit. Devolver el CONJUNTO (no el conteo) deja que el caller reporte
    QUIENES corrieron.
    """
    return {
        row.get("backend_key")
        for row in structurally_valid_rounds(
            scorecard_rows, emitted, commit_sha=commit_sha, loop_id=loop_id
        )
        if is_substantive(row)
    }


def structurally_valid_rounds(
    scorecard_rows: list[dict],
    emitted: list[dict],
    *,
    commit_sha: str,
    loop_id: str | None = None,
) -> list[dict]:
    """Rondas que pasan todos los filtros ESTRUCTURALES, sin mirar el contenido.

    Es la pasada UNICA que comparten el recuento de lentes y el listado de mudas
    (WOT-2026-043q): la sustancia es el ULTIMO filtro y el unico que las separa,
    asi que duplicar aqui la cadena de filtros haria que las dos vistas
    divergieran en cuanto alguien tocara una sola.
    """
    valid_nonces = _valid_nonces_for(emitted, commit_sha, loop_id)
    issuers = {
        row.get("issuer_backend_key")
        for row in emitted
        if row.get("commit_sha") == commit_sha and row.get("issuer_backend_key")
    }
    rounds: list[dict] = []
    for row in scorecard_rows:
        if row.get("event") != "ronda":
            continue
        # WOT-2026-055o: DEFENSA EN PROFUNDIDAD contra el trafico EXPLORATORIO
        # (smoke/preflight/llamadas ad-hoc), que a partir de este ticket SI
        # deja fila en el scorecard con event="ronda". El filtro de nonce de
        # abajo ya impide que una fila exploratoria NORMAL cuente (no lleva
        # `challenge_nonce`), pero solo eso dejaba el riesgo en cero por
        # AUSENCIA: si algun caller exploratorio reutilizara por error un
        # commit_sha+challenge_nonce de un bucle de gobierno real, la fila
        # SI colaria y contaria para la barrera de independencia. Aqui se
        # excluye POR TIPO, antes (no en vez de) del filtro de nonce.
        if row.get("task_type") == "exploracion":
            continue
        if row.get("commit_sha") != commit_sha:
            continue
        bk = row.get("backend_key")
        nonce = row.get("challenge_nonce")
        if not bk or not nonce:
            continue
        if bk in issuers:
            continue  # el emisor no es una lente independiente del challenge
        emitted_ts = valid_nonces.get(nonce)
        if emitted_ts is None:
            continue  # nonce no emitido para este commit: fabricado
        row_ts = row.get("ts")
        if row_ts is not None and emitted_ts > row_ts:
            continue  # el nonce se emitio DESPUES de la ronda: sin ceremonia previa
        rounds.append(row)
    return rounds


# WOT-2026-044l: el join commit+nonce+backend_key (arriba) prueba EJECUCION,
# no que la ronda auditara el bundle correcto -- un commit citado por bucles
# sobre OTRA cosa (medido 2026-08-11: 17 citas, 0 legitimas) pasaba esa barrera
# igual. Las dos funciones siguientes son ADITIVAS (diagnostico, no bloqueo):
# el guard de independencia (`distinct_execution_backends`) y sus NON-GOALS
# declarados ("no bloquear WOT-2026-044d con esto") no cambian.
def bundle_sha256_groups(
    scorecard_rows: list[dict],
    emitted: list[dict],
    *,
    commit_sha: str,
    loop_id: str | None = None,
) -> dict[str | None, list[dict]]:
    """Agrupa las rondas ESTRUCTURALMENTE validas de `commit_sha` por `bundle_sha256`.

    WOT-2026-044l (DoD b): el guard que COMPARA `bundle_sha256`. Una ronda
    estructuralmente valida (nonce+commit+backend_key correctos) puede haber
    auditado un bundle DISTINTO si el commit_sha fue citado por error -- o por
    inercia -- desde OTRO bucle, sobre OTRO material. Agrupar por bundle_sha256
    separa esas citas ajenas del grupo que de verdad comparte bundle.

    Before: `scorecard_rows`/`emitted` son las filas ya leidas (`_read_scorecard`,
        `read_emitted_nonces`).
    During: reusa `structurally_valid_rounds` (MISMA pasada que el recuento de
        independencia, para no divergir si alguien toca un solo filtro) y agrupa
        por `row.get("bundle_sha256")`. Una fila sin el campo (legacy, o ronda
        que fallo antes de leer el bundle) agrupa bajo la clave `None`.
    After: mapa `bundle_sha256 -> [rows]`. El grupo con MAS filas es el
        candidato a "bucle legitimo sobre este commit"; los demas son citas que
        el join commit+nonce no puede distinguir por si solo.
    """
    rounds = structurally_valid_rounds(
        scorecard_rows, emitted, commit_sha=commit_sha, loop_id=loop_id
    )
    groups: dict[str | None, list[dict]] = {}
    for row in rounds:
        groups.setdefault(row.get("bundle_sha256"), []).append(row)
    return groups


def foreign_bundle_rounds(
    scorecard_rows: list[dict],
    emitted: list[dict],
    *,
    commit_sha: str,
    loop_id: str | None = None,
) -> list[dict]:
    """Rondas estructuralmente validas de `commit_sha` que NO comparten el
    `bundle_sha256` mayoritario (WOT-2026-044l, DoD b/d).

    Una ronda aqui es indistinguible de una auditoria legitima por
    commit+nonce+backend_key, pero audito un CONTENIDO distinto -- la firma
    medida del caso real: tres bucles sobre OTRA cosa que pasaron el mismo
    `--commit-sha` por inercia, sin que nadie mirara el diff de ese commit.

    Before: igual que `bundle_sha256_groups`.
    During: el grupo con MAS filas se toma como el bundle legitimo (empate ->
        el primero por orden de aparicion, estable); el resto se reporta.
    After: lista de filas foraneas (vacia si todas comparten bundle, o si solo
        hay un grupo con hash). Filas sin `bundle_sha256` (`None`) NUNCA se
        reportan como foraneas: la AUSENCIA de dato no es evidencia de
        contenido distinto (fail-closed hacia el silencio, no hacia la
        acusacion).
    """
    groups = bundle_sha256_groups(
        scorecard_rows, emitted, commit_sha=commit_sha, loop_id=loop_id
    )
    populated = {k: v for k, v in groups.items() if k is not None}
    if len(populated) <= 1:
        return []
    majority_hash = max(populated, key=lambda h: len(populated[h]))
    return [row for h, rows in populated.items() if h != majority_hash for row in rows]


# WOT-2026-044l DoD (f): criterio DECLARADO EN CONTRATO (prompts/ensemble_loop.md
# Seccion 4) de que constituye "auditar" un commit -- distinto de "ejecutar una
# ronda estructuralmente valida" (arriba). Es el criterio que el propio AUDITADO
# eligio al reconstruir este ticket a mano; sin declararlo, un guard corregido
# seguiria dependiendo de que cada orquestador acierte con la definicion.
AUDIT_PHASES = frozenset({"CONTRACT_AUDIT", "MANAGER_REVIEW"})


def auditing_rounds_for_commit(
    scorecard_rows: list[dict],
    *,
    commit_sha: str,
    commit_owner_ticket: str,
) -> list[dict]:
    """Rondas que cumplen la definicion contractual de "auditar" un commit.

    Criterio (WOT-2026-044l DoD f): `ticket == dueno del commit` AND `phase in
    {CONTRACT_AUDIT, MANAGER_REVIEW}` AND `output_chars > 0`.

    Before: `scorecard_rows` ya leidas; `commit_owner_ticket` es el ticket DUENO
        del commit (quien lo genero), no necesariamente el de la fila.
    During: filtro puro de 3 condiciones sobre `event == "ronda"`. NO reusa
        `structurally_valid_rounds` (ese filtro certifica EJECUCION -- nonce,
        backend_key, commit -- no AUDITORIA del commit concreto; un bucle
        legitimo sobre OTRO objeto pasa esa barrera igual).
    After: lista de filas que cumplen el criterio; vacia si ninguna.
    """
    return [
        row
        for row in scorecard_rows
        if row.get("event") == "ronda"
        and row.get("commit_sha") == commit_sha
        and row.get("ticket") == commit_owner_ticket
        and str(row.get("phase") or "").upper().replace("-", "_") in AUDIT_PHASES
        and (row.get("output_chars") or 0) > 0
    ]


def silent_rounds(
    scorecard_rows: list[dict],
    emitted: list[dict],
    *,
    commit_sha: str,
    loop_id: str | None = None,
) -> list[dict]:
    """Rondas estructuralmente validas que NO aportaron contenido: corrieron y callaron.

    Son exactamente las que `distinct_execution_backends` descarta por
    `is_substantive`. Se devuelven aparte para que el CLI pueda NOMBRARLAS: un gate
    que dice "4/4" sin decir quien callo obliga a re-medir a mano, y "conte a mano"
    no es barrera.
    """
    return [
        {
            "backend_key": row.get("backend_key"),
            "diagnosis": diagnose_silence(row),
            "outcome": row.get("outcome"),
            "failure_mode": row.get("failure_mode"),
            "output_chars": row.get("output_chars"),
        }
        for row in structurally_valid_rounds(
            scorecard_rows, emitted, commit_sha=commit_sha, loop_id=loop_id
        )
        if not is_substantive(row)
    ]


def orphan_nonces(
    scorecard_rows: list[dict],
    emitted: list[dict],
    *,
    commit_sha: str,
    loop_id: str | None = None,
) -> list[dict]:
    """Nonces emitted for this commit that have NO corresponding scorecard rounds.

    WOT-2026-044p (b): distinguishes "no nonce emitted" (no loop happened) from
    "nonce emitted without rounds" (loop happened and was lost). An orphan nonce
    means the loop was DECLARED but never ACCREDITED -- the worst case, because
    work was done and lost without detection.

    Returns a list of dicts with nonce, loop_id, and issued_before_ts for each
    orphan. Empty list means all emitted nonces have at least one round.
    """
    valid_nonces = _valid_nonces_for(emitted, commit_sha, loop_id)
    if not valid_nonces:
        return []

    # Collect all nonces that appear in structurally valid rounds
    rounds_with_nonce: set[str] = set()
    for row in structurally_valid_rounds(
        scorecard_rows, emitted, commit_sha=commit_sha, loop_id=loop_id
    ):
        nonce = row.get("challenge_nonce")
        if nonce:
            rounds_with_nonce.add(nonce)

    orphans = []
    for nonce, ts in valid_nonces.items():
        if nonce not in rounds_with_nonce:
            # Find the loop_id from the emitted record
            emitted_loop = None
            for row in emitted:
                if row.get("challenge_nonce") == nonce:
                    emitted_loop = row.get("loop_id")
                    break
            orphans.append(
                {
                    "nonce": nonce,
                    "loop_id": emitted_loop,
                    "issued_before_ts": ts,
                    "diagnosis": (
                        "nonce emitido sin rondas: el bucle fue DECLARADO pero nunca "
                        "ACREDITADO -- el trabajo se perdio sin deteccion"
                    ),
                }
            )
    return orphans


def nonce_fanouts(
    scorecard_rows: list[dict],
    emitted: list[dict],
    *,
    commit_sha: str,
    loop_id: str | None = None,
) -> dict[str, set[str]]:
    """nonce -> conjunto de `backend_key` sustantivos de ESA corrida (C').

    Cada nonce emitido fuera identifica UNA corrida del bucle; agrupar por el
    es lo que hace que "N lentes distintas" signifique N lentes en la MISMA
    corrida y no la suma de corridas distintas (DEC-bucle-doc-001). Solo
    participan las rondas estructuralmente validas y SUSTANTIVAS: es la misma
    poblacion que cuenta `distinct_execution_backends`, partiendola por
    instancia en vez de sumarla.
    """
    fanouts: dict[str, set[str]] = {}
    for row in structurally_valid_rounds(
        scorecard_rows, emitted, commit_sha=commit_sha, loop_id=loop_id
    ):
        if not is_substantive(row):
            continue
        # structurally_valid_rounds ya exige nonce y backend_key no vacios
        fanouts.setdefault(row["challenge_nonce"], set()).add(row["backend_key"])
    return fanouts


def fabricated_nonce_rounds(
    scorecard_rows: list[dict],
    emitted: list[dict],
    *,
    commit_sha: str,
    loop_id: str | None = None,
) -> list[dict]:
    """Rondas que SOLO fallan por su nonce: no fue emitido para este commit.

    Hoy `structurally_valid_rounds` las descarta con un `continue` MUDO y el
    veredicto dice `0/4` sin decir por que. Se NOMBRAN (mismo criterio ya
    aplicado a las mudas en WOT-2026-043q): un contador sin nombres obliga a
    re-medir a mano. Un receipt cuyo nonce no esta en el ledger para este
    commit (y loop, si se da) es un nonce fabricado.

    WOT-2026-086f (correccion): filtra tambien las filas del scorecard por
    `loop_id` (no solo el ledger de `emitted_nonces`). Sin este filtro, rondas
    legitimas de OTRO bucle sobre el mismo sha salen marcadas FABRICADO (203 shas
    afectados medidos).
    """
    valid_nonces = _valid_nonces_for(emitted, commit_sha, loop_id)
    issuers = {
        row.get("issuer_backend_key")
        for row in emitted
        if row.get("commit_sha") == commit_sha and row.get("issuer_backend_key")
    }
    fabricated: list[dict] = []
    for row in scorecard_rows:
        if row.get("event") != "ronda":
            continue
        if row.get("commit_sha") != commit_sha:
            continue
        # WOT-2026-086f: filtrar por loop_id tambien en scorecard
        if loop_id is not None and row.get("loop_id") not in (None, loop_id):
            continue
        bk = row.get("backend_key")
        nonce = row.get("challenge_nonce")
        if not bk or not nonce or bk in issuers:
            continue  # esas exclusiones NO son por el nonce: no se reportan aqui
        if nonce in valid_nonces:
            continue
        fabricated.append(
            {
                "backend_key": bk,
                "nonce": nonce,
                "reason": (
                    "nonce no emitido para este commit (y loop, si se da): "
                    "receipt descartado como fabricado"
                ),
            }
        )
    return fabricated


def audit_commit(
    scorecard_rows: list[dict],
    emitted: list[dict],
    *,
    commit_sha: str,
    min_distinct: int,
    loop_id: str | None = None,
) -> dict:
    """Veredicto para UN commit: {commit_sha, distinct_backends, min_distinct, ok}.

    C' (DEC-bucle-doc-001): `ok` es True sii ALGUNA INSTANCIA (challenge_nonce)
    alcanza `min_distinct` con lentes sustantivas; las instancias que no llegan
    quedan nombradas en `per_nonce`. `distinct_backends` (la union) se sigue
    reportando para diagnostico, pero ya no decide: la union de dos corridas
    de 2 lentes no prueba independencia.

    El commit_sha se compara por prefijo NO: se exige match exacto del campo
    `commit_sha` que el receipt declara (la ENTRADA CLI se normaliza en
    `resolve_input_commit_sha`; S1B item 1).
    """
    backends = distinct_execution_backends(
        scorecard_rows, emitted, commit_sha=commit_sha, loop_id=loop_id
    )
    fanouts = nonce_fanouts(
        scorecard_rows, emitted, commit_sha=commit_sha, loop_id=loop_id
    )
    per_nonce = [
        {
            "nonce": nonce,
            "backends": sorted(instancia),
            "distinct": len(instancia),
            "ok": len(instancia) >= min_distinct,
        }
        for nonce, instancia in sorted(fanouts.items())
    ]
    return {
        "commit_sha": commit_sha,
        "distinct_backends": sorted(backends),
        "min_distinct": min_distinct,
        # C' (DEC-bucle-doc-001): decide la INSTANCIA, no la union.
        "ok": any(entry["ok"] for entry in per_nonce),
        # Instancias por nonce, con las que no llegan a N NOMBRADAS.
        "per_nonce": per_nonce,
        # WOT-2026-043q: rondas que corrieron y callaron. Se reportan SIEMPRE
        # (tambien en verde): una lente muda es una senal aunque el resto alcance
        # el minimo.
        "silent_rounds": silent_rounds(
            scorecard_rows, emitted, commit_sha=commit_sha, loop_id=loop_id
        ),
        # WOT-2026-044p (b): nonces emitidos sin rondas (bucle declarado pero
        # no acreditado). Se reportan SIEMPRE: es la peor senal porque el
        # trabajo se perdio sin deteccion.
        "orphan_nonces": orphan_nonces(
            scorecard_rows, emitted, commit_sha=commit_sha, loop_id=loop_id
        ),
        # C': rondas descartadas por nonce no emitido, antes mudas en el
        # `continue` de structurally_valid_rounds. Se NOMBRAN siempre.
        "fabricated_rounds": fabricated_nonce_rounds(
            scorecard_rows, emitted, commit_sha=commit_sha, loop_id=loop_id
        ),
    }


def summarize_loop_groups(
    commit_shas: list[str], per_commit_loop: dict[str, str]
) -> dict[str, list[str]]:
    """WOT-2026-055p: agrupa commits de `loop_execution_targets.txt` por su
    `loop=<id>` compartido, PARA REPORTAR -- nunca para decidir acreditacion.

    Historia (DESIGN_REVIEW, 2026-10-11): una v1 de este ticket proponia un
    nonce compartido que acreditara VARIOS commits con UNA sola ronda real,
    descartada tras bucle adversarial (Codex RECHAZA, qwen3.6 APRUEBA CON
    CAMBIOS) por permitir acreditar commits SIN que ninguna lente revisara su
    contenido -- el nonce compartido conectaba un commit revisado con otros
    que no lo estaban. El `loop_id` compartido en `_parse_loop_execution_targets`
    YA ACREDITA cada commit por separado (cada uno exige su propia ronda con
    `commit_sha` exacto, intacto en `structurally_valid_rounds`); esta funcion
    SOLO agrupa el TEXTO del reporte agregado para que un humano lea "grupo
    L800: 3 commits" en vez de 3 lineas sueltas sin relacion visible.

    Before: `commit_shas` es la lista en el orden del fichero de targets;
        `per_commit_loop` es el mapeo sha->loop_id de
        `_parse_loop_execution_targets` (puede faltar un sha si no declaro
        `loop=`).
    During: agrupa preservando el orden de PRIMERA aparicion, tanto de grupos
        como de commits dentro de cada grupo. Los commits SIN `loop_id`
        declarado van bajo la clave `None` (sin agrupar, cada uno solo).
    After: `{loop_id_o_None: [shas en orden]}`. No lee disco, no decide
        ok/not-ok de ningun commit -- es puro formateo de lo ya calculado por
        `_loop_accreditation_failures`.
    """
    groups: dict[str, list[str]] = {}
    for sha in commit_shas:
        key = per_commit_loop.get(sha) or ""
        groups.setdefault(key, []).append(sha)
    return groups


def audit(
    project_root: Path,
    *,
    commit_shas: list[str],
    deliverable_type: str | None = None,
    min_distinct: int | None = None,
    loop_id: str | None = None,
    phase: str | None = None,
    delivery_authority: str | None = None,
    config: dict | None = None,
) -> list[dict]:
    """Veredicto por cada commit del vuelo, leyendo scorecard + emitted del destino.

    Before: `project_root` es el destino-rol con `.agent/runtime/ensemble/`;
        `commit_shas` son los commits de ticket a verificar (entrada, NO descubierta
        aqui). `min_distinct` gana sobre `deliverable_type` si se pasa, pero con
        cobertura declarada NO puede bajar del minimo derivado (WOT-2026-129y D5).
        `phase`+`delivery_authority` JUNTOS activan la cobertura elegible
        declarada; sin ambos, el camino es byte-legacy (prepush/cierre no cambian).
    During: lee scorecard y emitted_nonces (ambos estrictos-UTF8); por commit
        resuelve el minimo (cobertura/declared/strict/exento, D4-D6), cuenta con
        `audit_commit` y, si hay cobertura valida, filtra a las claves elegibles
        (`apply_eligibility`). Cada veredicto lleva el receipt DoD 6
        (min_aplicado/min_origen/eligible/tickets/override).
    After: lista de veredictos por commit. NO imprime ni sale; el CLI formatea.
        Sin efectos de escritura.
    """
    scorecard_rows, _sha = _read_scorecard(project_root)
    emitted = read_emitted_nonces(project_root)
    coverage_entry: dict | None = None
    coverage_reason: str | None = None
    coverage_key: str | None = None
    cfg: dict | None = None
    if phase is not None and delivery_authority is not None:
        cfg = config if config is not None else load_motor_config()
        coverage_entry, coverage_reason, coverage_key = load_eligible_coverage(
            cfg, phase, delivery_authority
        )
    verdicts: list[dict] = []
    for sha in commit_shas:
        policy_min = min_distinct_for(deliverable_type)
        rows_for_sha = [
            r
            for r in scorecard_rows
            if isinstance(r, dict) and r.get("commit_sha") == sha
        ]
        tickets = sorted(
            {
                t
                for t in (r.get("ticket") for r in rows_for_sha)
                if isinstance(t, str) and t
            }
        )
        exempt = bool(
            coverage_entry
            and (set(coverage_entry.get("exempt_tickets") or []) & set(tickets))
        )
        plan = _coverage_plan(
            coverage_entry=coverage_entry,
            coverage_reason=coverage_reason,
            coverage_key=coverage_key,
            exempt=exempt,
            cfg=cfg,
            phase=phase,
            delivery_authority=delivery_authority,
            deliverable_type=deliverable_type,
            min_distinct=min_distinct,
            policy_min=policy_min,
        )
        verdict = audit_commit(
            scorecard_rows,
            emitted,
            commit_sha=sha,
            min_distinct=plan["applied_min"],
            loop_id=loop_id,
        )
        if plan["eligible"] is not None:
            reason_map = apply_eligible_reasons(coverage_entry or {}, plan["removed"])
            apply_eligibility(verdict, plan["eligible"], reason_map)
        if plan["block_reason"] is not None:
            verdict["ok"] = False
            verdict["coverage_error"] = plan["block_reason"]
        verdict.update(
            {
                "loop_id": loop_id,
                "deliverable_type": deliverable_type,
                "policy_min": policy_min,
                "min_aplicado": plan["applied_min"],
                "min_origen": plan["min_origen"],
                "coverage_key": coverage_key,
                "coverage_source": COVERAGE_SOURCE_LABEL if coverage_key else None,
                "eligible_declared": (
                    sorted(coverage_entry["backend_keys"])
                    if coverage_entry is not None
                    else None
                ),
                "eligible_effective": (
                    sorted(plan["eligible"]) if plan["eligible"] is not None else None
                ),
                "declared_removed": plan["removed"],
                "tickets": tickets,
                "exempt": exempt,
                "override": min_distinct,
                "override_below_policy": plan["override_below_policy"],
                "phase": phase,
                "delivery_authority": delivery_authority,
            }
        )
        # WOT-2026-143a: deuda historica declarada por SHA40 exacto. Solo levanta
        # un FALLO (nunca altera un OK) y queda NOMBRADA en el veredicto.
        debt = historic_debt_ficha(sha)
        verdict["debt"] = debt
        verdict["debt_waived"] = debt is not None and not verdict["ok"]
        if verdict["debt_waived"]:
            verdict["ok"] = True
        verdicts.append(verdict)
    return verdicts


def _receipt_view(v: dict) -> dict:
    """Subconjunto determinista de un veredicto para el recibo DoD 6.

    Before: veredicto de `audit()` ya enriquecido.
    During: proyecta SOLO campos estables (sin dependencia de orden de claves
        de los diagnosticos) para que dos corridas identicas impriman el mismo
        recibo (test de determinismo).
    After: dict con ticket, commit_sha, loop_id, nonces, distinct_backends,
        elegibles declarada/efectiva, no_contadas (declaradas removidas +
        rondas fuera de cobertura), deliverable_type, policy_min,
        min_aplicado, min_origen, coverage_key, override y ok.
    """
    no_contadas: list[dict[str, str]] = []
    seen_keys: set[str] = set()
    for item in (
        *(v.get("declared_removed") or []),
        *(v.get("not_eligible_backends") or []),
    ):
        key = item.get("backend_key")
        if key in seen_keys:
            continue
        seen_keys.add(key)
        no_contadas.append(item)
    return {
        "ticket": v.get("tickets"),
        "commit_sha": v.get("commit_sha"),
        "loop_id": v.get("loop_id"),
        "nonces": [e.get("nonce") for e in v.get("per_nonce", [])],
        "distinct_backends": v.get("distinct_backends"),
        "eligible_declared": v.get("eligible_declared"),
        "eligible_effective": v.get("eligible_effective"),
        "no_contadas": no_contadas,
        "deliverable_type": v.get("deliverable_type"),
        "policy_min": v.get("policy_min"),
        "min_aplicado": v.get("min_aplicado"),
        "min_origen": v.get("min_origen"),
        "coverage_key": v.get("coverage_key"),
        "override": v.get("override"),
        "exempt": v.get("exempt"),
        "debt": v.get("debt"),
        "ok": v.get("ok"),
    }


def resolve_input_commit_sha(project_root: Path, commit_sha: str) -> str:
    """Normaliza la ENTRADA CLI del --commit-sha a sha40 (S1B item 1).

    WOT-2026-067i: la resolucion ya NO vive aqui. Delega en
    `ensemble_dispatch.resolve_governed_commit_sha`, la MISMA funcion que usa el
    EMISOR (`emit-nonce`). Antes cada extremo tenia la suya y discrepaban: el
    lector aceptaba shas del destino y el emisor los bloqueaba, lo que hacia
    INSATISFACIBLE el cierre de todo ticket `delivery_authority: repo_destino`.
    Compartir funcion hace que ambos dominios sean el mismo POR CONSTRUCCION.

    Cambio de comportamiento heredado del helper compartido, deliberado: una
    abreviatura que resuelve a sha40 DISTINTOS en motor y destino ya NO se
    acepta en silencio (antes ganaba el motor) -- ahora es `ValueError`.

    Before: `project_root` resuelto; `commit_sha` la forma recibida (puede ser
        abreviada). `MOTOR_ROOT` es el motor de ESTE checkout.
    During: delega; sin escrituras.
    After: sha40 pleno. `ValueError` NOMBRANDO el sha si es ambiguo entre raices
        o si no resuelve en ninguna (fail-closed: el veredicto no se inventa).
    """
    sha40, _resolved_against = resolve_governed_commit_sha(
        MOTOR_ROOT, project_root, commit_sha
    )
    return sha40


def _resolvable_shas(root: Path, shas: list[str]) -> set[str]:
    """SHAs que resuelven a un COMMIT en `root` (resolucion en lote, D9).

    Predicado unico `<sha>^{commit}` (el mismo de resolve_governed_commit_sha):
    un abreviado que resuelve a un arbol o blob NO resuelve; `missing` y
    `ambiguous` tampoco. Se usa aqui a PROPOSITO (y no en el otro sentido):
    para la PISTA solo importa resoluble-si/no, y el peel convierte la
    ambiguedad en `missing`, que es exactamente "no resoluble".

    Before: `root` es una raiz git candidata; `shas` cadenas sin espacios.
    During: UNA lectura `git cat-file --batch-check` en BYTES (sin shell ni
        pipes: un pipe re-codifica). Sin escrituras.
    After: subconjunto resoluble. Ante git no ejecutable, rc != 0 o salida mas
        corta que la entrada devuelve set() (nada resoluble, sin excepcion).
    """
    clean = [s for s in shas if s and not any(c.isspace() for c in s)]
    if not clean or not root.is_dir():
        return set()
    payload = b"".join(f"{s}^{{commit}}\n".encode() for s in clean)
    try:
        proc = subprocess.run(  # noqa: S603
            ["git", "-C", str(root), "cat-file", "--batch-check"],  # noqa: S607
            input=payload,
            capture_output=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return set()
    if proc.returncode != 0:
        return set()
    lines = proc.stdout.decode("utf-8", errors="replace").splitlines()
    if len(lines) < len(clean):
        return set()
    resolvable: set[str] = set()
    for sha, line in zip(clean, lines, strict=False):
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "commit":
            resolvable.add(sha)
    return resolvable


def _unresolvable_evidence_shas(project_root: Path) -> list[str]:
    """SHAs citados por la evidencia que no resuelven ni en motor ni destino.

    Conserva el orden de PRIMERA aparicion (scorecard primero, luego
    emitted_nonces) para que la pista de `_print_remap_hint` sea determinista.
    Un SHA resoluble en CUALQUIERA de las dos raices no es huerfano.
    """
    rows, _sha = _read_scorecard(project_root)
    emitted = read_emitted_nonces(project_root)
    ordered: list[str] = []
    seen: set[str] = set()
    for row in [*rows, *emitted]:
        sha = row.get("commit_sha") if isinstance(row, dict) else None
        if isinstance(sha, str) and sha and sha not in seen:
            seen.add(sha)
            ordered.append(sha)
    if not ordered:
        return []
    roots = [MOTOR_ROOT]
    if project_root.resolve() != MOTOR_ROOT.resolve():
        roots.append(project_root)
    resolvable: set[str] = set()
    for root in roots:
        resolvable |= _resolvable_shas(root, ordered)
    return [sha for sha in ordered if sha not in resolvable]


def _print_remap_hint(project_root: Path, affected: list[dict]) -> None:
    """Pista DIAGNOSTICA (nunca un veredicto) en la ruta de fallo (D9).

    Corre SOLO para commits del veredicto con 0 rondas (`per_nonce` vacio)
    cuando la evidencia contiene SHAs no resolubles. Nombra
    `scripts/remap_evidence_shas.py` y la regla (arbol Y patch-id identicos),
    con hasta 3 SHAs (orden de primera aparicion) y su total. Es GLOBAL y no
    afirma que esos SHAs pertenezcan al commit consultado. No cambia ningun
    veredicto ni exit code.
    """
    if not affected:
        return
    try:
        unresolvable = _unresolvable_evidence_shas(project_root)
    except (OSError, ValueError) as exc:
        print(f"[loop-exec]   PISTA no disponible: {exc}", file=sys.stderr)
        return
    if not unresolvable:
        return
    sample = ", ".join(unresolvable[:3])
    for verdict in affected:
        print(
            f"[loop-exec]   PISTA {verdict['commit_sha']}: 0 rondas; la "
            f"evidencia contiene {len(unresolvable)} SHA(s) no resolubles "
            f"(posible reescritura de historia): {sample}. Si reescribiste "
            f"historia, usa scripts/remap_evidence_shas.py: remapea solo "
            f"pares con arbol Y patch-id identicos (git patch-id --stable)."
        )


def _print_verdict(v: dict) -> None:
    """Imprime UN veredicto por-commit y sus senales, todas NOMBRADAS.

    Reparto de ciclomatica (el CLI supera C901 con el render inline). Criterio
    ya aplicado a las mudas (WOT-2026-043q): un contador sin nombres obliga a
    re-medir a mano.
    """
    status = "OK" if v["ok"] else "FAIL"
    print(
        f"[loop-exec] {status} {v['commit_sha']}: "
        f"{len(v['distinct_backends'])}/{v['min_distinct']} lentes distintas "
        f"{v['distinct_backends']}"
    )
    # WOT-2026-129y: bloqueos de cobertura NOMBRADOS (DoD 2) antes de senales.
    if v.get("coverage_error"):
        print(f"[loop-exec]   COBERTURA {v.get('coverage_key')}: {v['coverage_error']}")
    if v.get("exempt"):
        print(
            f"[loop-exec]   EXENTO: ticket {v.get('tickets')} en "
            f"{v.get('coverage_key')} (exempt_tickets); se evalua con la "
            f"politica estricta policy_min={v.get('policy_min')} "
            "(WOT-2026-129y DoD 5)"
        )
    # WOT-2026-129y: rondas que corrieron fuera de la cobertura declarada.
    for ne in v.get("not_eligible_backends") or []:
        print(
            f"[loop-exec]   NO-ELEGIBLE {ne['backend_key']}: {ne['reason']} "
            "(ronda fuera de la cobertura elegible; no cuenta para N)"
        )
    # WOT-2026-143a: deuda historica declarada (SHA40 exacto), nunca silenciosa.
    if v.get("debt_waived"):
        print(
            f"[loop-exec]   DEUDA HISTORICA {v['commit_sha']}: bajo el minimo, "
            f"declarada en HISTORIC_LOOP_DEBT; criterio de salida {v['debt']}"
        )
    # WOT-2026-043q: nombrar a quien callo, en verde y en rojo.
    for s in v["silent_rounds"]:
        print(
            f"[loop-exec]   MUDA {s['backend_key']}: {s['diagnosis']} "
            f"(output_chars={s['output_chars']})"
        )
    # C' (DEC-bucle-doc-001): las corridas que no llegan a N se NOMBRAN,
    # tambien en verde (una instancia por debajo del minimo es senal aunque
    # otra la alcance).
    for entry in v["per_nonce"]:
        if not entry["ok"]:
            print(
                f"[loop-exec]   NONCE {entry['nonce'][:12]}...: "
                f"{entry['distinct']}/{v['min_distinct']} lentes distintas "
                f"{entry['backends']} (esa corrida no llega a N)"
            )
    # C': receipts con nonce no emitido, antes un `continue` mudo.
    for f in v["fabricated_rounds"]:
        print(
            f"[loop-exec]   FABRICADO {f['backend_key']} (nonce "
            f"{f['nonce'][:12]}...): {f['reason']}"
        )
    # WOT-2026-044p (b): nonces emitidos sin rondas (bucle declarado pero
    # no acreditado). Se reportan SIEMPRE como ERROR porque es la peor senal.
    for o in v["orphan_nonces"]:
        print(
            f"[loop-exec]   HUERFANO {o['nonce'][:12]}... "
            f"(loop={o['loop_id']}): {o['diagnosis']}"
        )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument(
        "--project-root",
        required=True,
        help=(
            "repo_destino / AGENT_PROJECT_ROOT -- NO el repo_motor en topologia "
            "motor+destino (code-only). Ahi vive .agent/runtime/ensemble/"
            "emitted_nonces.jsonl y scorecard.jsonl; pasar el repo_motor da "
            "silenciosamente 0 lentes sin ningun aviso."
        ),
    )
    ap.add_argument(
        "--commit-sha",
        action="append",
        default=[],
        help="commit de ticket a verificar (repetible)",
    )
    ap.add_argument("--deliverable-type", default=None)
    ap.add_argument(
        "--min-distinct",
        type=int,
        default=None,
        help=(
            "override del N minimo (WOT-2026-129y D5): con cobertura "
            "policy=declared NO puede bajar del minimo declarado (se rechaza); "
            "por debajo de policy avisa por stderr y queda en el recibo"
        ),
    )
    ap.add_argument("--loop-id", default=None)
    ap.add_argument(
        "--phase",
        default="MANAGER_REVIEW",
        help="fase para la clave de cobertura <PHASE>:<AUTHORITY> (default: MANAGER_REVIEW)",
    )
    ap.add_argument(
        "--delivery-authority",
        default=None,
        help=(
            "delivery_authority del ticket (p. ej. repo_motor); solo con este "
            "flag (y su clave declarada) se aplica la cobertura elegible "
            "WOT-2026-129y; sin el, camino legacy"
        ),
    )
    args = ap.parse_args(argv)

    if not args.commit_sha:
        print("[loop-exec] SKIP: no --commit-sha dado (nada que verificar).")
        return 0

    project_root = Path(args.project_root).resolve()
    # S1B item 1: normalizar la ENTRADA CLI (sha corto -> sha40) ANTES de
    # auditar. El join exacto de `audit_commit` queda intacto.
    resolved_shas: list[str] = []
    for sha in args.commit_sha:
        try:
            canonical = resolve_input_commit_sha(project_root, sha)
        except ValueError as exc:
            print(f"[loop-exec] ERROR: {exc}")
            return 1
        if canonical != sha:
            print(
                f"[loop-exec] sha normalizado: {sha} -> {canonical}",
                file=sys.stderr,
            )
        resolved_shas.append(canonical)
    verdicts = audit(
        project_root,
        commit_shas=resolved_shas,
        deliverable_type=args.deliverable_type,
        min_distinct=args.min_distinct,
        loop_id=args.loop_id,
        phase=args.phase,
        delivery_authority=args.delivery_authority,
    )
    failures = [v for v in verdicts if not v["ok"]]
    for v in verdicts:
        # WOT-2026-129y D5: un override por debajo de policy NO es silencioso.
        if v.get("override_below_policy"):
            print(
                f"[loop-exec] WARN: --min-distinct {v.get('override')} por debajo "
                f"de policy_min={v.get('policy_min')} (deliverable_type="
                f"{v.get('deliverable_type')}): se aplica por mandato CLI y queda "
                "registrado en el recibo; no lo uses para saltarte la politica.",
                file=sys.stderr,
            )
        _print_verdict(v)
        # WOT-2026-129y DoD 6: recibo reproducible por commit (JSON determinista).
        print(json.dumps({"loop_exec_receipt": _receipt_view(v)}, ensure_ascii=True))
        if v["orphan_nonces"] and v not in failures:
            failures.append(v)
    if failures:
        # WOT-2026-088b (D9): pista GLOBAL y solo diagnostica en la ruta de
        # fallo, para commits con 0 rondas; no altera veredictos ni exit code.
        _print_remap_hint(project_root, [v for v in failures if not v["per_nonce"]])
        print(
            "\n[loop-exec] ERROR: el bucle 1->9->2 NO corrio (o corrio DEGRADADO) "
            "para el/los commit(s) de arriba.\n"
            "  Cada commit de ticket exige >=N rondas de EJECUCION con backend_key\n"
            "  DISTINTO, un challenge_nonce emitido FUERA (emit-nonce) ANTES de la\n"
            "  ronda, y CONTENIDO en la respuesta: una lente que corre y CALLA no\n"
            "  aporta independencia (WOT-2026-043q). Las rondas MUDA de arriba, si\n"
            "  las hay, dicen si el fallo es de TRANSPORTE (no hubo llamada) o del\n"
            "  BACKEND (hubo llamada y respondio vacio). Corre el bucle de gobierno\n"
            "  de verdad -- no es una norma, es una barrera (WOT-2026-040b)."
        )
        return 1
    print("[loop-exec] OK: cada commit tiene el fan-out de gobierno ejecutado.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
