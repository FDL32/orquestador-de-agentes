"""Tests del lector de vecindad de memoria/backlog (WOT-2026-039m).

Rubrica aplicada: cada test fuerza una transicion real o un caso limite. No hay
`assert x is not None` ni umbrales satisfechos por el valor base sin la feature.

El test decisivo (`test_dogfooding_*`) corre contra el CORPUS REAL del motor, no
contra fixtures escritos para el barrido: barrer contra los propios fixtures mide
los fixtures, no el sistema (fallo medido el 2026-07-22).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from find_similar_signals import (
    ParseError,
    load_archive,
    load_backlog,
    main,
    rank_neighbours,
    tokenize,
)


MOTOR_ROOT = Path(__file__).resolve().parents[2]
REAL_ARCHIVE = MOTOR_ROOT / ".agent/runtime/memory/archive/observations.2026-07.jsonl"


# --------------------------------------------------------------------------
# Tokenizacion y ponderacion
# --------------------------------------------------------------------------


def test_tokenize_tolerates_none_and_non_str():
    """El corpus real trae campos ausentes; tokenize no puede petar por ello."""
    assert tokenize(None) == set()
    assert tokenize("") == set()
    assert tokenize(12345) == {"12345"}


def test_tokenize_drops_short_tokens():
    """Articulos y preposiciones se caen por longitud, sin lista por idioma."""
    assert tokenize("de la el guard vara") == {"guard", "vara"}


def test_idf_demotes_ubiquitous_terms():
    """Un termino presente en TODAS las entradas no debe decidir el ranking.

    Sin IDF este es el fallo central: `2026`/`regla`/`ticket` aparecen en casi todo
    el corpus y un solape crudo los cuenta igual que un termino discriminante,
    degenerando en el mismo grep ciego que el detector viene a sustituir.

    El fixture esta calibrado para que la ponderacion INVIERTA el ganador, no solo
    para que lo confirme: `senuelo` comparte TRES terminos ubicuos con el candidato
    y `correcto` solo DOS raros. Con peso plano gana `senuelo` (0.60 vs 0.40); con
    IDF gana `correcto` (0.67 vs 0.33). Un fixture donde el vecino correcto ganara
    igual sin IDF seria una FLOOR ASSERTION: pasaria con la feature mutada y no
    probaria nada (verificado por mutacion: sustituir el IDF por 1.0 dejaba los 20
    tests en verde).
    """
    corpus = [("archive", f"ruido-{i}", "ticket regla commit") for i in range(12)]
    corpus += [
        ("archive", "senuelo", "ticket regla commit"),
        ("archive", "correcto", "mutacion copia"),
    ]
    hits = rank_neighbours("ticket regla commit mutacion copia", corpus, top=14)
    assert hits, "un candidato con terminos del corpus debe producir vecinos"
    assert hits[0][2] == "correcto", (
        "el vecino que comparte terminos RAROS debe ganar al que solo comparte "
        "terminos ubicuos: sin ponderacion IDF gana 'senuelo' y el detector "
        f"degenera en un grep ciego; ranking obtenido: {[h[2] for h in hits[:3]]}"
    )


def test_rank_returns_shared_terms_for_human_reading():
    """El auditor debe ver POR QUE hubo match, no solo un numero."""
    corpus = [("archive", "x", "mutacion copia restaura deliverable")]
    (score, surface, label, terms) = rank_neighbours("mutacion copia", corpus, 5)[0]
    assert 0 < score <= 1
    assert surface == "archive" and label == "x"
    assert set(terms) == {"mutacion", "copia"}


def test_disjoint_candidate_yields_no_neighbours():
    """Sin terminos comunes no se inventan vecinos (ruido = ceguera del auditor)."""
    corpus = [("archive", "x", "mutacion copia restaura")]
    assert rank_neighbours("zzzz yyyy wwww", corpus, 5) == []


# --------------------------------------------------------------------------
# Lectura del archive (contrato de LECTURA, no de escritura)
# --------------------------------------------------------------------------


def test_load_archive_tolerates_entries_without_id(tmp_path):
    """10 de las 132 entradas reales no tienen `id`: asumirlo peta con KeyError."""
    p = tmp_path / "a.jsonl"
    p.write_text(
        json.dumps({"signal": "con id", "id": "obs-1"})
        + "\n"
        + json.dumps({"signal": "sin id", "topic": "un-topic"})
        + "\n"
        + json.dumps({"signal": "sin id ni topic"})
        + "\n",
        encoding="utf-8",
    )
    labels = [lb for lb, _ in load_archive(p)]
    assert labels == ["obs-1", "un-topic", "#3"]


def test_load_archive_skips_entries_without_signal(tmp_path):
    """El eje de comparacion es el signal; sin el, la entrada no es comparable."""
    p = tmp_path / "a.jsonl"
    p.write_text(
        json.dumps({"id": "vacia", "signal": ""})
        + "\n"
        + json.dumps({"id": "buena", "signal": "texto real"})
        + "\n",
        encoding="utf-8",
    )
    assert [lb for lb, _ in load_archive(p)] == ["buena"]


def test_load_archive_raises_on_corrupt_json(tmp_path):
    """Un JSONL corrupto es ParseError -> exit 2, NUNCA 'no hay similares'."""
    p = tmp_path / "a.jsonl"
    p.write_text('{"signal": "ok"}\n{roto\n', encoding="utf-8")
    with pytest.raises(ParseError):
        load_archive(p)


# --------------------------------------------------------------------------
# Lectura del backlog markdown
# --------------------------------------------------------------------------


def test_load_backlog_reassembles_multiline_cells(tmp_path):
    """Una celda multilinea partiria la fila y truncaria la señal en silencio."""
    p = tmp_path / "b.md"
    p.write_text(
        "| Prioridad | Ticket | Titulo |\n"
        "|---|---|---|\n"
        "| Alta | WOT-2026-001a | primera parte\n"
        "  continuacion de la misma celda |\n",
        encoding="utf-8",
    )
    rows = load_backlog(p)
    assert len(rows) == 1
    label, body = rows[0]
    assert label == "WOT-2026-001a"
    assert "continuacion" in body, "la continuacion multilinea debe conservarse"


def test_load_backlog_redetects_header_per_table(tmp_path):
    """backlog_done encadena tablas de esquemas distintos.

    Arrastrar el indice de la primera cabecera etiqueta las filas de la segunda
    con la columna equivocada (medido en dogfooding: un vecino salio como `Media`,
    que es la celda de prioridad, en vez de su ticket).
    """
    p = tmp_path / "b.md"
    p.write_text(
        "| Ticket | Estado |\n"
        "|---|---|\n"
        "| WOT-2026-001a | completed |\n"
        "\n"
        "| Prioridad | Ticket | Titulo |\n"
        "|---|---|---|\n"
        "| Media | WOT-2026-002b | un titulo |\n",
        encoding="utf-8",
    )
    assert [lb for lb, _ in load_backlog(p)] == ["WOT-2026-001a", "WOT-2026-002b"]


def test_load_backlog_recovers_label_when_prose_shifts_cells(tmp_path):
    """Una ficha con `|` sin escapar desplaza las celdas.

    Medido: 26 de 113 filas del backlog vivo quedaban etiquetadas con media ficha.
    La celda de cabecera es la intencion; el patron de ticket es el hecho.
    """
    p = tmp_path / "b.md"
    p.write_text(
        "| Prioridad | Ticket | Titulo |\n"
        "|---|---|---|\n"
        "| Alta | texto | con pipe WOT-2026-003c | descripcion |\n",
        encoding="utf-8",
    )
    assert [lb for lb, _ in load_backlog(p)] == ["WOT-2026-003c"]


def test_load_backlog_ignores_rows_before_any_header(tmp_path):
    """Sin esquema conocido no hay etiqueta fiable: la fila se descarta."""
    p = tmp_path / "b.md"
    p.write_text(
        "| WOT-2026-009z | huerfana sin cabecera |\n"
        "\n"
        "| Ticket | Estado |\n"
        "|---|---|\n"
        "| WOT-2026-001a | completed |\n",
        encoding="utf-8",
    )
    assert [lb for lb, _ in load_backlog(p)] == ["WOT-2026-001a"]


# --------------------------------------------------------------------------
# Contrato de CLI: es ayuda, nunca gate
# --------------------------------------------------------------------------


def test_cli_exit_zero_when_no_neighbours(tmp_path, capsys):
    """NON-GOAL duro: no encontrar nada NO es fallo y no bloquea la promocion."""
    a = tmp_path / "a.jsonl"
    a.write_text(json.dumps({"id": "x", "signal": "alfa beta gamma"}) + "\n", "utf-8")
    rc = main(["--text", "zzzz yyyy wwww", "--archive", str(a)])
    assert rc == 0
    assert "Sin vecinos" in capsys.readouterr().out


def test_cli_exit_zero_even_with_strong_neighbour(tmp_path, capsys):
    """Un vecino fortisimo tampoco puede devolver != 0: no es un gate."""
    a = tmp_path / "a.jsonl"
    a.write_text(
        json.dumps({"id": "x", "signal": "mutacion copia restaura"}) + "\n", "utf-8"
    )
    rc = main(["--text", "mutacion copia restaura", "--archive", str(a)])
    assert rc == 0
    assert "NO es un duplicado confirmado" in capsys.readouterr().out


def test_cli_parse_error_is_exit_2_not_silent_zero(tmp_path, capsys):
    """ "No pude parsear" debe ser distinguible de "no hay similares"."""
    a = tmp_path / "a.jsonl"
    a.write_text("{roto\n", encoding="utf-8")
    rc = main(["--text", "algun texto largo", "--archive", str(a)])
    assert rc == 2
    assert "ERROR de parseo" in capsys.readouterr().err


def test_cli_requires_at_least_one_surface(capsys):
    """Barrer UNA sola superficie es el fallo que este lector combate."""
    rc = main(["--text", "un candidato cualquiera"])
    assert rc == 2
    assert "al menos una superficie" in capsys.readouterr().err


def test_cli_crosses_both_surfaces_in_one_sweep(tmp_path, capsys):
    """El CRUCE de superficies es el mecanismo central del ticket (DoD c).

    Un candidato debe poder encontrar a la vez su vecino en la MEMORIA y su vecino
    en el BACKLOG. Barrer una sola superficie por vez fue exactamente el 2o de los 4
    fallos medidos el 2026-07-22: el duplicado estaba en el backlog y el dedupe solo
    miro el archive. Este test alcanza la rama que carga ambas superficies -- sin el,
    retirar el cruce del cargador deja la suite entera en verde (verificado por
    mutacion: 19/19 pasaban con el cruce eliminado).
    """
    archive = tmp_path / "a.jsonl"
    archive.write_text(
        json.dumps(
            {
                "id": "obs-regla-abstracta",
                "signal": "mutacion copia restaura deliverable",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    backlog = tmp_path / "b.md"
    backlog.write_text(
        "| Ticket | Titulo |\n"
        "|---|---|\n"
        "| WOT-2026-777z | mutacion copia restaura sin commitear |\n",
        encoding="utf-8",
    )
    rc = main(
        [
            "--text",
            "mutacion copia restaura",
            "--archive",
            str(archive),
            "--backlog",
            str(backlog),
            "--json",
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    surfaces = {n["surface"] for n in payload["neighbours"]}
    labels = {n["label"] for n in payload["neighbours"]}
    assert surfaces == {"archive", "backlog"}, (
        "el barrido debe cruzar AMBAS superficies en una sola pasada; "
        f"superficies obtenidas: {surfaces}"
    )
    assert {"obs-regla-abstracta", "WOT-2026-777z"} <= labels
    assert payload["scanned"] == 2, "la cobertura debe contar las dos superficies"


def test_cli_reports_coverage_to_prevent_false_green(tmp_path, capsys):
    """Un 'sin vecinos' por no haber escaneado nada seria un falso verde."""
    a = tmp_path / "a.jsonl"
    a.write_text(json.dumps({"id": "x", "signal": "alfa beta gamma"}) + "\n", "utf-8")
    main(["--text", "alfa beta", "--archive", str(a)])
    assert "escaneadas 1 entradas" in capsys.readouterr().out


# --------------------------------------------------------------------------
# DOGFOODING contra el corpus REAL (no fixtures)
# --------------------------------------------------------------------------


@pytest.mark.skipif(not REAL_ARCHIVE.exists(), reason="archive real no disponible")
def test_dogfooding_detector_lists_the_lesson_about_itself():
    """El detector aplicado a SU PROPIA leccion debe listarla.

    `obs-the-meta-guard-had-the-disease` dice que un guard que mide una propiedad
    tiende a medirla con vara mas floja consigo mismo. Se le pasa una REFORMULACION
    CONCRETA de esa regla ABSTRACTA -- el cruce exacto que el dedupe por keyword no
    hace -- y debe aparecer entre los vecinos. Si no aparece, el detector no sirve
    para aquello que se construyo: es hallazgo, no exito.
    """
    entries = load_archive(REAL_ARCHIVE)
    corpus = [("archive", lb, sg) for lb, sg in entries]
    candidate = (
        "enunciar una regla no la aplica a uno mismo; el guard que mide una "
        "propiedad la mide con vara mas floja consigo mismo"
    )
    labels = [lb for _, _, lb, _ in rank_neighbours(candidate, corpus, top=5)]
    assert "obs-the-meta-guard-had-the-disease" in labels, (
        "el detector NO lista la leccion que describe su propio modo de fallo; "
        f"vecinos obtenidos: {labels}"
    )


@pytest.mark.skipif(not REAL_ARCHIVE.exists(), reason="archive real no disponible")
def test_dogfooding_real_duplicate_cases_are_surfaced():
    """Los casos REALES del 2026-07-22 deben aparecer en el top-5 del corpus real."""
    entries = load_archive(REAL_ARCHIVE)
    corpus = [("archive", lb, sg) for lb, sg in entries]
    cases = {
        "obs-mutation-verify-copy-restore-not-git-checkout": (
            "restaurar la mutacion con git checkout borro el deliverable entero "
            "que no estaba commiteado"
        ),
        "obs-receipt-guard-had-its-own-false-green": (
            "el guard que caza false greens en bundles tenia su propio false green: "
            "aceptaba un path absoluto fuera del root"
        ),
        "obs-premisa-operativa-de-prompt-tambien-caduca": (
            "una premisa operativa escrita en un prompt tambien caduca y debe "
            "reverificarse contra la fuente viva"
        ),
    }
    for expected, candidate in cases.items():
        labels = [lb for _, _, lb, _ in rank_neighbours(candidate, corpus, top=5)]
        assert expected in labels, f"{expected} no listado; obtenidos: {labels}"
