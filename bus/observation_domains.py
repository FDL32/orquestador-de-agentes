"""Canonical source of truth for observation `domain` values.

el campo `domain` de observations.jsonl se VALIDABA contra una
lista y se ENRUTABA contra otra, sin nada que obligase a coincidir:

    gate      scripts/validate_observations.py    VALID_DOMAINS
    enrutado  bus/review_observations.py          DOMAIN_DTYPE_MAP

Un dominio presente solo en el gate produce observaciones que PASAN `--strict`,
se escriben, y NO se recuperan JAMAS en una manager review de `code`/`mixed`
(bus/review_observations.py, filtro `domain not in relevant_domains`). Memoria
que valida y nadie lee: falla en silencio.

Este modulo hace esa clase de bug INEXPRESABLE. `VALID_DOMAINS` y
`DOMAIN_DTYPE_MAP` ya no son dos estructuras que se puedan desincronizar: ambas
se DERIVAN de `DOMAIN_SPECS`. Un `DomainSpec` no se puede construir sin
`deliverable_types`, asi que un dominio no puede existir para el gate y no
existir para el enrutado.

Modulo HOJA a proposito: solo stdlib. Todos los consumidores (los tres scripts,
bus/review_observations.py y, encadenado, bus/review_bridge.py) importan de
aqui en vez de repetir el literal. Precedente del patron: bus/ticket_id.py.

Al anadir un dominio: anadir UN `DomainSpec` aqui y la fila correspondiente en
`skills/_shared/ap-schema.md`. `tests/unit/test_observation_domains.py` falla si
falta cualquiera de las dos.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType


# ── Vocabulario de deliverable_type ──────────────────────────────────────────
# OJO: NO es el mismo enum que `applies_to` de la observacion
# (scripts/validate_observations.py: VALID_APPLIES_TO = code|mixed|docs|all).
# Son dos vocabularios distintos y confundirlos es un fallo medido: `applies_to`
# dice "docs", `deliverable_type` dice "documentation", y este ultimo tiene
# ademas "research"/"analysis" que el primero no. `deliverable_types` de un
# DomainSpec se contrasta contra ESTE conjunto, nunca contra VALID_APPLIES_TO.
#
# Fuente unica: la leia como literal bus/review_bridge.py::_read_deliverable_type,
# que ahora importa de aqui.
VALID_DELIVERABLE_TYPES: frozenset[str] = frozenset(
    {"code", "documentation", "research", "analysis", "mixed"}
)

_CODE_AND_MIXED: frozenset[str] = frozenset({"code", "mixed"})


@dataclass(frozen=True)
class DomainSpec:
    """Un dominio de observacion: nombre, criterio de eleccion y enrutado.

    `definition` NO es descriptiva sino EXCLUYENTE. La regla anterior del
    contrato ("domain debe elegir un valor util y estable de la lista") no era
    un criterio: dos revisores independientes leyeron lo mismo y eligieron
    dominios distintos para la misma observacion. Cada definicion dice contra
    que dominio vecino se decide y por que, no solo de que habla.

    `deliverable_types` es el enrutado: en que manager reviews se recupera esta
    observacion. Es OBLIGATORIO -- esa obligatoriedad es la barrera.
    """

    name: str
    definition: str
    deliverable_types: frozenset[str]


DOMAIN_SPECS: tuple[DomainSpec, ...] = (
    DomainSpec(
        name="security-gates",
        definition=(
            "Barrera de seguridad o permisos cuyo fallo ABRE acceso. Frente a "
            "`testing`: el dano es exposicion, no falso verde."
        ),
        deliverable_types=_CODE_AND_MIXED,
    ),
    DomainSpec(
        name="integration-tests",
        definition=(
            "Fallo que solo aparece al combinar componentes reales. Frente a "
            "`testing`: la unidad pasaba; el defecto vive en la juntura."
        ),
        deliverable_types=_CODE_AND_MIXED,
    ),
    DomainSpec(
        name="protocol-handlers",
        definition=(
            "Forma exacta del mensaje que viaja entre agentes o herramientas "
            "(claves, anidamiento). Frente a `config-schema`: el dato circula, "
            "no se persiste."
        ),
        deliverable_types=_CODE_AND_MIXED,
    ),
    DomainSpec(
        name="bus-architecture",
        definition=(
            "Topologia y estado operativo del PROPIO bus: terminacion, "
            "recuperacion, autoridad de lectura. Frente a `cross-phase-state`: "
            "el objeto es el bus, no un dato de dominio que lo atraviesa."
        ),
        deliverable_types=_CODE_AND_MIXED,
    ),
    DomainSpec(
        name="review-quality",
        definition=(
            "Criterios de evidencia y decision del Manager al revisar una "
            "entrega. Frente a `builder-contract`: es el lado que juzga, no el "
            "que produce."
        ),
        # Unico dominio que aplica a los cinco: la calidad de la revision se
        # recupera revise lo que revise el Manager.
        deliverable_types=VALID_DELIVERABLE_TYPES,
    ),
    DomainSpec(
        name="config-schema",
        definition=(
            "Forma y acceso seguro a configuracion persistida o parseada. "
            "Frente a `protocol-handlers`: el dato se guarda y se relee, no se "
            "envia."
        ),
        deliverable_types=_CODE_AND_MIXED,
    ),
    DomainSpec(
        name="testing",
        definition=(
            "El test como instrumento: cobertura, ortogonalidad, falso verde. "
            "Frente a `contract-fixtures`: el hallazgo agota UNA superficie."
        ),
        deliverable_types=_CODE_AND_MIXED,
    ),
    DomainSpec(
        name="delivery-hygiene",
        definition=(
            "Que se commitea, donde, con que nombre, y si el cierre esta "
            "completo. Frente a `review-quality`: es mecanica de entrega, no "
            "juicio sobre el contenido."
        ),
        deliverable_types=_CODE_AND_MIXED,
    ),
    DomainSpec(
        name="builder-contract",
        definition=(
            "Obligaciones del Builder al implementar: alcance, evidencia, "
            "no exceder el ticket. Frente a `review-quality`: es el lado que "
            "produce, no el que juzga."
        ),
        deliverable_types=_CODE_AND_MIXED,
    ),
    # ── dominios nuevos ───────────────────────────────────────
    DomainSpec(
        name="contract-fixtures",
        definition=(
            "Elevar una identidad compartida a fixture transversal cuando el "
            "mismo fallo aparece por TERCERA vez. Frente a `testing`: el "
            "hallazgo es la reincidencia a traves de superficies, y la accion "
            "es crear la fixture comun, no arreglar el test que fallo."
        ),
        deliverable_types=_CODE_AND_MIXED,
    ),
    DomainSpec(
        name="warning-contracts",
        definition=(
            "Avisos contrastados contra un historico: excluir la ejecucion en "
            "curso, distinguir reintento de repeticion. Frente a "
            "`review-quality`: el objeto es el aviso que emite una herramienta "
            "y su ventana de comparacion, no la evidencia de una revision."
        ),
        deliverable_types=_CODE_AND_MIXED,
    ),
    DomainSpec(
        name="cross-phase-state",
        definition=(
            "Estado persistido entre fases: procedencia, vigencia, "
            "invalidacion, relectura. Frente a `bus-architecture`: el objeto es "
            "un dato de dominio que sobrevive a la fase que lo escribio y que "
            "otra fase relee, no la topologia del bus."
        ),
        deliverable_types=_CODE_AND_MIXED,
    ),
)


# ── Vistas derivadas (NUNCA escritas a mano) ─────────────────────────────────

VALID_DOMAINS: frozenset[str] = frozenset(spec.name for spec in DOMAIN_SPECS)

# `MappingProxyType` + `frozenset` a proposito: este mapa es un GLOBAL
# compartido por re-export (bus/review_observations.py -> bus/review_bridge.py)
# e iterado por `relevant_domains_for_dtype`. Mutable, un solo `.add()` en
# cualquier consumidor envenena el enrutado de todo el proceso sin dejar rastro.
DOMAIN_DTYPE_MAP: Mapping[str, frozenset[str]] = MappingProxyType(
    {spec.name: spec.deliverable_types for spec in DOMAIN_SPECS}
)

DOMAIN_SPECS_BY_NAME: Mapping[str, DomainSpec] = MappingProxyType(
    {spec.name: spec for spec in DOMAIN_SPECS}
)


__all__ = [
    "DOMAIN_DTYPE_MAP",
    "DOMAIN_SPECS",
    "DOMAIN_SPECS_BY_NAME",
    "VALID_DELIVERABLE_TYPES",
    "VALID_DOMAINS",
    "DomainSpec",
]
