"""WOT-2026-049j: `--why <id|topic>` muestra procedencia COMPLETA de una entrada.

Contexto medido en el motor: `--recall` (memory_context.py) imprime
timestamp/topic/signal/source, pero NO `confidence`, `source_ticket`,
`evidence`, `impact`, `domain` ni en que FICHERO vive la entrada (L1 o que mes
del archive) -- campos que el schema YA declara pero que ninguna vista expone
juntos. `find_similar_signals.py` es "GENERADOR DE SENAL, NUNCA VEREDICTO", y
`memory_loader.recall_observations()` devuelve dicts sin vista de procedencia.

DoD BINARIO del ticket:
  (a) un comando muestra, para un id/topic dado, los campos de procedencia que
      YA existen en el schema, mas si esta en L1/archive y en que fichero;
  (b) NO inventa campos: si `evidence` falta, lo dice;
  (c) test con una entrada real del archive.

NON-GOAL: no anadir campos al schema, no scoring numerico, no tocar el loader
(`bus/memory_loader.py` no se modifica; `_locate_provenance_file` relee los
ficheros CRUDOS por separado).
"""

from __future__ import annotations

import json
from pathlib import Path

import scripts.memory_context as memory_context


def _entry(**overrides) -> dict:
    base = {
        "id": "obs-test-why-entry",
        "topic": "testing",
        "signal": "Una senal de prueba con procedencia completa para --why.",
        "source": "session-test",
        "source_ticket": "WOT-2026-049j",
        "evidence": "commit abc123, test unitario",
        "timestamp": "2026-10-09T00:00:00+00:00",
        "confidence": 0.9,
        "impact": "medium",
        "domain": "testing",
    }
    base.update(overrides)
    return base


def test_why_prints_every_provenance_field_for_a_real_shaped_entry(monkeypatch, capsys):
    """DoD (a)+(c): --why <id> imprime los 7 campos de procedencia del schema
    mas el fichero de origen, para una entrada con la FORMA real del archive
    (mismos nombres de campo que un record real: source, source_ticket,
    evidence, timestamp, confidence, impact, domain).

    MUTACION ALCANZABLE: quitar cualquier campo de `_PROVENANCE_FIELDS` en
    `_print_why` hace que su valor correspondiente desaparezca del output y
    este assert cae.
    """
    entry = _entry()
    monkeypatch.setattr(memory_context, "recall_observations", lambda **k: [entry])
    monkeypatch.setattr(
        memory_context,
        "_locate_provenance_file",
        lambda e: "observations.2026-10.jsonl (archive, activo)",
    )
    monkeypatch.setattr(
        "sys.argv", ["memory_context.py", "--why", "obs-test-why-entry"]
    )

    rc = memory_context.main()
    out = capsys.readouterr().out

    assert rc == 0
    for field, value in (
        ("source", "session-test"),
        ("source_ticket", "WOT-2026-049j"),
        ("evidence", "commit abc123, test unitario"),
        ("timestamp", "2026-10-09T00:00:00+00:00"),
        ("confidence", "0.9"),
        ("impact", "medium"),
        ("domain", "testing"),
    ):
        assert f"- {field}: {value}" in out, (
            f"campo de procedencia {field!r} no aparece con su valor real en "
            "la salida de --why"
        )
    assert "observations.2026-10.jsonl (archive, activo)" in out, (
        "--why debe declarar en que fichero vive la entrada (DoD a)"
    )
    assert entry["signal"] in out


def test_why_declares_absent_field_instead_of_inventing_one(monkeypatch, capsys):
    """DoD (b): un campo de procedencia AUSENTE en la entrada real se declara
    '(ausente)', nunca se omite en silencio ni se inventa un valor.

    MUTACION ALCANZABLE: cambiar '(ausente)' por simplemente no imprimir la
    linea del campo ausente hace que este test caiga (ya no habria linea
    '- evidence: ...' en absoluto que contenga el marcador).
    """
    entry = _entry(evidence=None, impact=None)
    del entry["evidence"]
    del entry["impact"]
    monkeypatch.setattr(memory_context, "recall_observations", lambda **k: [entry])
    monkeypatch.setattr(
        memory_context,
        "_locate_provenance_file",
        lambda e: "desconocido (no se encontro en ningun fichero escaneado)",
    )
    monkeypatch.setattr(
        "sys.argv", ["memory_context.py", "--why", "obs-test-why-entry"]
    )

    rc = memory_context.main()
    out = capsys.readouterr().out

    assert rc == 0
    assert "- evidence: (ausente)" in out
    assert "- impact: (ausente)" in out


def test_why_fails_closed_on_unknown_id_or_topic(monkeypatch, capsys):
    """Un id/topic que no existe en el pool sale con rc=1 y un mensaje claro,
    nunca cae a un recall silencioso ni imprime una entrada equivocada --
    mismo contrato fail-closed que ya tiene `--recall --id`.
    """
    monkeypatch.setattr(memory_context, "recall_observations", lambda **k: [])
    monkeypatch.setattr(
        "sys.argv", ["memory_context.py", "--why", "obs-does-not-exist"]
    )

    rc = memory_context.main()
    err = capsys.readouterr().err

    assert rc == 1
    assert "No lesson with id/topic" in err


def test_why_matches_by_topic_when_not_an_obs_id(monkeypatch, capsys):
    """Un valor que NO empieza por 'obs-' se interpreta como TOPIC: el DoD dice
    "para un id/topic dado", y puede devolver varias entradas bajo el mismo
    topic -- no se exige unicidad.
    """
    one = _entry(id="obs-a", topic="mi-topic", signal="primera senal del topic buscado")
    two = _entry(id="obs-b", topic="mi-topic", signal="segunda senal distinta")
    other = _entry(id="obs-c", topic="otro-topic", signal="senal de un topic DISTINTO")
    monkeypatch.setattr(
        memory_context, "recall_observations", lambda **k: [one, two, other]
    )
    monkeypatch.setattr(memory_context, "_locate_provenance_file", lambda e: "x")
    monkeypatch.setattr("sys.argv", ["memory_context.py", "--why", "mi-topic"])

    rc = memory_context.main()
    out = capsys.readouterr().out

    assert rc == 0
    assert one["signal"] in out
    assert two["signal"] in out
    assert other["signal"] not in out


def test_locate_provenance_file_finds_record_by_key_in_archive(
    tmp_path: Path, monkeypatch
):
    """DoD (a), la mitad que `_print_why` no ejercita directamente: dado un
    `record_key` real `(topic, source_ticket)`, `_locate_provenance_file`
    busca en el archive REAL en disco (no en un mock) y nombra el fichero de
    mes correcto.

    Entrada con la forma REAL de un record del archive (DoD c).
    """
    archive_dir = tmp_path / ".agent" / "runtime" / "memory" / "archive"
    archive_dir.mkdir(parents=True)
    record = {
        "topic": "una-leccion-real",
        "source_ticket": "WOT-2026-049j",
        "signal": "contenido de la leccion",
        "timestamp": "2026-10-01T00:00:00+00:00",
    }
    (archive_dir / "observations.2026-10.jsonl").write_text(
        json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    monkeypatch.setattr("runtime.project_root.resolve_project_root", lambda: tmp_path)
    monkeypatch.setattr("bus.memory_loader._resolve_motor_root", lambda: None)
    monkeypatch.setattr(
        "bus.memory_loader._get_observations_file",
        lambda: tmp_path / "does-not-exist.jsonl",
    )

    result = memory_context._locate_provenance_file(record)

    assert result == "observations.2026-10.jsonl (archive, activo)", (
        f"se esperaba nombrar el fichero de archive real que contiene el "
        f"record_key, se obtuvo: {result!r}"
    )


def test_locate_provenance_file_reports_unknown_when_absent_everywhere(
    tmp_path: Path, monkeypatch
):
    """MUTACION ALCANZABLE del DoD (a): si el record no existe en NINGUN
    fichero escaneado, se declara 'desconocido', nunca se asume un origen.
    """
    monkeypatch.setattr("runtime.project_root.resolve_project_root", lambda: tmp_path)
    monkeypatch.setattr("bus.memory_loader._resolve_motor_root", lambda: None)
    monkeypatch.setattr(
        "bus.memory_loader._get_observations_file",
        lambda: tmp_path / "does-not-exist.jsonl",
    )

    result = memory_context._locate_provenance_file(
        {"topic": "nunca-existio", "source_ticket": None}
    )

    assert result.startswith("desconocido"), (
        "un record ausente de todas las rutas escaneadas debe declararse "
        f"desconocido, no inventarse un origen: {result!r}"
    )
