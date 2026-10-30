#!/usr/bin/env python3
"""WOT-2026-136m: tests del chequeo de deriva del indice de campos de `quota`.

Hermetico: cada caso arma su propio roster y su propio protocolo sinteticos en
`tmp_path`; ningun caso lee el roster vivo. Solo `test_indice_real_...` lee el protocolo
real del repo (para fijar que el parser ve sus 31 filas), nunca el roster.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from scripts.closeout_steps.gates import step_quota_index_drift
from scripts.session_closeout import StepResult


_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "flight" / "check_quota_index_drift.py"
_PROTOCOL = _ROOT / "docs" / "protocol" / "flight_supervision.md"


def _load_script():
    """Carga el script por ruta (scripts/flight no es paquete) sin registrar nada."""
    spec = importlib.util.spec_from_file_location("check_quota_index_drift_t", _SCRIPT)
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


MOD = _load_script()
# Fuente UNICA de la exencion: la constante del script, no una copia.
EXENTAS = MOD.PROVIDER_MAP_HIJAS_EXENTAS
HIJAS = [ruta.rsplit(".", 1)[1] for ruta in EXENTAS]
BASE_QUOTA = {
    "source": "monitor",
    "account_policy": {"scope": "s", "provider_map": dict.fromkeys(HIJAS, "prov")},
}
BASE_INDICE = [
    "quota.source",
    "quota.account_policy",
    "quota.account_policy.scope",
    "quota.account_policy.provider_map",
]


def _protocolo(claves: list[str], *, encabezado: bool = True) -> str:
    filas = "".join(f"| `{k}` | P1 |\n" for k in claves)
    cuerpo = (
        "| Clave de `quota` (ruta completa) | Donde se desarrolla |\n|---|---|\n"
        + filas
    )
    cabeza = "### Indice de campos de quota\n\n" if encabezado else ""
    return (
        "# Protocolo\n\nProsa con `quota.fantasma` entre comillas, sin ser fila.\n\n"
        + cabeza
        + "Prosa con `quota.otra.ruta` tampoco es fila.\n\n"
        + cuerpo
        + "\n### Otra seccion\n\n| `quota.ajena` | no cuenta |\n"
    )


def _escribe(tmp_path: Path, quota, claves: list[str], **kw) -> tuple[Path, Path]:
    roster = tmp_path / "flight_roster.json"
    roster.write_text(json.dumps({"quota": quota}), encoding="utf-8")
    protocolo = tmp_path / "protocol.md"
    protocolo.write_text(_protocolo(claves, **kw), encoding="utf-8")
    return roster, protocolo


def _corre(roster: Path | None, protocolo: Path, env_roster: str | None = None):
    """Ejecuta el script como en produccion (subprocess) y devuelve (rc, lineas)."""
    env = {k: v for k, v in os.environ.items() if k != "FLIGHT_ROSTER_PATH"}
    if env_roster is not None:
        env["FLIGHT_ROSTER_PATH"] = env_roster
    args = [sys.executable, str(_SCRIPT), "--protocol-path", str(protocolo)]
    if roster is not None:
        args += ["--roster-path", str(roster)]
    r = subprocess.run(
        args, capture_output=True, text=True, encoding="utf-8", env=env, timeout=60
    )
    return r.returncode, r.stdout.strip().splitlines()


# ---------------------------------------------------------------- DoD (3): 8 casos


def test_sin_deriva_imprime_ok_rc0(tmp_path):
    """Before: roster e indice coinciden (hijas exentas aparte). After: OK, rc 0."""
    roster, proto = _escribe(tmp_path, BASE_QUOTA, BASE_INDICE)
    rc, lineas = _corre(roster, proto)
    assert rc == 0
    assert lineas[0].startswith("OK 4 claves"), lineas
    assert "2 exentas" in lineas[0]


def test_clave_nueva_en_roster_avisa(tmp_path):
    """Una ruta del roster que el indice no tiene da AVISO rc 0 con la clave y el
    comando para revalidar. Control positivo: sin la clave nueva, el caso base es OK."""
    quota = {**BASE_QUOTA, "clave_nueva": 1}
    roster, proto = _escribe(tmp_path, quota, BASE_INDICE)
    rc, lineas = _corre(roster, proto)
    assert rc == 0
    assert lineas[0].startswith("AVISO"), lineas
    assert "  roster-sin-indice: quota.clave_nueva" in lineas
    assert any(ln.startswith("Revalidar: python scripts/flight/") for ln in lineas)
    assert not any(ln.startswith("  indice-sin-roster") for ln in lineas)


def test_clave_retirada_del_roster_avisa(tmp_path):
    """Una fila del indice cuya ruta ya no esta en el roster da AVISO rc 0."""
    quota = {k: v for k, v in BASE_QUOTA.items() if k != "source"}
    roster, proto = _escribe(tmp_path, quota, BASE_INDICE)
    rc, lineas = _corre(roster, proto)
    assert rc == 0
    assert lineas[0].startswith("AVISO"), lineas
    assert "  indice-sin-roster: quota.source" in lineas


def test_hija_nueva_bajo_provider_map_avisa_pero_las_exentas_no(tmp_path):
    """La exencion es por clave exacta: una tercera hija NO exenta da AVISO, mientras las
    dos de `PROVIDER_MAP_HIJAS_EXENTAS` siguen sin avisar (el caso base es OK)."""
    quota = {
        "source": "monitor",
        "account_policy": {
            "scope": "s",
            "provider_map": {**BASE_QUOTA["account_policy"]["provider_map"], "otra": 1},
        },
    }
    roster, proto = _escribe(tmp_path, quota, BASE_INDICE)
    rc, lineas = _corre(roster, proto)
    assert rc == 0
    assert lineas[0].startswith("AVISO"), lineas
    sin_indice = [ln for ln in lineas if ln.startswith("  roster-sin-indice")]
    assert sin_indice == ["  roster-sin-indice: quota.account_policy.provider_map.otra"]


def test_roster_ausente_no_verificable_rc2(tmp_path):
    """Roster inexistente, y tambien sin flag ni variable: NO VERIFICABLE rc 2, jamas OK."""
    _, proto = _escribe(tmp_path, BASE_QUOTA, BASE_INDICE)
    rc, lineas = _corre(tmp_path / "no_existe.json", proto)
    assert rc == 2 and lineas[0].startswith("NO VERIFICABLE"), lineas
    rc, lineas = _corre(None, proto)
    assert rc == 2 and "sin roster" in lineas[0], lineas


def test_roster_ilegible_no_verificable_rc2(tmp_path):
    roster, proto = _escribe(tmp_path, BASE_QUOTA, BASE_INDICE)
    roster.write_text("{no es json", encoding="utf-8")
    rc, lineas = _corre(roster, proto)
    assert rc == 2 and lineas[0].startswith("NO VERIFICABLE"), lineas
    assert "JSON" in lineas[0]


@pytest.mark.parametrize("quota", [{}, None, [], "texto"])
def test_roster_sin_quota_util_no_verificable_rc2(tmp_path, quota):
    """Sin bloque `quota` (ausente, vacio o de otro tipo) no hay nada que comparar."""
    roster, proto = _escribe(tmp_path, quota, BASE_INDICE)
    if quota is None:
        roster.write_text(json.dumps({"otro": 1}), encoding="utf-8")
    rc, lineas = _corre(roster, proto)
    assert rc == 2 and lineas[0].startswith("NO VERIFICABLE"), lineas


def test_indice_vacio_o_no_parseable_no_verificable_nunca_ok(tmp_path):
    """Encabezado sin filas, sin encabezado y con una fila malformada: rc 2, nunca OK."""
    roster, proto = _escribe(tmp_path, BASE_QUOTA, [])
    rc, lineas = _corre(roster, proto)
    assert rc == 2 and "ninguna fila" in lineas[0], lineas
    roster, proto = _escribe(tmp_path, BASE_QUOTA, BASE_INDICE, encabezado=False)
    rc, lineas = _corre(roster, proto)
    assert rc == 2 and "subseccion" in lineas[0], lineas
    roster, proto = _escribe(tmp_path, BASE_QUOTA, BASE_INDICE)
    proto.write_text(
        proto.read_text(encoding="utf-8").replace(
            "| `quota.source` | P1 |", "| `quota.source` sin segunda celda"
        ),
        encoding="utf-8",
    )
    rc, lineas = _corre(roster, proto)
    assert rc == 2 and "malformada" in lineas[0], lineas


# ---------------------------------------------------------- contrato y propiedades


def test_nunca_rc3_ni_ok_sin_comparar(tmp_path):
    """El contrato de rc: solo 0 o 2 en todos los casos; la 1a linea es OK/AVISO/NO
    VERIFICABLE y OK solo aparece cuando se compararon claves en ambos lados."""
    especificaciones = [
        (BASE_QUOTA, BASE_INDICE, "OK"),
        ({**BASE_QUOTA, "x": 1}, BASE_INDICE, "AVISO"),
        ({}, BASE_INDICE, "NO VERIFICABLE"),
        (BASE_QUOTA, [], "NO VERIFICABLE"),
    ]
    casos = []
    for n, (quota, claves, esperado) in enumerate(especificaciones):
        carpeta = tmp_path / f"caso{n}"  # un directorio por caso: no se pisan
        carpeta.mkdir()
        casos.append((_escribe(carpeta, quota, claves), esperado))
    for (roster, proto), esperado in casos:
        rc, lineas = _corre(roster, proto)
        assert rc in (0, 2) and rc != 3
        assert lineas[0].startswith(esperado), (lineas, esperado)
        assert (rc == 2) == esperado.startswith("NO")


def test_roster_por_variable_de_entorno_y_flag_gana(tmp_path):
    """Sin flag se usa FLIGHT_ROSTER_PATH; con flag, el flag gana sobre la variable."""
    roster, proto = _escribe(tmp_path, BASE_QUOTA, BASE_INDICE)
    rc, lineas = _corre(None, proto, env_roster=str(roster))
    assert rc == 0 and lineas[0].startswith("OK"), lineas
    rc, lineas = _corre(roster, proto, env_roster=str(tmp_path / "otro.json"))
    assert rc == 0 and lineas[0].startswith("OK"), lineas


def test_exenta_escrita_en_el_indice_no_es_discrepancia(tmp_path):
    """Si alguien escribe una hija exenta en el indice y el roster la tiene, no avisa."""
    roster, proto = _escribe(tmp_path, BASE_QUOTA, [*BASE_INDICE, EXENTAS[0]])
    rc, lineas = _corre(roster, proto)
    assert rc == 0 and lineas[0].startswith("OK"), lineas


def test_aplana_nodos_intermedios_y_hojas_sin_descender_listas():
    rutas = MOD.flatten_paths({"a": {"b": 1, "c": {"d": [{"e": 1}]}}, "f": None})
    assert rutas == {"quota.a", "quota.a.b", "quota.a.c", "quota.a.c.d", "quota.f"}


def test_el_chequeo_no_escribe_roster_ni_protocolo(tmp_path):
    """DoD (6): solo lectura. Los bytes de ambos ficheros y el listado del directorio
    quedan identicos tras correr el chequeo en un caso con AVISO."""
    roster, proto = _escribe(tmp_path, {**BASE_QUOTA, "x": 1}, BASE_INDICE)
    antes = (roster.read_bytes(), proto.read_bytes(), sorted(tmp_path.iterdir()))
    _corre(roster, proto)
    assert (
        roster.read_bytes(),
        proto.read_bytes(),
        sorted(tmp_path.iterdir()),
    ) == antes


def test_indice_real_del_protocolo_se_parsea_y_no_incluye_exentas():
    """Lee el protocolo REAL (no el roster): 31 filas, ninguna exenta, y la ruta entre
    comillas invertidas en la PROSA del protocolo no entra como fila."""
    claves = MOD.parse_index_keys(_PROTOCOL.read_text(encoding="utf-8"))
    assert len(claves) == 31
    assert not claves & set(EXENTAS)
    assert "scripts/flight/check_quota_index_drift.py" not in claves


def test_el_protocolo_ya_no_dice_que_el_chequeo_queda_fuera():
    """DoD (5): la frase que declaraba el chequeo fuera de alcance dejo de ser cierta.
    Before: el protocolo real. After: nombra el script (que existe) y no conserva la frase
    (busqueda multilinea: el salto de linea la partia y un grep de linea unica no la ve)."""
    texto = _PROTOCOL.read_text(encoding="utf-8")
    assert not re.search(r"queda\s+fuera\s+de\s+este\s+ticket", texto)
    assert "`scripts/flight/check_quota_index_drift.py`" in texto
    assert _SCRIPT.is_file()


# ------------------------------------------------- paso de closeout (mapeo de rc)


class _Res:
    def __init__(self, rc: int, out: str = "", err: str = "") -> None:
        self.returncode, self.stdout, self.stderr = rc, out, err


def _paso(fn, dry_run=False, roster_path=None):
    llamadas: list = []

    def run(nombre, args, cwd, timeout=None):
        llamadas.append((nombre, args, timeout))
        return fn()

    r = step_quota_index_drift(
        Path("."),
        dry_run,
        roster_path=roster_path,
        run_script_fn=run,
        process_diagnostic_fn=lambda res: f"diag:{res.stdout}{res.stderr}",
        step_result_cls=StepResult,
    )
    return r, llamadas


def test_paso_dry_run_omite_y_lo_declara():
    r, llamadas = _paso(lambda: _Res(0, "OK"), dry_run=True)
    assert llamadas == []
    assert r.status == "SKIP" and not r.blocking and "not verified" in r.detail


def test_paso_ok_es_pass_y_pasa_el_roster_solo_si_lo_hay():
    r, llamadas = _paso(lambda: _Res(0, "OK 31 claves"), roster_path="/x/r.json")
    assert (r.status, r.blocking, r.detail) == ("PASS", False, "OK 31 claves")
    assert llamadas == [
        ("flight/check_quota_index_drift.py", ["--roster-path", "/x/r.json"], 30)
    ]
    _, llamadas = _paso(lambda: _Res(0, "OK"))
    assert llamadas[0][1] == []


def test_paso_aviso_es_warn_visible_no_bloqueante():
    salida = "AVISO deriva\n  roster-sin-indice: quota.nueva\nRevalidar: python x"
    r, _ = _paso(lambda: _Res(0, salida))
    assert (r.status, r.blocking) == ("WARN", False)
    assert "quota.nueva" in r.detail and "Revalidar" in r.detail


@pytest.mark.parametrize(
    "res", [_Res(2, "NO VERIFICABLE sin roster"), _Res(1, "", "boom"), _Res(3, "N/A")]
)
def test_paso_rc_distinto_de_0_es_not_verified_no_bloqueante(res):
    r, _ = _paso(lambda: res)
    assert (r.status, r.blocking) == ("NOT_VERIFIED", False)
    assert f"exit {res.returncode}" in r.detail and "diag:" in r.detail


def test_paso_rc0_sin_ok_ni_aviso_nunca_es_pass():
    """Un rc 0 cuya 1a linea no es OK ni AVISO (script cambiado, stdout vacio) no
    puede salir verde."""
    for salida in ("", "algo raro"):
        r, _ = _paso(lambda s=salida: _Res(0, s))
        assert (r.status, r.blocking) == ("NOT_VERIFIED", False)


@pytest.mark.parametrize(
    "exc",
    [subprocess.TimeoutExpired("x", 30), FileNotFoundError("x")],
)
def test_paso_timeout_y_script_ausente_no_bloquean(exc):
    def lanza():
        raise exc

    r, _ = _paso(lanza)
    assert (r.status, r.blocking) == ("NOT_VERIFIED", False)


def test_run_closeout_invoca_el_paso_y_un_warn_no_bloquea(tmp_path, monkeypatch):
    """Cableado: run_closeout llama a `_step_quota_index_drift` con el roster recibido
    y un WARN no bloquea el cierre (rc 0). Mutacion: retirar la llamada deja
    `invocado` en False. Los pasos previos se sustituyen como en el test de 136c."""
    wp_dir = tmp_path / ".agent" / "collaboration"
    wp_dir.mkdir(parents=True)
    (wp_dir / "work_plan.md").write_text(
        "# Work Plan\n\n## Metadata\n- **ID:** WOT-2026-0001\n", encoding="utf-8"
    )
    visto: dict = {"invocado": False}

    def falso_quota(project_root, dry_run, *, roster_path=None):
        visto.update(invocado=True, dry_run=dry_run, roster_path=roster_path)
        return StepResult(name="quota_index_drift", status="WARN", detail="faked")

    monkeypatch.setattr("scripts.session_closeout._step_quota_index_drift", falso_quota)
    monkeypatch.setattr(
        "scripts.session_closeout._step_roster_matches_acting_thread",
        lambda *a, **k: StepResult(name="roster", status="PASS", blocking=True),
    )
    monkeypatch.setattr(
        "scripts.session_closeout._step_prepush_check",
        lambda *a, **k: StepResult(name="prepush_check", status="PASS", blocking=True),
    )
    import scripts.session_closeout as session_closeout

    rc = session_closeout.run_closeout(
        tmp_path,
        dry_run=False,
        acting_thread="mcp:test-thread",
        roster_path="/fake/roster.json",
    )
    assert visto["invocado"] is True, "run_closeout no llama al paso de deriva"
    assert visto["roster_path"] == "/fake/roster.json" and visto["dry_run"] is False
    assert rc == 0
