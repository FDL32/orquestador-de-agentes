#!/usr/bin/env python3
"""WOT-2026-136i: tests del medidor de contexto de las sesiones de un vuelo.

Hermetico: cada caso arma su registro y sus transcripts sinteticos en `tmp_path`; los
transcripts no llevan contenido de conversaciones, solo las claves que lee el medidor
(`type`, `timestamp`, `isCompactSummary`, `message.usage`). Ningun caso lee el registro vivo
ni `~/.claude*`: toda raiz se pasa por `--projects-root`.
"""

from __future__ import annotations

import ast
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from scripts import context_usage as cu


T0 = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)
SECOND = timedelta(seconds=1)


def _iso(offset_s: float) -> str:
    return (T0 + timedelta(seconds=offset_s)).isoformat().replace("+00:00", "Z")


def _assistant(offset_s: float, total: int, **extra) -> dict:
    return {
        "type": "assistant",
        "timestamp": _iso(offset_s),
        "message": {
            "role": "assistant",
            "usage": {
                "input_tokens": 1,
                "cache_read_input_tokens": total - 1 - 2,
                "cache_creation_input_tokens": 2,
            },
        },
        **extra,
    }


def _write(path: Path, records: list, tail: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(json.dumps(r) + "\n" for r in records)
    path.write_bytes((body + tail).encode("utf-8"))
    return path


def _registry(tmp_path: Path, rows: list[dict]) -> Path:
    path = tmp_path / "session_registry.json"
    path.write_text(json.dumps({"sessions": rows}), encoding="utf-8")
    return path


def _row(code: str, slot: str, offset_s: float | None) -> dict:
    return {
        "code": code,
        "slot": slot,
        "started": None if offset_s is None else _iso(offset_s),
    }


def _run(tmp_path: Path, rows: list[dict], capsys, *extra: str):
    registry = _registry(tmp_path, rows)
    rc = cu.main(
        ["--registry", str(registry), "--projects-root", str(tmp_path / "proj"), *extra]
    )
    out = capsys.readouterr()
    return rc, out.out, out.err


def _proj(tmp_path: Path, slug: str, name: str) -> Path:
    return tmp_path / "proj" / slug / f"{name}.jsonl"


# --- (1) y (2): contexto actual y compactaciones --------------------------------------------


def test_contexto_es_input_mas_cache_del_ultimo_assistant(tmp_path):
    path = _write(tmp_path / "t.jsonl", [_assistant(0, 100), _assistant(1, 350_000)])
    measure = cu.measure_transcript(path)
    assert (measure.ctx_now, measure.ctx_max, measure.messages) == (350_000, 350_000, 2)


def test_caida_a_usage_cero_no_es_compactacion(tmp_path):
    caida = _assistant(1, 3)
    caida["message"]["usage"] = {
        "input_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    }
    path = _write(
        tmp_path / "t.jsonl", [_assistant(0, 400_000), caida, _assistant(2, 50_000)]
    )
    measure = cu.measure_transcript(path)
    assert measure.compactions == 0
    assert (measure.ctx_now, measure.ctx_max) == (50_000, 400_000)


def test_is_compact_summary_cuenta_una_por_mensaje(tmp_path):
    registros = [
        _assistant(0, 400_000),
        {"type": "user", "timestamp": _iso(1), "isCompactSummary": True},
        _assistant(2, 20_000),
        {"type": "user", "timestamp": _iso(3), "isCompactSummary": False},
        {"type": "user", "timestamp": _iso(4), "isCompactSummary": True},
        _assistant(5, 30_000),
    ]
    measure = cu.measure_transcript(_write(tmp_path / "t.jsonl", registros))
    assert measure.compactions == 2


def test_sintetico_y_cadena_lateral_no_son_el_contexto_actual(tmp_path):
    sintetico = _assistant(2, 3)
    sintetico["message"]["model"] = "<synthetic>"
    lateral = _assistant(3, 999_999, isSidechain=True)
    path = _write(tmp_path / "t.jsonl", [_assistant(0, 120_000), sintetico, lateral])
    assert cu.measure_transcript(path).ctx_now == 120_000


def test_transcript_sin_assistant_con_usage_es_desconocido(tmp_path):
    path = _write(tmp_path / "t.jsonl", [{"type": "user", "timestamp": _iso(0)}])
    assert cu.measure_transcript(path) is None


# --- (6): formato desconocido falla cerrado --------------------------------------------------


def test_linea_json_truncada_se_salta_y_se_cuenta(tmp_path):
    path = _write(
        tmp_path / "t.jsonl",
        [_assistant(0, 100_000)],
        tail='{"type": "assistant", "mess',
    )
    measure = cu.measure_transcript(path)
    assert measure.skipped_lines == 1
    assert measure.ctx_now == 100_000


def test_fichero_sin_ninguna_linea_json_valida_es_formato_desconocido(tmp_path):
    path = tmp_path / "t.jsonl"
    path.write_text("esto no es json\notra linea\n", encoding="utf-8")
    with pytest.raises(cu.FormatoDesconocidoError, match="formato no reconocido"):
        cu.measure_transcript(path)


@pytest.mark.parametrize(
    "usage",
    [
        "cadena",
        {"cache_read_input_tokens": 5},
        {"input_tokens": "9"},
        {"input_tokens": 1, "cache_read_input_tokens": -4},
        {"input_tokens": True},
    ],
)
def test_usage_mal_formado_es_formato_desconocido(tmp_path, usage):
    registro = _assistant(0, 100)
    registro["message"]["usage"] = usage
    with pytest.raises(cu.FormatoDesconocidoError):
        cu.measure_transcript(_write(tmp_path / "t.jsonl", [registro]))


def test_linea_que_no_es_objeto_y_flag_no_booleano_son_formato_desconocido(tmp_path):
    with pytest.raises(cu.FormatoDesconocidoError, match="no es un objeto"):
        cu.measure_transcript(
            _write(tmp_path / "a.jsonl", [_assistant(0, 100), [1, 2]])
        )
    with pytest.raises(cu.FormatoDesconocidoError, match="isCompactSummary"):
        cu.measure_transcript(
            _write(tmp_path / "b.jsonl", [{"type": "user", "isCompactSummary": "si"}])
        )


def test_main_devuelve_rc_2_y_mensaje_ante_formato_desconocido(tmp_path, capsys):
    registro = _assistant(0, 100)
    registro["message"]["usage"] = {"input_tokens": "nueve"}
    _write(_proj(tmp_path, "wt-orquestadora-1", "x"), [registro])
    rc, out, err = _run(tmp_path, [_row("OR-1", "orquestadora-1", 0)], capsys)
    assert rc == 2
    assert "NO VERIFICABLE" in err and "input_tokens" in err
    assert "esperados" not in out


def test_registro_ilegible_o_sin_sessions_da_rc_2(tmp_path, capsys):
    mal = tmp_path / "reg.json"
    mal.write_text("{no json", encoding="utf-8")
    assert cu.main(["--registry", str(mal), "--projects-root", str(tmp_path)]) == 2
    mal.write_text(json.dumps({"otra": []}), encoding="utf-8")
    assert cu.main(["--registry", str(mal), "--projects-root", str(tmp_path)]) == 2
    assert "sessions" in capsys.readouterr().err


def test_registro_con_started_sin_zona_es_formato_desconocido(tmp_path):
    registro = _registry(
        tmp_path, [{"code": "OR-1", "slot": "a", "started": "2026-10-30T12:00:00"}]
    )
    with pytest.raises(cu.FormatoDesconocidoError, match="zona"):
        cu.load_registry(registro)


def test_sin_registro_ni_variable_da_rc_2(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv(cu.REGISTRY_ENV, raising=False)
    assert cu.main(["--projects-root", str(tmp_path)]) == 2
    assert cu.REGISTRY_ENV in capsys.readouterr().err


def test_registro_por_variable_de_entorno(tmp_path, monkeypatch, capsys):
    _write(_proj(tmp_path, "wt-orquestadora-1", "x"), [_assistant(0, 100_000)])
    monkeypatch.setenv(
        cu.REGISTRY_ENV, str(_registry(tmp_path, [_row("OR-1", "orquestadora-1", 0)]))
    )
    assert cu.main(["--projects-root", str(tmp_path / "proj")]) == 0
    assert "medidos 1" in capsys.readouterr().out


# --- (3) y (4): atribucion, denominador y sin medicion ---------------------------------------


def test_sesion_sin_transcript_sale_sin_medicion_y_el_denominador_va_primero(
    tmp_path, capsys
):
    _write(_proj(tmp_path, "wt-orquestadora-1", "a"), [_assistant(0, 100_000)])
    rows = [
        _row("OR-1", "orquestadora-1", 0),
        _row("OR-9", "orquestadora-9", 0),
        _row("OR-5", "orquestadora-5", None),
    ]
    rc, out, _ = _run(tmp_path, rows, capsys)
    lineas = out.splitlines()
    assert rc == 0
    assert lineas[0] == "esperados 3, medidos 1, sin medicion 2"
    assert "OR-9 [orquestadora-9]: sin directorio de transcripts para el slot" in out
    assert "OR-5 [orquestadora-5]: el registro no trae `started`" in out
    assert "DESCONOCIDO" in out
    assert not any(linea.startswith("OR-9 ") for linea in lineas)


def test_nada_medido_da_rc_2_aunque_imprima_el_informe(tmp_path, capsys):
    rc, out, err = _run(tmp_path, [_row("OR-9", "orquestadora-9", 0)], capsys)
    assert rc == 2
    assert out.splitlines()[0] == "esperados 1, medidos 0, sin medicion 1"
    assert "ninguna sesion medida" in err


def test_transcript_sin_assistant_se_lista_sin_medicion(tmp_path, capsys):
    _write(
        _proj(tmp_path, "wt-orquestadora-1", "a"),
        [{"type": "user", "timestamp": _iso(0)}],
    )
    _write(_proj(tmp_path, "wt-orquestadora-2", "b"), [_assistant(0, 100_000)])
    rows = [_row("OR-1", "orquestadora-1", 0), _row("OR-2", "orquestadora-2", 0)]
    rc, out, _ = _run(tmp_path, rows, capsys)
    assert rc == 0
    assert "OR-1 [orquestadora-1]: transcript sin mensajes assistant con usage" in out


def test_coordinadoras_de_un_directorio_compartido_se_reparten_por_started(
    tmp_path, capsys
):
    carpeta = "wt-orquestadora-3-vuelo"
    _write(_proj(tmp_path, carpeta, "a"), [_assistant(-60, 111_111)])
    _write(_proj(tmp_path, carpeta, "b"), [_assistant(3600 - 90, 222_222)])
    rows = [_row("CO-1", "coord-1", 0), _row("CO-2", "coord-2", 3600)]
    rc, out, _ = _run(
        tmp_path,
        rows,
        capsys,
        "--slot-dir",
        "coord-1=orquestadora-3",
        "--slot-dir",
        "coord-2=orquestadora-3",
    )
    assert rc == 0
    assert "111111" in out and "222222" in out
    assert out.splitlines()[0] == "esperados 2, medidos 2, sin medicion 0"


def test_un_transcript_anterior_a_la_ventana_de_otra_sesion_no_se_le_asigna(tmp_path):
    transcripts = {"d": [_write(tmp_path / "d" / "solo.jsonl", [_assistant(0, 100)])]}
    sesiones = [
        cu.Session("A", "d", T0),
        cu.Session("B", "d", T0 + 100 * SECOND),
    ]
    reparto = cu.attribute(
        sesiones, transcripts, {}, 5 * SECOND, timedelta(0), 1000 * SECOND
    )
    assert list(reparto.chosen) == ["A"]
    assert "ventana" in reparto.missing["B"]


def test_la_ventana_termina_en_el_started_de_la_siguiente_sesion(tmp_path):
    # Con la ventana abierta hasta max_lag, A se llevaria el transcript de B; la ventana lo impide.
    transcripts = {"d": [_write(tmp_path / "d" / "b.jsonl", [_assistant(100, 100)])]}
    sesiones = [cu.Session("A", "d", T0), cu.Session("B", "d", T0 + 100 * SECOND)]
    reparto = cu.attribute(
        sesiones, transcripts, {}, 5 * SECOND, timedelta(0), 1000 * SECOND
    )
    assert list(reparto.chosen) == ["B"]
    assert "A" in reparto.missing
    rutas = [t.path for t in reparto.chosen.values()]
    assert len(rutas) == len(set(rutas))


@pytest.mark.parametrize(
    ("separacion_s", "ambiguo"),
    [(0, True), (4, True), (5, True), (6, False)],
)
def test_ambiguedad_por_ventana_de_5_segundos_ambos_lados(
    tmp_path, separacion_s, ambiguo
):
    transcripts = {
        "d": [
            _write(tmp_path / "d" / "uno.jsonl", [_assistant(10, 100)]),
            _write(tmp_path / "d" / "dos.jsonl", [_assistant(10 + separacion_s, 100)]),
        ]
    }
    reparto = cu.attribute(
        [cu.Session("A", "d", T0)],
        transcripts,
        {},
        5 * SECOND,
        timedelta(0),
        1000 * SECOND,
    )
    assert ("A" in reparto.missing) is ambiguo
    if ambiguo:
        assert reparto.missing["A"].startswith("ambiguo: 2 candidatos")
        assert len(reparto.unattributed) == 2
    else:
        assert reparto.chosen["A"].path.name == "uno.jsonl"


def test_el_umbral_de_ambiguedad_es_un_parametro(tmp_path):
    transcripts = {
        "d": [
            _write(tmp_path / "d" / "uno.jsonl", [_assistant(10, 100)]),
            _write(tmp_path / "d" / "dos.jsonl", [_assistant(14, 100)]),
        ]
    }
    sesion = [cu.Session("A", "d", T0)]
    estricto = cu.attribute(
        sesion, transcripts, {}, 2 * SECOND, timedelta(0), 1000 * SECOND
    )
    laxo = cu.attribute(
        sesion, transcripts, {}, 5 * SECOND, timedelta(0), 1000 * SECOND
    )
    assert "A" in laxo.missing and "A" in estricto.chosen


def test_el_lead_admite_el_transcript_que_arranco_antes_del_started(tmp_path):
    transcripts = {"d": [_write(tmp_path / "d" / "t.jsonl", [_assistant(-120, 100)])]}
    sesion = [cu.Session("A", "d", T0)]
    estricta = cu.attribute(
        sesion, transcripts, {}, 5 * SECOND, timedelta(0), 300 * SECOND
    )
    con_lead = cu.attribute(
        sesion, transcripts, {}, 5 * SECOND, 300 * SECOND, 300 * SECOND
    )
    assert "A" in estricta.missing and "A" in con_lead.chosen


def test_el_tope_de_lag_descarta_un_transcript_muy_posterior(tmp_path):
    transcripts = {
        "d": [_write(tmp_path / "d" / "t.jsonl", [_assistant(48 * 3600, 100)])]
    }
    reparto = cu.attribute(
        [cu.Session("A", "d", T0)],
        transcripts,
        {},
        5 * SECOND,
        300 * SECOND,
        300 * SECOND,
    )
    assert "A" in reparto.missing


def test_transcript_sin_timestamp_queda_sin_atribuir(tmp_path):
    transcripts = {"d": [_write(tmp_path / "d" / "t.jsonl", [{"type": "user"}])]}
    reparto = cu.attribute(
        [cu.Session("A", "d", T0)],
        transcripts,
        {},
        5 * SECOND,
        300 * SECOND,
        300 * SECOND,
    )
    assert "A" in reparto.missing
    assert reparto.unattributed[0].first_ts is None


def test_timestamp_ilegible_en_el_transcript_es_formato_desconocido(tmp_path):
    path = _write(tmp_path / "t.jsonl", [{"type": "user", "timestamp": "ayer"}])
    with pytest.raises(cu.FormatoDesconocidoError, match="timestamp"):
        cu.first_timestamp(path)


# --- enlace slot -> directorio ---------------------------------------------------------------


def test_slot_casa_por_palabras_y_un_sufijo_numerico_es_otra_generacion():
    nombres = [
        "wt-orquestadora-3-vuelo",
        "wt-orquestadora-3-1-vuelo",
        "wt-orquestadora-30-vuelo",
    ]
    assert cu.dirs_for_slot("orquestadora-3", nombres, {}) == [
        "wt-orquestadora-3-vuelo"
    ]
    assert cu.dirs_for_slot("implantacion-136l", ["wt-implantador-136l-2026"], {}) == []
    assert cu.dirs_for_slot(
        "implantacion-136l",
        ["wt-implantador-136l-2026"],
        {"implantacion-136l": "implantador-136l"},
    ) == ["wt-implantador-136l-2026"]
    assert cu.dirs_for_slot(None, nombres, {}) == []


def test_las_raices_repetidas_por_enlace_cuentan_una_vez(tmp_path):
    real = tmp_path / "real"
    _write(real / "wt-a" / "t.jsonl", [_assistant(0, 100)])
    enlace = tmp_path / "enlace"
    try:
        enlace.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("sin permiso para symlinks")
    hallados = cu.discover_transcripts(cu.project_roots([str(real), str(enlace)]))
    assert list(hallados) == ["wt-a"] and len(hallados["wt-a"]) == 1


def test_dos_raices_con_un_subdirectorio_del_mismo_nombre_juntan_sus_transcripts(
    tmp_path, capsys
):
    uno = _write(
        tmp_path / "raiz1" / "wt-orquestadora-1" / "uno.jsonl", [_assistant(0, 1)]
    )
    dos = _write(
        tmp_path / "raiz2" / "wt-orquestadora-1" / "dos.jsonl",
        [_assistant(600, 100_000)],
    )
    hallados = cu.discover_transcripts(
        cu.project_roots([str(tmp_path / "raiz1"), str(tmp_path / "raiz2")])
    )
    assert hallados == {"wt-orquestadora-1": [uno, dos]}
    # De punta a punta: la sesion cuyo transcript solo esta en la segunda raiz se mide, y el
    # transcript de la primera aparece como sin atribuir en vez de desaparecer.
    registro = _registry(tmp_path, [_row("OR-1", "orquestadora-1", 600)])
    rc = cu.main(
        [
            "--registry", str(registro),
            "--projects-root", str(tmp_path / "raiz1"),
            "--projects-root", str(tmp_path / "raiz2"),
            "--list-unattributed",
        ]
    )  # fmt: skip
    out = capsys.readouterr().out
    assert rc == 0
    assert "medidos 1" in out and "dos.jsonl"[:8] in out
    assert "wt-orquestadora-1/uno.jsonl" in out


def test_el_candidato_aislado_gana_aunque_el_segundo_y_el_tercero_se_pisen(tmp_path):
    transcripts = {
        "d": [
            _write(tmp_path / "d" / "primero.jsonl", [_assistant(10, 1)]),
            _write(tmp_path / "d" / "segundo.jsonl", [_assistant(20, 1)]),
            _write(tmp_path / "d" / "tercero.jsonl", [_assistant(22, 1)]),
        ]
    }
    reparto = cu.attribute(
        [cu.Session("A", "d", T0)],
        transcripts,
        {},
        5 * SECOND,
        timedelta(0),
        1000 * SECOND,
    )
    assert reparto.chosen["A"].path.name == "primero.jsonl"
    assert {t.path.name for t in reparto.unattributed} == {
        "segundo.jsonl",
        "tercero.jsonl",
    }


def test_ninguna_ventana_atribuye_dos_veces_un_transcript_ni_fuera_de_su_ventana(
    tmp_path,
):
    azar = random.Random(136)  # noqa: S311 - semilla fija, no criptografia
    for caso in range(200):
        lead = timedelta(seconds=azar.choice([0, 300]))
        max_lag = timedelta(seconds=azar.choice([300, 1000]))
        carpeta = tmp_path / f"caso{caso}"
        transcripts = {
            nombre: [
                _write(
                    carpeta / nombre / f"t{n}.jsonl",
                    [_assistant(azar.randint(-400, 1500), 1)],
                )
                for n in range(azar.randint(0, 5))
            ]
            for nombre in ("dirA", "dirB")
        }
        transcripts = {k: v for k, v in transcripts.items() if v}
        sesiones = [
            cu.Session(f"S{n}", f"slot{n}", T0 + azar.randint(0, 1200) * SECOND)
            for n in range(azar.randint(2, 5))
        ]
        enlaces = {s.slot: azar.choice(["dirA", "dirB", "dir"]) for s in sesiones}
        reparto = cu.attribute(
            sesiones, transcripts, enlaces, 5 * SECOND, lead, max_lag
        )
        rutas = [t.path for t in reparto.chosen.values()]
        assert len(rutas) == len(set(rutas)), caso
        vecinos = {
            s.code: [
                o.started
                for o in sesiones
                if o is not s
                and o.started >= s.started
                and {d for d in transcripts if enlaces[o.slot] in d}
                & {d for d in transcripts if enlaces[s.slot] in d}
            ]
            for s in sesiones
        }
        for s in sesiones:
            if s.code in reparto.chosen:
                ts = reparto.chosen[s.code].first_ts
                tope = min([s.started + max_lag, *[v - lead for v in vecinos[s.code]]])
                assert s.started - lead <= ts < tope, (caso, s.code)


def test_el_desfase_entre_started_y_transcript_se_imprime_con_signo(tmp_path, capsys):
    _write(_proj(tmp_path, "wt-orquestadora-1", "a"), [_assistant(-120, 100_000)])
    rc, out, _ = _run(tmp_path, [_row("OR-1", "orquestadora-1", 0)], capsys)
    fila = next(linea for linea in out.splitlines() if linea.startswith("OR-1 "))
    assert rc == 0 and "desfase_s" in out
    assert fila.split()[-2] == "-120"


def test_una_compactacion_de_cadena_lateral_no_cuenta_en_la_sesion_principal(tmp_path):
    registros = [
        _assistant(0, 100_000),
        {
            "type": "user",
            "timestamp": _iso(1),
            "isCompactSummary": True,
            "isSidechain": True,
        },
        {"type": "user", "timestamp": _iso(2), "isCompactSummary": True},
    ]
    assert (
        cu.measure_transcript(_write(tmp_path / "t.jsonl", registros)).compactions == 1
    )


# --- (5): solo lectura -----------------------------------------------------------------------


def _foto(raiz: Path) -> dict[str, tuple[int, bytes]]:
    return {
        str(p.relative_to(raiz)): (p.stat().st_mtime_ns, p.read_bytes())
        for p in raiz.rglob("*")
        if p.is_file()
    }


def test_la_ejecucion_no_modifica_ni_crea_ficheros(tmp_path, capsys):
    _write(
        _proj(tmp_path, "wt-orquestadora-1", "a"),
        [_assistant(0, 100_000)],
        tail="{trunc",
    )
    registro = _registry(tmp_path, [_row("OR-1", "orquestadora-1", 0)])
    antes = _foto(tmp_path)
    rc = cu.main(
        [
            "--registry",
            str(registro),
            "--projects-root",
            str(tmp_path / "proj"),
            "--list-unattributed",
        ]
    )
    capsys.readouterr()
    assert rc == 0
    assert _foto(tmp_path) == antes


def test_el_script_no_importa_procesos_ni_red_ni_abre_en_escritura():
    fuente = Path(cu.__file__).read_text(encoding="utf-8")
    arbol = ast.parse(fuente)
    importados = {
        alias.name.split(".")[0]
        for nodo in ast.walk(arbol)
        if isinstance(nodo, ast.Import)
        for alias in nodo.names
    } | {
        nodo.module.split(".")[0]
        for nodo in ast.walk(arbol)
        if isinstance(nodo, ast.ImportFrom) and nodo.module
    }
    assert importados.isdisjoint(
        {"subprocess", "socket", "urllib", "http", "requests", "shutil"}
    )
    prohibidos = {
        "write_text",
        "write_bytes",
        "unlink",
        "rename",
        "replace",
        "mkdir",
        "touch",
        "system",
        "Popen",
    }
    llamadas = {
        nodo.func.attr
        for nodo in ast.walk(arbol)
        if isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Attribute)
    }
    assert llamadas.isdisjoint(prohibidos)
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Call) and getattr(nodo.func, "attr", "") == "open":
            modos = [a.value for a in nodo.args if isinstance(a, ast.Constant)] + [
                k.value.value
                for k in nodo.keywords
                if k.arg == "mode" and isinstance(k.value, ast.Constant)
            ]
            assert not any(set("wax+") & set(str(m)) for m in modos)
