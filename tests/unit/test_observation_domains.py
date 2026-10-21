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
import os
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
# WOT-2026-025w: subarbol volatil gitignored (.gitignore:93) donde viven los
# tmp_path de la sesion (re-enraizados ahi por tests/conftest.py) y las caches
# que los fixtures dejan dentro (p.ej. .agent/runtime/uv-cache de `uv run`).
_TEST_RUNTIME_ROOT = _MOTOR_ROOT / "tests" / "sandbox" / "test_runtime"
# WOT-2026-059n: mismo tipo de superficie que lo de arriba (gitignored,
# .gitignore:17) pero por el OTRO lado -- scratch de TRABAJO del agente, no de
# fixtures de test. MEDIDO 2026-10-07: scripts auxiliares de una sesion previa
# de vuelo (.agent/runtime/tmp/vuelo_memoria_v3/*.py, p.ej. h1_robustez_f4.py,
# measure_robust_f4.py) definian listas literales de muestra de VALID_DOMAINS
# para sus propios probes y el scan los leia como si fueran codigo del arbol
# portable, dando falso rojo por basura temporal legitima. AGENTS.md ya
# declara este directorio "Excluido del workspace: runtime transitorio".
_RUNTIME_TMP_ROOT = _MOTOR_ROOT / ".agent" / "runtime" / "tmp"
# WOT-2026-109b: directorios que el scan no recorre. Por NOMBRE (donde esten) y
# por RUTA relativa a la raiz escaneada (tupla de componentes): el scan antes
# enumeraba todo con glob y podaba despues; ahora os.walk no desciende.
_DIRS_EXCLUIDOS = frozenset(
    {".git", ".venv", "venv", "node_modules", "backups", ".kilo", "__pycache__"}
)
_SUBARBOLES_PODADOS = frozenset(
    {
        _TEST_RUNTIME_ROOT.relative_to(_MOTOR_ROOT).parts,
        _RUNTIME_TMP_ROOT.relative_to(_MOTOR_ROOT).parts,
        # Caches de `uv run` (codigo de terceros): MEDIDO 2026-10-21 que 2014 de
        # los 2663 .py parseados por el scan (76%) vivian aqui.
        (".agent", "runtime", "uv-cache"),
    }
)


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


def _ficheros_py_del_arbol(raiz: Path = _MOTOR_ROOT) -> list[Path]:
    """Ficheros `.py` que el scan debe leer, enumerados PODANDO directorios.

    Before (pre-condiciones): `raiz` es un directorio existente.
    During (proceso): `os.walk(topdown=True, followlinks=False)` y poda
    `dirs` en sitio, de modo que NO se desciende a los subarboles excluidos
    (WOT-2026-109b: antes se enumeraba todo con `Path.glob("**/*.py")` y se
    podaba DESPUES; sobre un arbol con ~56000 ficheros de sandbox eso era
    ~4 s solo de recorrido). Se poda por NOMBRE de directorio
    (`_DIRS_EXCLUIDOS`) y por RUTA relativa a `raiz` completa
    (`_SUBARBOLES_PODADOS`), nunca por el nombre suelto de esos subarboles:
    un `uv-cache` fuera de `.agent/runtime` SI se escanea.
    After (post-condiciones): lista ordenada de rutas; no lanza.
    """
    encontrados: list[Path] = []
    for actual, dirs, ficheros in os.walk(raiz, topdown=True, followlinks=False):
        relativa = Path(actual).relative_to(raiz).parts
        dirs[:] = sorted(
            d
            for d in dirs
            if d not in _DIRS_EXCLUIDOS and (*relativa, d) not in _SUBARBOLES_PODADOS
        )
        # normcase: en Windows `Path.glob("*.py")` ignora mayusculas (UP.PY entra);
        # en POSIX no. Mismo criterio que el glob al que sustituye.
        encontrados.extend(
            Path(actual) / f for f in ficheros if os.path.normcase(f).endswith(".py")
        )
    return sorted(encontrados)


def _infractores_en_el_arbol(raiz: Path = _MOTOR_ROOT) -> list[str]:
    """Escanea el arbol del motor y devuelve las copias literales del enum.

    Before (pre-condiciones): `raiz` resuelve a la raiz del motor con sus
    ficheros trackeados presentes; no requiere ningun estado previo de sesion.
    During (proceso): enumera con `_ficheros_py_del_arbol` (poda de
    directorios: `.git/.venv/venv/node_modules/backups/.kilo/__pycache__` por
    nombre y, por ruta relativa, -- WOT-2026-025w -- el subarbol volatil
    `tests/sandbox/test_runtime` (gitignored en `.gitignore:93`, 0 ficheros
    trackeados: `git ls-files tests/sandbox/test_runtime` -> 0; precedente:
    `_safe_walk` ya lo poda desde WOT-2026-013d), -- WOT-2026-059n -- el
    scratch de trabajo `.agent/runtime/tmp` (gitignored en `.gitignore:17`, 0
    ficheros trackeados: `git ls-files .agent/runtime/tmp` -> 0) y --
    WOT-2026-109b -- `.agent/runtime/uv-cache` (caches de `uv run`: codigo de
    terceros bajo `.agent/runtime/`, no fuente del proyecto). Salta el modulo
    canonico. Lee y parsea con AST solo los ficheros restantes.
    After (post-condiciones): devuelve la lista de `ruta:linea` de cada
    coleccion literal hecha SOLO de dominios; nunca lanza (un SyntaxError
    salta ese fichero).
    """
    canonico = raiz / "bus" / "observation_domains.py"
    infractores: list[str] = []
    for py in _ficheros_py_del_arbol(raiz):
        if py == canonico:
            continue
        try:
            arbol = ast.parse(py.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        infractores.extend(
            f"{py.relative_to(raiz)}:{linea}"
            for linea in _colecciones_literales_de_dominios(arbol)
        )
    return infractores


class TestSinDuplicados:
    """Barrera estatica: nadie reintroduce una enumeracion literal.

    El test de identidad (`is`) solo prueba los modulos que importa. No detecta
    una lista escrita a mano en un fichero cualquiera del arbol -- que es
    exactamente la deriva que ya habia ocurrido cuando se abrio este ticket.
    """

    def test_ninguna_copia_del_enum_en_el_arbol(self):
        infractores = _infractores_en_el_arbol()
        assert infractores == [], (
            "enumeracion literal de dominios fuera de bus/observation_domains.py; "
            "importa VALID_DOMAINS en vez de copiarla: " + ", ".join(infractores)
        )

    def test_el_scan_ignora_el_sandbox_volatil(self, tmp_path: Path):
        """Regresion del piloto de optimizacion WOT-2026-025w.

        FAIL-sin / PASS-con el podado de `tests/sandbox/test_runtime` en
        `_infractores_en_el_arbol`. Before (sin el podado): este test planta
        una copia literal del enum dentro de `tmp_path` (re-enraizado en el
        sandbox volatil por `conftest.py`) y el scan la PARSEA como si fuera
        fuente del proyecto -- el test falla con `infractores` apuntando al
        fichero plantado. After (con el podado): el subarbol gitignored se
        ignora y el test pasa.

        Motivo medido (PASO 1b, corrida completa 2026-09-28T16:22:38Z):
        el scan AST-parseaba 6044 de 6714 ficheros que vivian bajo el
        sandbox (caches `uv-cache` de terceros que los fixtures dejan en
        `tmp_path`), 19.9s de la llamada en sesion y 38.97s en suite.
        La barrera NO pierde cobertura duradera: `git ls-files
        tests/sandbox/test_runtime` -> 0 ficheros trackeados.
        """
        muestra = sorted(VALID_DOMAINS)[:5]
        (tmp_path / "copia_enum.py").write_text(
            "LISTA_COPIADA = [" + ", ".join(f'"{d}"' for d in muestra) + "]\n",
            encoding="utf-8",
        )
        infractores = _infractores_en_el_arbol()
        assert infractores == [], (
            "el scan del arbol NO debe leer el sandbox volatil "
            "tests/sandbox/test_runtime (WOT-2026-025w); fichero que lo "
            "delata: " + ", ".join(infractores)
        )


_DOMINIOS_COPIADOS = (
    "[" + ", ".join(f'"{d}"' for d in sorted(VALID_DOMAINS)[:5]) + "]\n"
)


def _ficheros_py_via_glob(raiz: Path, *, podar_uv_cache: bool) -> list[Path]:
    """ORACULO del scan previo (WOT-2026-109b): `glob("**/*.py")` y poda despues.

    Mismo criterio de exclusion que `_ficheros_py_del_arbol`, evaluado sobre la
    ruta RELATIVA a `raiz`. (La version anterior miraba `py.parts` absolutos: si
    el checkout vivia bajo un directorio llamado `venv`/`backups`/`.kilo`, el
    scan se desactivaba en silencio. Diferencia deliberada, no un cambio de
    cobertura en un arbol normal.)
    """
    podados = {p for p in _SUBARBOLES_PODADOS if p != (".agent", "runtime", "uv-cache")}
    if podar_uv_cache:
        podados.add((".agent", "runtime", "uv-cache"))
    resultado: list[Path] = []
    for py in sorted(raiz.glob("**/*.py")):
        if not py.is_file():
            continue
        rel = py.relative_to(raiz).parts
        if set(rel) & _DIRS_EXCLUIDOS:
            continue
        if any(rel[: len(p)] == p for p in podados):
            continue
        resultado.append(py)
    return resultado


def _plantar(raiz: Path, rel: str, contenido: str = "X = 1\n") -> Path:
    destino = raiz.joinpath(*rel.split("/"))
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(contenido, encoding="utf-8")
    return destino


_RUTAS_ARBOL_FIXTURE = (
    # se escanean
    "a.py",
    "pkg/b.py",
    "pkg/sub/c.py",
    "pkg/uv-cache/m.py",  # el NOMBRE `uv-cache` suelto no poda: solo la ruta completa
    "tmp/real.py",  # idem `tmp`
    "pkg/test_runtime/q2.py",  # idem `test_runtime`
    "tests/sandbox/otro/o.py",
    ".agent/runtime/otro/r.py",
    "dir.py/dentro.py",  # un DIRECTORIO llamado dir.py: glob lo lista, no es fichero
    # se podan por nombre, donde esten
    ".git/x.py",
    ".venv/lib/y.py",
    "venv/z.py",
    "node_modules/n.py",
    "backups/k.py",
    ".kilo/q.py",
    "pkg/__pycache__/p.py",
    "pkg/.git/w.py",
    # se podan por ruta relativa completa
    "tests/sandbox/test_runtime/s/t.py",
    ".agent/runtime/tmp/scratch.py",
    ".agent/runtime/uv-cache/pkg/u.py",
    # no son .py
    "notas.txt",
    "mod.pyc",
)


def _arbol_fixture(raiz: Path) -> Path:
    for rel in _RUTAS_ARBOL_FIXTURE:
        _plantar(raiz, rel)
    return raiz


class TestEscaneoPodaPorRuta:
    """WOT-2026-109b: `os.walk` con poda == `glob` + filtro, salvo `uv-cache`.

    La IGUALDAD DE CONJUNTOS no la garantiza el cambio de API, la demuestra este
    guard sobre un arbol fixture (NO el sandbox ni el arbol real: recorrerlo con
    el oraculo costaria justo lo que el piloto ahorra).
    """

    def test_mismo_conjunto_que_el_glob_salvo_uv_cache(self, tmp_path: Path):
        raiz = _arbol_fixture(tmp_path / "raiz")
        nuevo = _ficheros_py_del_arbol(raiz)
        assert nuevo == _ficheros_py_via_glob(raiz, podar_uv_cache=True)
        # La unica diferencia con el scan anterior (sin podar uv-cache) es
        # `.agent/runtime/uv-cache`: nada mas se ha dejado de leer.
        sin_podar = _ficheros_py_via_glob(raiz, podar_uv_cache=False)
        perdidos = {p.relative_to(raiz).as_posix() for p in set(sin_podar) - set(nuevo)}
        assert perdidos == {".agent/runtime/uv-cache/pkg/u.py"}

    def test_la_poda_es_por_ruta_completa_no_por_nombre_suelto(self, tmp_path: Path):
        raiz = _arbol_fixture(tmp_path / "raiz")
        vistos = {p.relative_to(raiz).as_posix() for p in _ficheros_py_del_arbol(raiz)}
        # Mutation: podar por nombre (`uv-cache`, `tmp`, `test_runtime` donde sea)
        # pierde estos tres y el scan deja de leer codigo fuente real.
        assert {"pkg/uv-cache/m.py", "tmp/real.py", "pkg/test_runtime/q2.py"} <= vistos

    def test_no_desciende_a_los_subarboles_podados(self, tmp_path: Path, monkeypatch):
        """El ahorro es de RECORRIDO, no solo de parseo: ni se listan."""
        raiz = _arbol_fixture(tmp_path / "raiz")
        listados: list[str] = []
        real_walk = os.walk

        def espia(top, *args, **kwargs):
            for actual, dirs, ficheros in real_walk(top, *args, **kwargs):
                listados.append(Path(actual).relative_to(raiz).as_posix())
                yield actual, dirs, ficheros

        monkeypatch.setattr(os, "walk", espia)
        _ficheros_py_del_arbol(raiz)
        for podado in (".agent/runtime/uv-cache", ".agent/runtime/tmp", ".git", "venv"):
            assert not any(
                d == podado or d.startswith(podado + "/") for d in listados
            ), f"se descendio a {podado}"

    def test_os_walk_se_invoca_sin_seguir_enlaces(self, tmp_path: Path, monkeypatch):
        raiz = _arbol_fixture(tmp_path / "raiz")
        llamadas: list[dict] = []
        real_walk = os.walk

        def espia(top, *args, **kwargs):
            llamadas.append(kwargs)
            return real_walk(top, *args, **kwargs)

        monkeypatch.setattr(os, "walk", espia)
        _ficheros_py_del_arbol(raiz)
        assert llamadas[0].get("followlinks") is False
        assert llamadas[0].get("topdown") is True

    def test_un_enlace_simbolico_a_un_directorio_no_se_sigue(self, tmp_path: Path):
        raiz = _arbol_fixture(tmp_path / "raiz")
        fuera = tmp_path / "fuera"
        _plantar(fuera, "fuga.py")
        try:
            os.symlink(fuera, raiz / "enlace", target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            pytest.skip(f"esta plataforma/usuario no puede crear symlinks: {exc}")
        nombres = {p.name for p in _ficheros_py_del_arbol(raiz)}
        assert "fuga.py" not in nombres

    def test_una_copia_literal_plantada_sigue_detectandose(self, tmp_path: Path):
        """Guard anti-relajacion (mutation): el scan sigue mordiendo."""
        raiz = _arbol_fixture(tmp_path / "raiz")
        assert _infractores_en_el_arbol(raiz) == []
        _plantar(raiz, "lib/copia.py", "LISTA = " + _DOMINIOS_COPIADOS)
        assert _infractores_en_el_arbol(raiz) == [str(Path("lib") / "copia.py") + ":1"]

    def test_la_copia_en_un_subarbol_podado_o_en_el_modulo_canonico_no_cuenta(
        self, tmp_path: Path
    ):
        raiz = _arbol_fixture(tmp_path / "raiz")
        for rel in (
            ".agent/runtime/uv-cache/terceros/copia.py",
            "tests/sandbox/test_runtime/s/copia.py",
            "bus/observation_domains.py",
        ):
            _plantar(raiz, rel, "LISTA = " + _DOMINIOS_COPIADOS)
        assert _infractores_en_el_arbol(raiz) == []


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
