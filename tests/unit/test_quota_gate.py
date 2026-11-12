import builtins
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
GATE_PATH = ROOT / "scripts" / "flight" / "quota_gate.py"
REGISTRY_PATH = ROOT / "scripts" / "flight" / "registry_ops.py"


def load_module(name, path):
    """Load a module from the repository path used by the test.

    Before: ``path`` identifies a Python module in this repository.
    During: import the module through its file location without changing sys.path.
    After: return the loaded module for direct contract-level tests.
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


quota_gate = load_module("quota_gate_test_module", GATE_PATH)
registry_ops = load_module("registry_ops_quota_gate_test_module", REGISTRY_PATH)


def roster_for(*, status="VERIFICADA", accounts=None, supervisor="supervisor"):
    """Build a small roster fixture for quota gate tests.

    Before: callers provide optional map status, account names, and supervisor identity.
    During: create the minimum quota/account_policy structure consumed by the gate.
    After: return an independent JSON-like roster dictionary.
    """
    accounts = accounts or {
        "target-instance": "target",
        "supervisor-instance": supervisor,
    }
    return {
        "quota": {
            "soft_freeze_block_pct": 92,
            "hard_stop_block_pct": 97,
            "account_policy": {
                "provider_map": accounts,
                "provider_map_status": status,
                "supervisor_account": supervisor,
                "preferred_account": "preferred",
                "harbor_account": "harbor",
            },
        }
    }


def payload_for(*entries):
    """Build a schema-v2-like payload with the supplied account entries.

    Before: entries are account dictionaries containing at least ``cuenta`` and ``block_pct``.
    During: add the stable schema and harmless codex/rc metadata.
    After: return a payload accepted by ``evaluate`` and ``pick_account``.
    """
    return {
        "QUOTA_JSON_SCHEMA": 2,
        "accounts": [
            {
                "cuenta": entry["cuenta"],
                "en_censo": True,
                "estado_operativo": "NORMAL",
                "calidad_medida": "OK",
                "block_pct": entry["block_pct"],
                "ventana_peor": "weekly",
                "ventanas": [],
            }
            | entry
            for entry in entries
        ],
        "codex": [{"primary_pct": 0, "weekly_pct": 0, "resets": [], "medido": True}],
        "rc_info": 0,
        "fallbacks": [],
    }


def test_quota_gate_extremos_umbral_por_cuenta(tmp_path, monkeypatch, capsys):
    """Verify OK, freeze, and hard thresholds with exact return codes.

    Before: the destination account is mapped and freshly measured at boundary values.
    During: evaluate three independent payloads against roster thresholds.
    After: return codes are exactly 0, 4, and 5 at the specified boundaries.
    """
    roster = roster_for()
    for pct, expected in ((89.99, 0), (91, 0), (92, 4), (96.99, 4), (97, 5)):
        result = quota_gate.evaluate(
            roster,
            payload_for(
                {"cuenta": "target", "block_pct": pct},
                {"cuenta": "supervisor", "block_pct": 10},
            ),
            "target-instance",
        )
        assert result["rc"] == expected
    flight_dir = tmp_path / "flight"
    flight_dir.mkdir()
    (flight_dir / "flight_roster.json").write_text(json.dumps(roster), encoding="utf-8")
    measured = payload_for(
        {"cuenta": "target", "block_pct": 10},
        {"cuenta": "supervisor", "block_pct": 10},
    )
    monkeypatch.setattr(quota_gate, "measure", lambda _flight_dir: measured)
    rc = quota_gate.main(
        ["--target-instance", "target-instance", "--flight-dir", str(flight_dir)]
    )
    output = capsys.readouterr().out.splitlines()
    assert rc == 0
    assert "QUOTA_GATE target=target-instance" in output[0]
    assert "cuenta=target" in output[0]
    assert "block_pct=10" in output[0]
    assert "rc=0" in output[0]
    filtered = json.loads(output[1])
    assert len(filtered["accounts"]) == 1
    assert filtered["accounts"][0]["cuenta"] == "target"
    assert filtered["gate"]["target_instance"] == "target-instance"
    assert filtered["gate"]["cuenta_destino"] == "target"
    assert filtered["gate"]["rc"] == 0


def test_quota_gate_extremos_no_resoluble_y_stale():
    """Verify unresolved destinations and stale measurements fail closed.

    Before: one target is absent from the provider map and one mapped target is stale.
    During: evaluate both cases without invoking a real monitor subprocess.
    After: each result has exact rc 9 and an actionable reason.
    """
    roster = roster_for()
    unresolved = quota_gate.evaluate(
        roster, payload_for({"cuenta": "other", "block_pct": 10}), "missing"
    )
    stale_payload = payload_for(
        {"cuenta": "target", "block_pct": 10, "calidad_medida": "STALE"}
    )
    stale = quota_gate.evaluate(roster, stale_payload, "target-instance")
    assert unresolved["rc"] == 9
    assert "no resoluble" in unresolved["motivo"]
    assert stale["rc"] == 9
    assert stale["motivo"] == "stale"


def test_quota_gate_medida_fresca_subprocess(tmp_path, monkeypatch):  # noqa: C901
    """Verify fresh quota_tick invocation and subprocess failure labeling.

    Before: a temporary flight directory contains only the fixture roster.
    During: spy on the real subprocess call site and reject cache-file opens.
    After: argv is complete and a nonzero tick rc becomes exact rc 9 with its rc.
    """
    flight_dir = tmp_path / "flight"
    flight_dir.mkdir()
    (flight_dir / "flight_roster.json").write_text("{}", encoding="utf-8")
    calls = []

    valid_stdout = json.dumps(
        {
            "QUOTA_JSON_SCHEMA": 2,
            "accounts": [{"cuenta": "other", "calidad_medida": "OK", "block_pct": 99}],
        }
    )

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return type("Completed", (), {"returncode": 5, "stdout": valid_stdout})()

    monkeypatch.setattr(quota_gate.subprocess, "run", fake_run)
    real_open = builtins.open

    def guarded_open(*args, **kwargs):
        if "quota_last" in str(args[0]):
            raise AssertionError("quota_last.txt must not be opened")
        return real_open(*args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded_open)
    measured = quota_gate.measure(flight_dir)
    assert measured["QUOTA_JSON_SCHEMA"] == 2
    assert measured["accounts"][0]["block_pct"] == 99
    assert calls
    assert str(calls[0][0][0]).endswith("python.exe") or str(calls[0][0][0]).endswith(
        "python"
    )
    assert "quota_tick.py" in str(calls[0][0][1])
    assert "--json" in calls[0][0]
    assert "--flight-dir" in calls[0][0]

    def timeout_run(*args, **kwargs):
        raise quota_gate.subprocess.TimeoutExpired(
            cmd="quota_tick.py", timeout=quota_gate.TIMEOUT_S
        )

    monkeypatch.setattr(quota_gate.subprocess, "run", timeout_run)
    with pytest.raises(quota_gate.NoMedidoError, match="TimeoutExpired"):
        quota_gate.measure(flight_dir)

    stale_stdout = json.dumps(
        {
            "QUOTA_JSON_SCHEMA": 2,
            "accounts": [{"cuenta": "brabander", "calidad_medida": "STALE"}],
        }
    )

    def stale_run(*args, **kwargs):
        return type("Completed", (), {"returncode": 9, "stdout": stale_stdout})()

    monkeypatch.setattr(quota_gate.subprocess, "run", stale_run)
    with pytest.raises(quota_gate.NoMedidoError, match="brabander"):
        quota_gate.measure(flight_dir)

    other_hard_stdout = json.dumps(
        {
            "QUOTA_JSON_SCHEMA": 2,
            "accounts": [{"cuenta": "other", "calidad_medida": "OK", "block_pct": 99}],
        }
    )

    def other_hard_run(*args, **kwargs):
        return type("Completed", (), {"returncode": 9, "stdout": other_hard_stdout})()

    monkeypatch.setattr(quota_gate.subprocess, "run", other_hard_run)
    with pytest.raises(quota_gate.NoMedidoError) as other_hard_error:
        quota_gate.measure(flight_dir)
    assert str(other_hard_error.value) == (
        "quota_tick subprocess rc=9: sin cuentas stale/no medidas"
    )
    assert "no JSON parseable" not in str(other_hard_error.value)

    def invalid_run(*args, **kwargs):
        return type("Completed", (), {"returncode": 9, "stdout": "not json"})()

    monkeypatch.setattr(quota_gate.subprocess, "run", invalid_run)
    with pytest.raises(quota_gate.NoMedidoError, match="salida no JSON parseable"):
        quota_gate.measure(flight_dir)

    def invalid_hard_run(*args, **kwargs):
        return type(
            "Completed",
            (),
            {
                "returncode": 5,
                "stdout": json.dumps(
                    {"accounts": [{"cuenta": "other", "block_pct": 10}]}
                ),
            },
        )()

    monkeypatch.setattr(quota_gate.subprocess, "run", invalid_hard_run)
    with pytest.raises(quota_gate.NoMedidoError) as invalid_hard_error:
        quota_gate.measure(flight_dir)
    assert str(invalid_hard_error.value) == (
        "quota_tick subprocess rc=5: salida sin JSON v2 con accounts"
    )

    invalid_schema_stdout = json.dumps(
        {"accounts": [{"cuenta": "other", "calidad_medida": "OK", "block_pct": 10}]}
    )

    def invalid_schema_run(*args, **kwargs):
        return type(
            "Completed", (), {"returncode": 9, "stdout": invalid_schema_stdout}
        )()

    monkeypatch.setattr(quota_gate.subprocess, "run", invalid_schema_run)
    with pytest.raises(quota_gate.NoMedidoError) as invalid_schema_9:
        quota_gate.measure(flight_dir)
    assert str(invalid_schema_9.value) == (
        "quota_tick subprocess rc=9: salida sin JSON v2 con accounts"
    )

    def invalid_schema_zero_run(*args, **kwargs):
        return type(
            "Completed", (), {"returncode": 0, "stdout": invalid_schema_stdout}
        )()

    monkeypatch.setattr(quota_gate.subprocess, "run", invalid_schema_zero_run)
    with pytest.raises(quota_gate.NoMedidoError) as invalid_schema_0:
        quota_gate.measure(flight_dir)
    assert str(invalid_schema_0.value) == (
        "quota_tick subprocess rc=0: salida sin JSON v2 con accounts"
    )


def test_quota_gate_supervision_strict(tmp_path, monkeypatch, capsys):
    """Verify strict supervision is default, healthy, and fail-closed when absent.

    Before: destination and supervisor entries are independently measurable.
    During: evaluate hard, healthy, and missing-supervisor payloads without a flag.
    After: exact codes are 5, 0, and 9, with supervision reasons where applicable.
    """
    roster = roster_for()
    hard = quota_gate.evaluate(
        roster,
        payload_for(
            {"cuenta": "target", "block_pct": 10},
            {"cuenta": "supervisor", "block_pct": 98},
        ),
        "target-instance",
    )
    healthy = quota_gate.evaluate(
        roster,
        payload_for(
            {"cuenta": "target", "block_pct": 10},
            {"cuenta": "supervisor", "block_pct": 50},
        ),
        "target-instance",
    )
    hard_at_limit = quota_gate.evaluate(
        roster,
        payload_for(
            {"cuenta": "target", "block_pct": 10},
            {"cuenta": "supervisor", "block_pct": 97},
        ),
        "target-instance",
    )
    missing = quota_gate.evaluate(
        roster, payload_for({"cuenta": "target", "block_pct": 10}), "target-instance"
    )
    assert hard["rc"] == 5
    assert "supervision" in hard["motivo"]
    assert healthy["rc"] == 0
    assert hard_at_limit["rc"] == 5
    assert "supervision" in hard_at_limit["motivo"]
    assert missing["rc"] == 9
    assert missing["motivo"] == "supervision: sin medicion"

    numeric_target = quota_gate.evaluate(
        roster,
        payload_for(
            {"cuenta": "target", "block_pct": "12"},
            {"cuenta": "supervisor", "block_pct": 10},
        ),
        "target-instance",
    )
    numeric_supervisor = quota_gate.evaluate(
        roster,
        payload_for(
            {"cuenta": "target", "block_pct": 10},
            {"cuenta": "supervisor", "block_pct": "12"},
        ),
        "target-instance",
    )
    assert numeric_target["rc"] == 9
    assert "block_pct no numerico" in numeric_target["motivo"]
    assert numeric_supervisor["rc"] == 9
    assert "block_pct no numerico" in numeric_supervisor["motivo"]

    flight_dir = tmp_path / "flight"
    flight_dir.mkdir()
    (flight_dir / "flight_roster.json").write_text(json.dumps(roster), encoding="utf-8")
    main_payload = payload_for(
        {"cuenta": "target", "block_pct": 10},
        {"cuenta": "supervisor", "block_pct": 98},
    )
    monkeypatch.setattr(quota_gate, "measure", lambda _flight_dir: main_payload)
    default_rc = quota_gate.main(
        ["--target-instance", "target-instance", "--flight-dir", str(flight_dir)]
    )
    default_output = capsys.readouterr().out
    assert default_rc == 5
    assert "motivo=supervision" in default_output

    roster_without_supervisor = json.loads(json.dumps(roster))
    policy = roster_without_supervisor["quota"]["account_policy"]
    del policy["supervisor_account"]
    roster_without_supervisor["quota"]["reserve_for_orquestadora"] = (
        "coordinadora de prosa"
    )
    roster_with_reserve = json.loads(json.dumps(roster_without_supervisor))
    roster_with_reserve["quota"]["reserve_for_orquestadora"] = "supervisor"
    reserve_ok = quota_gate.evaluate(
        roster_with_reserve,
        payload_for(
            {"cuenta": "target", "block_pct": 10},
            {"cuenta": "supervisor", "block_pct": 10},
        ),
        "target-instance",
    )
    reserve_hard = quota_gate.evaluate(
        roster_with_reserve,
        payload_for(
            {"cuenta": "target", "block_pct": 10},
            {"cuenta": "supervisor", "block_pct": 98},
        ),
        "target-instance",
    )
    assert reserve_ok["rc"] == 0
    assert reserve_ok["supervision"]["cuenta"] == "supervisor"
    assert reserve_hard["rc"] == 5
    assert "supervision" in reserve_hard["motivo"]
    explicit_payload = payload_for(
        {"cuenta": "target", "block_pct": 10},
        {"cuenta": "supervisor", "block_pct": 98},
    )
    explicit = quota_gate.evaluate(
        roster_without_supervisor,
        explicit_payload,
        "target-instance",
        supervisor_instance="supervisor-instance",
    )
    no_explicit = quota_gate.evaluate(
        roster_without_supervisor, explicit_payload, "target-instance"
    )
    assert explicit["rc"] == 5
    assert "supervision" in explicit["motivo"]
    assert no_explicit["rc"] == 9
    assert "supervision" in no_explicit["motivo"]


def test_quota_gate_mapa_reserva_strict_reserva():
    """Verify unverified-map reserve quality for a named account.

    Before: the roster marks its provider map as unverified.
    During: evaluate a named mapped account and a strict-map invocation.
    After: reserve is visible and normal by default, while strict-map returns 9.
    """
    roster = roster_for(status="NO VERIFICADA POR CONFIG OFICIAL")
    payload = payload_for(
        {"cuenta": "target", "block_pct": 10}, {"cuenta": "supervisor", "block_pct": 10}
    )
    reserve = quota_gate.evaluate(roster, payload, "target-instance")
    assert reserve["rc"] == 0
    assert reserve["cuenta"]["calidad_medida"] == "RESERVA"
    assert "mapa no verificado: RESERVA" in reserve["motivo"]


def test_quota_gate_mapa_reserva_strict():
    """Verify strict-map rejection and an unmapped destination.

    Before: the roster marks its provider map as unverified.
    During: evaluate strict reserve and an outside-map target.
    After: both outcomes are exact rc 9 fail-closed results.
    """
    roster = roster_for(status="NO VERIFICADA POR CONFIG OFICIAL")
    payload = payload_for(
        {"cuenta": "target", "block_pct": 10}, {"cuenta": "supervisor", "block_pct": 10}
    )
    strict = quota_gate.evaluate(roster, payload, "target-instance", strict_map=True)
    outside = quota_gate.evaluate(roster, payload, "outside")
    assert strict["rc"] == 9
    assert strict["motivo"] == "mapa no verificado (strict-map)"
    assert outside["rc"] == 9


def _alta_args(rc, *, role="implantacion", code="IM-1"):
    """Build complete parser-shaped alta arguments for receipt tests.

    Before: ``rc`` is the optional quota gate return code.
    During: populate every optional field consumed by ``_session_for_alta``.
    After: return a namespace equivalent to the alta parser result.
    """
    return SimpleNamespace(
        code=code,
        role=role,
        slot="s",
        thread_id="t",
        started="2026-11-12T10:00:00+01:00",
        status="ACTIVA",
        celda='{"builder":"codex"}',
        nota=None,
        started_nota=None,
        supersedes=None,
        reporta_a=None,
        brief=None,
        generation=None,
        launched_by=None,
        worktree=None,
        quota_gate_rc=rc,
        quota_gate_waiver=None,
    )


def test_alta_quota_gate_receipt(tmp_path, capsys):
    """Verify implantacion nonzero receipt enforcement and waiver recording.

    Before: a temporary registry receives valid IM alta arguments and a cell.
    During: invoke the production alta session builder for rejecting, waiving, and absent rc.
    After: nonzero rc rejects without waiver, waiver is recorded, and omission is marked.
    """
    base = _alta_args(5)
    with pytest.raises(registry_ops.RegistryError, match="exige --quota-gate-waiver"):
        registry_ops._session_for_alta(base, {"sessions": []})
    base.quota_gate_waiver = "manual"
    waived = registry_ops._session_for_alta(base, {"sessions": []})
    assert waived["quota_gate_receipt"] == {"rc": 5, "waiver": "manual"}
    for empty_waiver in ("", "   "):
        base.quota_gate_waiver = empty_waiver
        with pytest.raises(registry_ops.RegistryError) as empty_error:
            registry_ops._session_for_alta(base, {"sessions": []})
        assert empty_error.value.code == 2
    base.quota_gate_waiver = "manual"
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"sessions": []}), encoding="utf-8")
    base.registry = str(registry)
    base.apply = False
    base.quota_gate_waiver = None
    with pytest.raises(registry_ops.RegistryError) as dry_run_error:
        registry_ops._handle_alta(base)
    assert dry_run_error.value.code == 2
    base.quota_gate_waiver = "manual"
    assert registry_ops._handle_alta(base) == 0
    dry_run = json.loads(capsys.readouterr().out)
    assert dry_run["quota_gate_receipt"] == {"rc": 5, "waiver": "manual"}

    triaje = _alta_args(5, role="triaje", code="TR-1")
    with pytest.raises(registry_ops.RegistryError) as triaje_error:
        registry_ops._session_for_alta(triaje, {"sessions": []})
    assert triaje_error.value.code == 2
    triaje.quota_gate_waiver = "triage manual"
    triaje_session = registry_ops._session_for_alta(triaje, {"sessions": []})
    assert triaje_session["quota_gate_receipt"] == {
        "rc": 5,
        "waiver": "triage manual",
    }

    coord = _alta_args(5, role="coord", code="CO-1")
    coord_session = registry_ops._session_for_alta(coord, {"sessions": []})
    assert coord_session["quota_gate_receipt"] == {"rc": 5}


def test_alta_quota_gate_receipt_ausente():
    """Verify an implantacion alta without quota rc remains visible as absent.

    Before: a complete implantacion alta has no quota gate rc or waiver.
    During: construct the session through the production helper.
    After: the exact visible receipt is the string ``ausente``.
    """
    base = _alta_args(None)
    absent = registry_ops._session_for_alta(base, {"sessions": []})
    assert absent["quota_gate_receipt"] == "ausente"


def test_registry_parser_apply_receipt(tmp_path, capsys):
    """Verify real alta parser choices and durable quota receipt persistence.

    Before: a temporary registry, ledger, and active roster support a coord alta.
    During: parse accepted/rejected choices and apply rc 5 through the real CLI.
    After: rc 5 is accepted and persisted, while rc 7 exits argparse with 2.
    """
    registry = tmp_path / "registry.json"
    ledger = tmp_path / "ledger.jsonl"
    roster = tmp_path / "roster.json"
    registry.write_text(json.dumps({"sessions": []}), encoding="utf-8")
    roster.write_text(
        json.dumps({"active_roles": {"orquestador": {"estado": "ACTIVO"}}}),
        encoding="utf-8",
    )
    common = [
        "alta",
        "--registry",
        str(registry),
        "--ledger",
        str(ledger),
        "--roster",
        str(roster),
        "--code",
        "CO-2",
        "--role",
        "coord",
        "--slot",
        "coord-2",
        "--thread-id",
        "thread-co-2",
        "--started",
        "2026-11-12T10:00:00+01:00",
        "--status",
        "ACTIVE",
        "--by",
        "test",
        "--reason",
        "quota gate",
    ]
    parsed = registry_ops._parser().parse_args([*common, "--quota-gate-rc", "5"])
    assert parsed.quota_gate_rc == 5
    with pytest.raises(SystemExit) as invalid_choice:
        registry_ops._parser().parse_args([*common, "--quota-gate-rc", "7"])
    assert invalid_choice.value.code == 2
    assert registry_ops.main([*common, "--quota-gate-rc", "5", "--apply"]) == 0
    capsys.readouterr()
    stored = json.loads(registry.read_text(encoding="utf-8"))["sessions"][0]
    assert stored["quota_gate_receipt"] == {"rc": 5}


@pytest.mark.skipif(
    sys.platform != "win32", reason="quota_tick monitor path is Windows PowerShell"
)
def test_cli_monitor_false_boundaries(tmp_path):
    """Exercise the real gate and quota_tick with a temporary PowerShell monitor.

    Before: a Windows flight has a schema-compatible roster and fake monitor script.
    During: run the real CLI over destination and supervision boundary scenarios.
    After: exact process return codes and human-readable reasons are asserted.
    """
    flight_dir = tmp_path / "flight"
    flight_dir.mkdir()
    roster = {
        "quota": {
            "soft_freeze_block_pct": 92,
            "hard_stop_block_pct": 97,
            "account_policy": {
                "provider_map": {
                    "claudeAgent": "brabander",
                    "claudeAgent_alvarovans": "alvarovans",
                },
                "provider_map_status": "VERIFICADA",
                "preferred_account": "brabander",
                "harbor_account": "alvarovans",
                "supervisor_account": "alvarovans",
            },
        }
    }
    (flight_dir / "flight_roster.json").write_text(json.dumps(roster), encoding="utf-8")
    monitor = tmp_path / "fake_monitor.ps1"
    monitor.write_text(
        "param([switch]$Json)\nWrite-Output $env:FAKE_QUOTA_JSON\n", encoding="ascii"
    )
    gate_path = ROOT / "scripts" / "flight" / "quota_gate.py"
    environment = os.environ.copy()
    environment["CC_USAGE_MONITOR_PS1"] = str(monitor)
    scenarios = (
        (10, 10, 0, "motivo=ok"),
        (91, 10, 0, "motivo=ok"),
        (95, 10, 4, "motivo=freeze"),
        (98, 10, 5, "motivo=hard"),
        (10, 98, 5, "motivo=supervision"),
    )
    for destination, supervisor, expected_rc, expected_reason in scenarios:
        environment["FAKE_QUOTA_JSON"] = json.dumps(
            {
                "accounts": {
                    "brabander": {
                        "block_pct": destination,
                        "stale": False,
                        "block_window": "weekly",
                    },
                    "alvarovans": {
                        "block_pct": supervisor,
                        "stale": False,
                        "block_window": "weekly",
                    },
                }
            }
        )
        result = subprocess.run(
            [
                sys.executable,
                str(gate_path),
                "--target-instance",
                "claudeAgent",
                "--flight-dir",
                str(flight_dir),
            ],
            capture_output=True,
            text=True,
            env=environment,
            check=False,
        )
        assert result.returncode == expected_rc
        assert f"rc={expected_rc}" in result.stdout
        assert expected_reason in result.stdout


def test_quota_gate_norma_avisos():
    """Verify the operational documentation and redirection safety invariant.

    Before: the real gate and stop-notices documentation are present in the repository.
    During: inspect the usage command, rc table, and every documented gate command.
    After: all required rows exist and no gate usage line contains redirection.
    """
    avisos = (
        ROOT / ".agent" / "rules" / "common" / "avisos_parada_vuelo.md"
    ).read_text(encoding="utf-8")
    gate_doc = GATE_PATH.read_text(encoding="utf-8")
    assert "## Gate de cupo por cuenta destino (quota_gate.py)" in avisos
    assert (
        "python scripts/flight/quota_gate.py --target-instance <providerInstanceId> --flight-dir <VUELO>"
        in avisos
    )
    assert "| 0 | OK/RESERVA: pct < 92 |" in avisos
    assert (
        "| 3 | AVISO upstream de quota_tick (pct >= 90): no es veredicto del gate; "
        "el veredicto sale de la cuenta destino (pct < 92 => 0) |"
    ) in avisos
    assert "| 4 | FREEZE: 92 <= pct < 97 |" in avisos
    assert "| 5 | HARD: pct >= 97 (o supervision >= 97) |" in avisos
    assert (
        "| 9 | NO_MEDIDO fail-closed: timeout, rc de subprocess fuera de {0,3,4,5}, "
        "salida sin JSON v2 con accounts, cuenta no resoluble, stale/sin medir, "
        "block_pct no numerico o mapa estricto |"
    ) in avisos
    for line in avisos.splitlines() + gate_doc.splitlines():
        if "quota_gate.py" in line or ("quota_gate" in line and "python " in line):
            assert " > " not in line
    assert "> ruta" not in gate_doc
