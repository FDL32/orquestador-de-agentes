"""Barrera del enum `domain` de las observaciones (origen: LEA-2026-002o).

El defecto que estos tests impiden: `domain` se VALIDABA contra `VALID_DOMAINS`
y se ENRUTABA contra `DOMAIN_DTYPE_MAP`, dos estructuras distintas que nada
obligaba a coincidir. Un dominio presente solo en la primera produce
observaciones que pasan `--strict`, se escriben, y no se recuperan jamas en una
manager review. Falla en silencio.

Que cubre cada bloque:

- `TestDerivacion`      -- la biyeccion gate<->enrutado, imposible de romper
                           desde el modulo canonico.
- `TestConsumidores`    -- los consumidores usan EL MISMO OBJETO, no uno igual.
- `TestSinDuplicados`   -- barrera ESTATICA sobre el arbol: nadie reintroduce
                           una enumeracion literal de dominios. Es la unica que
                           habria cazado la deriva real medida al abrir este
                           ticket (una lista de 7 de 9 dominios escrita a mano
                           en tests/unit/test_validate_observations.py).
- `TestContratoEscrito` -- `skills/_shared/ap-schema.md` documenta exactamente
                           los mismos dominios, definiciones y enrutados.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest


_MOTOR_ROOT = Path(__file__).resolve().parents[2]
if str(_MOTOR_ROOT) not in sys.path:
    sys.path.insert(0, str(_MOTOR_ROOT))

from bus.observation_domains import (  # noqa: E402
    DOMAIN_DTYPE_MAP,
    DOMAIN_SPECS,
    VALID_DELIVERABLE_TYPES,
    VALID_DOMAINS,
)


_AP_SCHEMA = _MOTOR_ROOT / "skills" / "_shared" / "ap-schema.md"
_CANONICO = _MOTOR_ROOT / "bus" / "observation_domains.py"


class TestDerivacion:
    """Gate y enrutado derivan de la misma fuente: no pueden divergir."""

    def test_biyeccion_gate_enrutado(self):
        """EL test del ticket: un dominio valido SIEMPRE tiene enrutado.

        Sin esto, anadir un dominio solo a `VALID_DOMAINS` produce memoria que
        valida y nadie lee.
        """
        assert set(DOMAIN_DTYPE_MAP) == set(VALID_DOMAINS)

    def test_nombres_unicos(self):
        assert len({s.name for s in DOMAIN_SPECS}) == len(DOMAIN_SPECS)

    def test_todo_dominio_enruta_a_algo(self):
        """`deliverable_types` vacio = el dominio valida pero nunca se recupera.

        Es el mismo fallo silencioso por otra puerta: no basta con existir en el
        mapa, hay que enrutar a al menos un deliverable_type real.
        """
        sin_ruta = [s.name for s in DOMAIN_SPECS if not s.deliverable_types]
        assert sin_ruta == []

    def test_deliverable_types_del_vocabulario_correcto(self):
        """Contra el enum del work plan, NO contra `applies_to`.

        `applies_to` dice `docs`; `deliverable_type` dice `documentation` y
        ademas tiene `research`/`analysis`. Contrastar contra el enum
        equivocado marcaria `review-quality` como invalido y borraria tres rutas
        de review que hoy funcionan.
        """
        for spec in DOMAIN_SPECS:
            desconocidos = spec.deliverable_types - VALID_DELIVERABLE_TYPES
            assert not desconocidos, f"{spec.name} enruta a {desconocidos}"

    def test_vocabulario_coincide_con_el_lector_del_work_plan(self):
        """`review_bridge._read_deliverable_type` acepta exactamente estos."""
        from bus import review_bridge

        fuente = Path(review_bridge.__file__).read_text(encoding="utf-8")
        assert "observation_domains.VALID_DELIVERABLE_TYPES" in fuente

    def test_toda_definicion_es_un_criterio(self):
        """No basta con que exista texto: debe DECIDIR frente a un vecino.

        El fallo original no fue que faltara documentacion sino que la que habia
        ('elegir un valor util y estable') no permitia decidir: dos revisores
        leyeron lo mismo y eligieron distinto.
        """
        for spec in DOMAIN_SPECS:
            assert spec.definition.strip(), f"{spec.name} sin definicion"
            assert "Frente a" in spec.definition, (
                f"{spec.name}: la definicion describe pero no excluye; "
                "debe decir contra que dominio vecino se decide y por que"
            )

    def test_estructuras_derivadas_inmutables(self):
        """`DOMAIN_DTYPE_MAP` es un global compartido por re-export.

        Mutable, un solo `.add()` en cualquier consumidor envenena el enrutado
        de todo el proceso sin dejar rastro.
        """
        with pytest.raises((TypeError, AttributeError)):
            DOMAIN_DTYPE_MAP["nuevo"] = frozenset({"code"})  # type: ignore[index]
        for dtypes in DOMAIN_DTYPE_MAP.values():
            assert isinstance(dtypes, frozenset)
        assert isinstance(VALID_DOMAINS, frozenset)


class TestConsumidores:
    """Los cuatro consumidores leen la fuente unica, no una copia."""

    def test_review_observations_reexporta_el_mismo_objeto(self):
        from bus import review_observations

        assert review_observations.DOMAIN_DTYPE_MAP is DOMAIN_DTYPE_MAP

    def test_review_bridge_encadena(self):
        from bus import review_bridge

        assert review_bridge.DOMAIN_DTYPE_MAP is DOMAIN_DTYPE_MAP

    def test_validate_observations_reexporta_el_mismo_objeto(self):
        from scripts import validate_observations

        assert validate_observations.VALID_DOMAINS is VALID_DOMAINS

    def test_migrate_observations_reexporta_el_mismo_objeto(self):
        from scripts import migrate_observations

        assert migrate_observations.VALID_DOMAINS is VALID_DOMAINS

    def test_session_close_observations_reexporta_el_mismo_objeto(self):
        from scripts import session_close_observations

        assert session_close_observations.VALID_DOMAINS is VALID_DOMAINS

    @pytest.mark.parametrize(
        "modulo",
        [
            "scripts.validate_observations",
            "scripts.migrate_observations",
            "scripts.session_close_observations",
        ],
    )
    def test_el_gate_acepta_los_dominios_nuevos(self, modulo):
        """De punta a punta: no basta con que la constante sea la misma."""
        import importlib

        mod = importlib.import_module(modulo)
        for nombre in ("contract-fixtures", "warning-contracts", "cross-phase-state"):
            assert nombre in mod.VALID_DOMAINS


def _colecciones_literales_de_dominios(arbol: ast.AST) -> list[int]:
    """Devuelve las lineas de colecciones literales hechas SOLO de dominios.

    Un `dict` de migracion cuyas CLAVES no son dominios no cuenta (mapear hacia
    un dominio es legitimo); una lista/set/tupla cuyos elementos son todos
    dominios canonicos, si: eso es una copia del enum.
    """
    lineas: list[int] = []
    for nodo in ast.walk(arbol):
        if isinstance(nodo, (ast.Set, ast.List, ast.Tuple)):
            elementos = nodo.elts
        elif isinstance(nodo, ast.Dict):
            elementos = [k for k in nodo.keys if k is not None]
        else:
            continue
        valores = [
            e.value
            for e in elementos
            if isinstance(e, ast.Constant) and isinstance(e.value, str)
        ]
        if len(valores) != len(elementos) or len(valores) < 5:
            continue
        if all(v in VALID_DOMAINS for v in valores):
            lineas.append(nodo.lineno)
    return lineas


class TestSinDuplicados:
    """Barrera estatica: nadie reintroduce una enumeracion literal.

    El test de identidad (`is`) solo prueba los modulos que importa. No detecta
    una lista escrita a mano en un fichero cualquiera del arbol -- que es
    exactamente la deriva que ya habia ocurrido cuando se abrio este ticket.
    """

    def test_ninguna_copia_del_enum_en_el_arbol(self):
        infractores: list[str] = []
        for py in sorted(_MOTOR_ROOT.glob("**/*.py")):
            partes = set(py.parts)
            if py == _CANONICO or "__pycache__" in partes:
                continue
            if partes & {".git", ".venv", "venv", "node_modules", "backups"}:
                continue
            try:
                arbol = ast.parse(py.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:
                continue
            infractores.extend(
                f"{py.relative_to(_MOTOR_ROOT)}:{linea}"
                for linea in _colecciones_literales_de_dominios(arbol)
            )
        assert infractores == [], (
            "enumeracion literal de dominios fuera de bus/observation_domains.py; "
            "importa VALID_DOMAINS en vez de copiarla: " + ", ".join(infractores)
        )


def _tabla_de_ap_schema() -> dict[str, tuple[str, frozenset[str]]]:
    """Parsea la tabla 'Dominios canonicos' de ap-schema.md."""
    texto = _AP_SCHEMA.read_text(encoding="utf-8")
    filas: dict[str, tuple[str, frozenset[str]]] = {}
    en_tabla = False
    for linea in texto.splitlines():
        if linea.startswith("## Dominios canonicos"):
            en_tabla = True
            continue
        if en_tabla and linea.startswith("## "):
            break
        if not en_tabla or not linea.startswith("|"):
            continue
        celdas = [c.strip() for c in linea.strip().strip("|").split("|")]
        if len(celdas) != 3 or celdas[0] in ("dominio", "---"):
            continue
        nombre = celdas[0].strip("`")
        dtypes = frozenset(
            d.strip().strip("`") for d in celdas[2].strip("`").split(",") if d.strip()
        )
        filas[nombre] = (celdas[1], dtypes)
    return filas


class TestContratoEscrito:
    """ap-schema.md es barrera, no comentario.

    El enrutado pudo desincronizarse justo porque no estaba en el contrato:
    `deliverable_type` no aparecia en ninguna linea de ap-schema.md.
    """

    def test_la_tabla_existe(self):
        assert "## Dominios canonicos" in _AP_SCHEMA.read_text(encoding="utf-8")

    def test_mismos_dominios_que_el_codigo(self):
        assert set(_tabla_de_ap_schema()) == set(VALID_DOMAINS)

    def test_mismo_enrutado_que_el_codigo(self):
        tabla = _tabla_de_ap_schema()
        for spec in DOMAIN_SPECS:
            assert tabla[spec.name][1] == spec.deliverable_types, (
                f"{spec.name}: ap-schema.md dice {sorted(tabla[spec.name][1])}, "
                f"el codigo dice {sorted(spec.deliverable_types)}"
            )

    def test_mismas_definiciones_que_el_codigo(self):
        tabla = _tabla_de_ap_schema()

        def norm(s: str) -> str:
            return re.sub(r"\s+", " ", s.replace("`", "")).strip()

        for spec in DOMAIN_SPECS:
            assert norm(tabla[spec.name][0]) == norm(spec.definition), (
                f"{spec.name}: la definicion de ap-schema.md no coincide con "
                "DOMAIN_SPECS"
            )

    def test_el_contrato_ya_no_omite_el_enrutado(self):
        assert "deliverable_types" in _AP_SCHEMA.read_text(encoding="utf-8")
