"""Before: specify the public measurement CLI with isolated JSONL fixtures.

During: exercise measurement, inventory, comparison, validation, and read-only
behaviour through ``main``.

After: every ticket invariant has an executable regression test without using
live transcript folders.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from scripts.flight.measure_tick_cost import main


def _write_jsonl(
    folder: Path, records: list[dict], name: str = "session.jsonl"
) -> Path:
    """Before: receive records for one synthetic transcript.

    During: serialize each record as one JSON line in the temporary folder.

    After: return the created transcript path.
    """
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )
    return path


def _usage(
    input_tokens: int, cache_read: int = 0, creation: int = 0, output: int = 1
) -> dict:
    """Before: receive explicit token components.

    During: build the transcript usage object used by Claude records.

    After: return a complete usage mapping.
    """
    return {
        "input_tokens": input_tokens,
        "cache_read_input_tokens": cache_read,
        "cache_creation_input_tokens": creation,
        "output_tokens": output,
    }


def _turn(
    co: int,
    usages: list[dict],
    model: str = "model-a",
    timestamp: str = "2026-01-01T00:00:00Z",
    tool: bool = False,
) -> list[dict]:
    """Before: receive a pulse definition.

    During: emit its opening user record, assistant records, and optional tool use.

    After: return valid records for one pulse.
    """
    records: list[dict] = [
        {
            "type": "user",
            "timestamp": timestamp,
            "message": {"content": f"LATIDO CO-{co}"},
        }
    ]
    if tool:
        records.append(
            {
                "type": "assistant",
                "timestamp": timestamp,
                "message": {
                    "model": model,
                    "content": [{"type": "tool_use", "name": "Read", "id": f"t{co}"}],
                    "usage": usages[0],
                },
            }
        )
        records.append(
            {
                "type": "user",
                "timestamp": timestamp,
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": f"t{co}",
                            "content": "salida",
                        }
                    ]
                },
            }
        )
        usages = usages[1:]
    records.extend(
        {
            "type": "assistant",
            "timestamp": timestamp,
            "message": {"model": model, "content": [], "usage": usage},
        }
        for usage in usages
    )
    return records


def _measure(tmp_path: Path, folders: list[Path], *extra: str) -> dict:
    """Before: receive fixture folders and CLI options.

    During: invoke the public measurement mode and load its JSON output.

    After: return the parsed measurement artifact.
    """
    out = tmp_path / "out.json"
    if out.exists():
        out.unlink()
    argv = [arg for folder in folders for arg in ("--project-dir", str(folder))]
    argv.extend(extra)
    argv.extend(("--out", str(out)))
    rc = main(argv)
    assert rc == 0
    return json.loads(out.read_text(encoding="utf-8"))


def test_mutation_m01_dos_carpetas_suma_8(tmp_path: Path) -> None:
    """Before: create five and three pulses plus non-pulse turns.

    During: measure both distinct folders.

    After: all eight pulses and their account breakdown are present.
    """
    first = tmp_path / "cuenta-a"
    second = tmp_path / "cuenta-b"
    first_records: list[dict] = []
    for i in range(1, 6):
        first_records.extend(_turn(i, [_usage(10, output=i)]))
    first_records.extend([{"type": "user", "message": {"content": "normal"}}] * 2)
    second_records: list[dict] = []
    for i in range(6, 9):
        second_records.extend(_turn(i, [_usage(10, output=i)]))
    second_records.extend([{"type": "user", "message": {"content": "normal"}}] * 2)
    _write_jsonl(first, first_records)
    _write_jsonl(second, second_records)
    result = _measure(tmp_path, [first, second])
    assert result["meta"]["n"] == 8
    assert {
        key: value["n"] for key, value in result["agregados"]["por_cuenta"].items()
    } == {"cuenta-a": 5, "cuenta-b": 3}


def test_mutation_m02_campos_exactos(tmp_path: Path) -> None:
    """Before: create a pulse with hand-calculated usage.

    During: measure it through the CLI.

    After: all six token and call fields equal their exact expected values.
    """
    folder = tmp_path / "cuenta"
    _write_jsonl(
        folder, _turn(7, [_usage(100, 20, 30, 9), _usage(130, 40, 10, 11)], tool=True)
    )
    pulse = _measure(tmp_path, [folder])["pulsos"][0]
    assert {
        key: pulse[key]
        for key in (
            "llamadas",
            "salida",
            "ctx0",
            "ctx1",
            "crecimiento",
            "fresco",
            "cache_read",
        )
    } == {
        "llamadas": 1,
        "salida": 20,
        "ctx0": 150,
        "ctx1": 180,
        "crecimiento": 30,
        "fresco": 270,
        "cache_read": 60,
    }


def test_mutation_m03_rango_y_desglose(tmp_path: Path) -> None:
    """Before: create three COs and two models.

    During: apply an inclusive CO range.

    After: only CO 2 and 3 remain and account/model groups sum to the total.
    """
    folder = tmp_path / "cuenta"
    records = (
        _turn(1, [_usage(1)], model="m1")
        + _turn(2, [_usage(2)], model="m1")
        + _turn(3, [_usage(3)], model="m2")
        + _turn(4, [_usage(4)], model="m2")
    )
    _write_jsonl(folder, records)
    result = _measure(tmp_path, [folder], "--co-from", "2", "--co-to", "3")
    assert [pulse["co"] for pulse in result["pulsos"]] == [2, 3]
    assert result["meta"]["n"] == 2
    assert (
        sum(group["n"] for group in result["agregados"]["por_cuenta_modelo"].values())
        == 2
    )


def test_mutation_m04_p90_n5(tmp_path: Path) -> None:
    """Before: create groups with two and six observations.

    During: measure all observations.

    After: small-group p90 is null and six-item p90 is the indexed value.
    """
    folder = tmp_path / "cuenta"
    records: list[dict] = []
    for i in range(2):
        records += _turn(i + 1, [_usage(10, cache_read=i + 1, output=1)], model="small")
    for i in range(6):
        records += _turn(
            i + 10, [_usage(10, cache_read=i + 1, output=1)], model="large"
        )
    _write_jsonl(folder, records)
    result = _measure(tmp_path, [folder])
    small = result["agregados"]["por_modelo"]["small"]
    large = result["agregados"]["por_modelo"]["large"]
    assert small["cache_read"]["p90"] is None
    assert large["cache_read"]["p90"] == 5
    assert large["cache_read"]["p90"] >= large["cache_read"]["mediana"]


def test_mutation_m05_sin_respuesta(tmp_path: Path) -> None:
    """Before: create two pulses without usage-bearing assistants.

    During: measure them.

    After: both count in the denominator and neither enters numeric aggregates.
    """
    folder = tmp_path / "cuenta"
    _write_jsonl(
        folder, _turn(1, [], model="<synthetic>") + _turn(2, [], model="<synthetic>")
    )
    result = _measure(tmp_path, [folder])
    assert result["meta"]["n"] == 2
    assert result["meta"]["n_sin_respuesta"] == 2
    assert result["agregados"]["global"]["cache_read"]["n"] == 0


def test_mutation_m06_inventario_clases(tmp_path: Path) -> None:
    """Before: create a known UTF-8 inventory fixture.

    During: run inventory mode.

    After: historical bytes, reference counts, unique references, and protocol occurrences match.
    """
    path = tmp_path / "latido.md"
    text = (
        "[HISTORICO]A\n[HISTORICO]B\n[HISTORICO]C\n"
        + " ".join(f"CO-{i} (mcp:{i:032x})" for i in [1, 2, 3, 4, 5, 6, 1, 2, 3, 4])
        + "\nPROTOCOLO_POSTCOMPACTACION_CO-1.md\n"
    )
    path.write_text(text, encoding="utf-8")
    out = tmp_path / "inventory.json"
    assert main(["--inventario", str(path), "--out", str(out)]) == 0
    result = json.loads(out.read_text(encoding="utf-8"))["inventario"]
    assert result["n_bloques_historico"] == 3
    assert result["por_clase"]["historico"]["bytes"] == len(
        b"[HISTORICO]A\n[HISTORICO]B\n[HISTORICO]C"
    )
    assert result["referencias"] == {"total": 10, "unicas": 6}
    assert result["por_clase"]["protocolo"]["ocurrencias"] == 1


def _comparison_file(path: Path, count: int, cache: int) -> None:
    """Before: receive a target artifact path and pulse count.

    During: write comparable synthetic pulse records for both states.

    After: the artifact is ready for comparator mode.
    """
    pulses = [
        {
            "co": i,
            "cuenta": "cuenta",
            "modelo": "m",
            "estado": state,
            "ctx0": 100000,
            "vueltas": 2 + cache,
            "cache_read": cache,
        }
        for state in ("activo", "reposo")
        for i in range(count)
    ]
    path.write_text(json.dumps({"pulsos": pulses}), encoding="utf-8")


def test_mutation_m07_comparador_30(tmp_path: Path) -> None:
    """Before: prepare 29-pair and 30-pair artifacts.

    During: compare both thresholds.

    After: 29 is insufficient without numbers and 30 reports differences per state.
    """
    for count, expected, has_numbers in [
        (29, "INSUFICIENTE", False),
        (30, "COMPARABLE", True),
    ]:
        current = tmp_path / f"v{count}.json"
        candidate = tmp_path / f"c{count}.json"
        out = tmp_path / f"o{count}.json"
        _comparison_file(current, count, 1)
        _comparison_file(candidate, count, 3)
        assert (
            main(["--comparar", str(current), str(candidate), "--out", str(out)]) == 0
        )
        comparison = json.loads(out.read_text(encoding="utf-8"))["comparacion"]
        assert comparison["veredicto"] == expected
        for state in ("activo", "reposo"):
            assert ("diff_cache_read" in comparison[state]) is has_numbers


def test_mutation_m08_solo_lectura(tmp_path: Path) -> None:
    """Before: hash a private input folder.

    During: run measurement with an output outside the folder.

    After: inputs are byte-identical and only the requested output is new.
    """
    folder = tmp_path / "entrada"
    source = _write_jsonl(folder, _turn(1, [_usage(2)]))
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    existing = {item.relative_to(tmp_path) for item in tmp_path.rglob("*")}
    _measure(tmp_path, [folder])
    after = hashlib.sha256(source.read_bytes()).hexdigest()
    assert before == after
    assert {item.relative_to(tmp_path) for item in tmp_path.rglob("*")} - existing == {
        Path("out.json")
    }


def test_mutation_m11_fraccion_cache_read(tmp_path: Path) -> None:
    """Before: create three pulses and two non-pulse usage turns in one session.

    During: measure session cache attribution.

    After: pulse cache fraction is exact and the five-session threshold remains n/a.
    """
    folder = tmp_path / "cuenta"
    records: list[dict] = []
    for i in range(3):
        records += _turn(i + 1, [_usage(1, cache_read=10)])
    records += [
        {"type": "user", "message": {"content": "normal"}},
        {
            "type": "assistant",
            "message": {"model": "m", "usage": _usage(1, cache_read=20)},
        },
    ]
    _write_jsonl(folder, records)
    result = _measure(tmp_path, [folder])
    session = result["meta"]["sesiones"][0]
    assert session["cache_read_pulsos"] == 30
    assert session["cache_read_total"] == 50
    assert session["fraccion"] == pytest.approx(0.6)
    assert result["agregados"]["m11"]["mediana"] is None


def test_mutation_m12_bytes_utf8(tmp_path: Path) -> None:
    """Before: create accented tool output and an unmatched tool use.

    During: measure command output sizes.

    After: sizes are UTF-8 byte counts and missing results are null.
    """
    folder = tmp_path / "cuenta"
    opening = {
        "type": "user",
        "timestamp": "2026-01-01T00:00:00Z",
        "message": {"content": "LATIDO CO-1"},
    }
    assistant = {
        "type": "assistant",
        "message": {
            "model": "m",
            "content": [
                {"type": "tool_use", "name": "Read", "id": "a"},
                {"type": "tool_use", "name": "Read", "id": "b"},
            ],
            "usage": _usage(1),
        },
    }
    result = {
        "type": "user",
        "message": {
            "content": [
                {"type": "tool_result", "tool_use_id": "a", "content": "áé\nsegunda"}
            ]
        },
    }
    _write_jsonl(folder, [opening, assistant, result])
    orders = _measure(tmp_path, [folder])["pulsos"][0]["ordenes"]
    assert orders == [
        {
            "tool": "Read",
            "bytes_totales": len("áé\nsegunda".encode()),
            "bytes_primera_linea": len("áé".encode()),
        },
        {"tool": "Read", "bytes_totales": None, "bytes_primera_linea": None},
    ]


def test_estados_estampa_y_fail_closed(tmp_path: Path) -> None:
    """Before: create a timestamped pulse and state windows.

    During: validate accepted and malformed state files.

    After: timestamps map to states and every malformed file returns rc 2.
    """
    folder = tmp_path / "cuenta"
    _write_jsonl(folder, _turn(1, [_usage(1)], timestamp="2026-01-01T01:00:00Z"))
    states = tmp_path / "states.json"
    states.write_text(
        json.dumps(
            {
                "ventanas": [
                    {
                        "desde": "2026-01-01T00:00:00Z",
                        "hasta": "2026-01-01T02:00:00Z",
                        "estado": "activo",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    assert (
        _measure(tmp_path, [folder], "--estados", str(states))["pulsos"][0]["estado"]
        == "activo"
    )
    for value in [
        "{}",
        '{"ventanas":[{"desde":"bad","hasta":"2026-01-01T02:00:00Z","estado":"activo"}]}',
        '{"ventanas":[{"desde":"2026-01-01T02:00:00Z","hasta":"2026-01-01T01:00:00Z","estado":"reposo"}]}',
        '{"ventanas":[{"desde":"2026-01-01T00:00:00Z","hasta":"2026-01-01T02:00:00Z","estado":"other"}]}',
    ]:
        states.write_text(value, encoding="utf-8")
        assert (
            main(
                [
                    "--project-dir",
                    str(folder),
                    "--estados",
                    str(states),
                    "--out",
                    str(tmp_path / f"bad-{len(value)}.json"),
                ]
            )
            == 2
        )


def test_dedupe_y_carpetas_identicas(tmp_path: Path) -> None:
    """Before: prepare repeated, identical-content, and distinct paths.

    During: measure each topology.

    After: realpath duplicates are skipped and content duplicates are reported without merging.
    """
    first = tmp_path / "one"
    second = tmp_path / "two"
    _write_jsonl(first, _turn(1, [_usage(1)]))
    _write_jsonl(second, _turn(1, [_usage(1)]))
    duplicate = _measure(tmp_path, [first, first])
    assert duplicate["meta"]["n"] == 1
    assert duplicate["meta"]["cuenta"] == "n/a"
    assert any("duplicada de" in item for item in duplicate["meta"]["carpetas_leidas"])
    identical = _measure(tmp_path, [first, second])
    assert str(first) in identical["meta"]["carpetas_leidas"]
    assert str(second) in identical["meta"]["carpetas_leidas"]
    assert any(
        "identico contenido" in item for item in identical["meta"]["carpetas_leidas"]
    )
    assert identical["meta"]["cuenta"] == "n/a"
    assert identical["meta"]["cuenta_motivo"] == "cuenta no separable"
    third = tmp_path / "three"
    _write_jsonl(
        third,
        [*_turn(2, [_usage(2)]), {"type": "user", "message": {"content": "different"}}],
    )
    distinct = _measure(tmp_path, [first, third])
    assert distinct["meta"]["cuenta"] == "separable"


def test_compact_boundary_flag(tmp_path: Path) -> None:
    """Before: place a compact boundary inside a pulse.

    During: measure the pulse.

    After: the flag and counter are set while growth is null and other fields remain measured.
    """
    folder = tmp_path / "cuenta"
    records = _turn(1, [_usage(10, cache_read=2), _usage(20, cache_read=3)])
    records.insert(2, {"type": "system", "subtype": "compact_boundary"})
    _write_jsonl(folder, records)
    result = _measure(tmp_path, [folder])
    assert result["pulsos"][0]["compact_boundary"] is True
    assert result["pulsos"][0]["crecimiento"] is None
    assert result["pulsos"][0]["vueltas"] == 2
    assert result["meta"]["n_compactados"] == 1


def test_usage_fail_closed_y_cli(tmp_path: Path) -> None:
    """Before: prepare malformed usage and conflicting CLI modes.

    During: invoke invalid public CLI forms.

    After: each form fails closed with rc 2 and existing output is never overwritten.
    """
    folder = tmp_path / "cuenta"
    _write_jsonl(folder, _turn(1, [{"cache_read_input_tokens": 1, "output_tokens": 1}]))
    assert (
        main(["--project-dir", str(folder), "--out", str(tmp_path / "bad.json")]) == 2
    )
    assert main(["--project-dir", str(folder)]) == 2
    assert (
        main(
            [
                "--inventario",
                str(folder / "x"),
                "--comparar",
                "a",
                "b",
                "--out",
                str(tmp_path / "bad2.json"),
            ]
        )
        == 2
    )
    existing = tmp_path / "existing.json"
    existing.write_text("old", encoding="utf-8")
    assert main(["--project-dir", str(folder), "--out", str(existing)]) == 2


def test_dedupe_message_id_y_pulso_supervision(tmp_path: Path) -> None:
    """Before: repeat one assistant message and add a supervision heartbeat.

    During: measure both transcript shapes through the public CLI.

    After: the repeated message is counted once and the supervision heartbeat is measured.
    """
    folder = tmp_path / "cuenta"
    duplicate = _turn(176, [_usage(100, cache_read=80, creation=20)])
    duplicate.append(duplicate[-1].copy())
    duplicate[-1]["message"] = dict(duplicate[-1]["message"])
    duplicate[-1]["message"]["id"] = "message-1"
    duplicate[-2]["message"]["id"] = "message-1"
    _write_jsonl(folder, duplicate)
    duplicate_result = _measure(tmp_path, [folder])
    assert duplicate_result["pulsos"][0]["vueltas"] == 1
    assert duplicate_result["pulsos"][0]["cache_read"] == 80

    supervision = tmp_path / "supervision"
    _write_jsonl(supervision, _turn(175, [_usage(100, cache_read=80)]))
    records = json.loads(
        "["
        + ",".join(supervision.joinpath("session.jsonl").read_text().splitlines())
        + "]"
    )
    records[0]["message"]["content"] = "LATIDO SUPERVISION CO-175"
    _write_jsonl(supervision, records)
    supervision_result = _measure(tmp_path, [supervision])
    assert supervision_result["meta"]["n"] == 1
    assert supervision_result["pulsos"][0]["co"] == 175

    unrelated = tmp_path / "unrelated"
    _write_jsonl(unrelated, _turn(999, [_usage(10)]))
    unrelated_records = json.loads(
        "["
        + ",".join(unrelated.joinpath("session.jsonl").read_text().splitlines())
        + "]"
    )
    unrelated_records[0]["message"]["content"] = "LATIDO AJENO CO-999"
    _write_jsonl(unrelated, unrelated_records)
    assert _measure(tmp_path, [unrelated])["meta"]["n"] == 0


def test_dedupe_apertura_no_crea_pulso_fantasma(tmp_path: Path) -> None:
    """Before: repeat a heartbeat opening with the same message id.

    During: measure the transcript through the public CLI.

    After: the repeated opening contributes one pulse and one response only.
    """
    folder = tmp_path / "cuenta"
    records = _turn(176, [_usage(100, cache_read=80)])
    records[0]["message"]["id"] = "opening-1"
    repeated_opening = json.loads(json.dumps(records[0]))
    records.insert(1, repeated_opening)
    _write_jsonl(folder, records)
    result = _measure(tmp_path, [folder])
    assert result["meta"]["n"] == 1
    assert result["meta"]["n_sin_respuesta"] == 0
    assert result["pulsos"][0]["vueltas"] == 1


def test_pulso_sin_respuesta_es_despierta(tmp_path: Path) -> None:
    """Before: create a heartbeat opening without a usage-bearing response.

    During: measure the pulse through the public CLI.

    After: it remains in the denominator and is explicitly classified as awake.
    """
    folder = tmp_path / "cuenta"
    _write_jsonl(folder, _turn(176, [], model="<synthetic>"))
    result = _measure(tmp_path, [folder])
    assert result["meta"]["n"] == 1
    assert result["meta"]["n_sin_respuesta"] == 1
    assert result["pulsos"][0]["estado_tick"] == "despierta"


def test_pesos_por_defecto_quedan_declarados(tmp_path: Path) -> None:
    """Before: create one pulse without overriding pricing parameters.

    During: measure it through the public CLI using parser defaults.

    After: the artifact exposes the declared default weights and cost.
    """
    folder = tmp_path / "cuenta"
    _write_jsonl(folder, _turn(176, [_usage(100, cache_read=80, creation=20)]))
    result = _measure(tmp_path, [folder])
    assert result["meta"]["pesos_coste"] == {"cache_read": 0.1, "fresco": 1.0}
    assert result["pulsos"][0]["coste_ponderado"] == pytest.approx(128)


def test_coste_ponderado_usa_pesos_declarados(tmp_path: Path) -> None:
    """Before: create one pulse with fresh and cache-read tokens.

    During: measure it once with unit weights and once with declared prices.

    After: unit weights equal the raw sum and non-unit weights change the result.
    """
    folder = tmp_path / "cuenta"
    _write_jsonl(folder, _turn(176, [_usage(100, cache_read=80, creation=20)]))
    unit = _measure(
        tmp_path,
        [folder],
        "--peso-cache-read",
        "1",
        "--peso-fresco",
        "1",
    )
    priced = _measure(
        tmp_path,
        [folder],
        "--peso-cache-read",
        "0.1",
        "--peso-fresco",
        "2",
    )
    assert unit["pulsos"][0]["coste_ponderado"] == 200
    assert priced["pulsos"][0]["coste_ponderado"] == pytest.approx(248)
    assert priced["meta"]["pesos_coste"] == {
        "cache_read": 0.1,
        "fresco": 2.0,
    }


def test_informe_cache_fria_separa_tiempo_y_compactacion(tmp_path: Path) -> None:
    """Before: create a cold pulse after a compacted earlier pulse.

    During: measure with an explicit fresh-token threshold.

    After: only the cold pulse is reported with elapsed seconds and prior compaction.
    """
    folder = tmp_path / "cuenta"
    first = _turn(
        176,
        [_usage(10, cache_read=2), _usage(20, cache_read=3)],
        timestamp="2026-01-01T00:00:00Z",
    )
    first.insert(2, {"type": "system", "subtype": "compact_boundary"})
    second = _turn(
        176,
        [_usage(100, cache_read=8, creation=200)],
        timestamp="2026-01-01T00:02:00Z",
    )
    _write_jsonl(folder, first + second)
    result = _measure(tmp_path, [folder], "--cache-fria-umbral", "100")
    report = result["cache_fria"]
    assert report["umbral_fresco_tokens"] == 100
    assert [item["fresco"] for item in report["pulsos"]] == [300]
    assert report["pulsos"][0]["segundos_desde_pulso_anterior"] == 120
    assert report["pulsos"][0]["compactacion_previa"] is True
