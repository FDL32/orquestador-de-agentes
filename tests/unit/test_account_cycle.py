"""Tests for the pure mother/daughter account cycle guard and its CLI."""

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest


PATH = Path(
    os.environ.get("ACCOUNT_CYCLE_UNDER_TEST")
    or Path(__file__).resolve().parents[2] / "scripts" / "flight" / "account_cycle.py"
)


def load_module():
    """Load the implementation from the motor path.

    Before: the test needs the current account-cycle source.
    During: import the file without executing its CLI.
    After: return the loaded module.
    """
    spec = importlib.util.spec_from_file_location("account_cycle_ut", PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def state(**changes):
    """Create a state fixture from the implementation's initial state.

    Before: optional fields describe a state-machine transition.
    During: copy the initial state and apply overrides.
    After: return an isolated state dictionary.
    """
    module = load_module()
    value = json.loads(json.dumps(module.ESTADO_INICIAL))
    value.update(changes)
    return value


def readings(
    pct=50,
    weekly_pct=20,
    now=1000,
    resets=2000,
    weekly_resets=3000,
    refugio_pct=50,
    refugio_weekly_pct=50,
    roster_sha12=None,
):
    """Build validated-looking readings for pure decision tests."""
    return {
        "pct": pct,
        "weekly_pct": weekly_pct,
        "resets": resets,
        "weekly_resets": weekly_resets,
        "checked_at": now,
        "refugio_pct": refugio_pct,
        "refugio_weekly_pct": refugio_weekly_pct,
        "roster_sha12": roster_sha12,
    }


def action_pair(result):
    """Return the action type and executor from a decision result."""
    return result[1]["tipo"], result[1]["ejecutor"]


def test_m03_rem5_y_proyeccion_mueven_madre_a_refugio():
    """Before: the preferred account has either low remaining quota or a falling trend.

    During: decide three boundary cases.
    After: only strict remaining/projection breaches move the mother.
    """
    module = load_module()
    now = 1000
    rows = [
        (readings(95, now=now), state(), "MOVE_MADRE_REFUGE", "hija"),
        (
            readings(90, now=now),
            state(lecturas=[{"ts": now - 300, "pct": 90}]),
            "NONE",
            None,
        ),
        (
            readings(90, now=now),
            state(lecturas=[{"ts": now - 300, "pct": 87}]),
            "MOVE_MADRE_REFUGE",
            "hija",
        ),
    ]
    for current, old, expected, executor in rows:
        assert action_pair(module.decide(current, old, now, [])) == (expected, executor)


def test_m03_control_tasa_negativa_no_dispara():
    """Before: usage is falling and therefore has no positive burn rate.

    During: decide at exactly ten percent remaining.
    After: the non-positive rate is clamped and no move occurs.
    """
    module = load_module()
    result = module.decide(
        readings(90, now=1000),
        state(lecturas=[{"ts": 700, "pct": 95}]),
        1000,
        [],
    )
    assert action_pair(result) == ("NONE", None)


def test_m04_semanal_bloquea_retorno_hasta_reset():
    """Before: weekly remaining quota latches the refuge.

    During: decide before and after the weekly reset.
    After: return actions are blocked before reset and resume after it.
    """
    module = load_module()
    base = state(madre_en_refugio=True, secuencia_retorno=1, despertar_en=900)
    before = module.decide(
        readings(50, 97, now=1940, weekly_resets=2000), base, 1940, []
    )
    after = module.decide(
        readings(50, 97, now=2060, weekly_resets=2000), base, 2060, []
    )
    control = module.decide(
        readings(50, 50, now=1940, weekly_resets=2000), base, 1940, []
    )
    assert before[1]["tipo"] not in {"MOVE_MADRE_PREFERIDA", "MOVE_HIJA_PREFERIDA"}
    assert after[1]["tipo"] == "MOVE_MADRE_PREFERIDA"
    assert control[1]["tipo"] == "MOVE_MADRE_PREFERIDA"


def test_m04_semanal_baja_fija_madre_en_refugio():
    """Before: the mother is in the initial state while weekly quota is latched.

    During: evaluate a fresh low-weekly reading.
    After: the mother moves to refuge.
    """
    module = load_module()
    result = module.decide(
        readings(50, 97, now=1940, weekly_resets=2000), state(), 1940, []
    )
    assert action_pair(result) == ("MOVE_MADRE_REFUGE", "hija")


@pytest.mark.parametrize(
    "current, events, reset, quota",
    [
        (readings(100, 50, resets=2000), [], 2000, "5h"),
        (readings(50, 100, weekly_resets=3000), [], 3000, "semanal"),
        (readings(100, 100, resets=2000, weekly_resets=3000), [], 3000, "semanal"),
        (readings(99, 50, resets=2000), ["limite"], 2000, "5h"),
        (readings(99, 60, weekly_resets=3000), ["limite_semanal"], 3000, "semanal"),
    ],
)
def test_m05_agotada_programa_despertar_wake_exacto(current, events, reset, quota):
    """Before: the daughter is not in refuge and a quota exhaustion is observed.

    During: apply readings or an explicit limit event.
    After: the mother moves the daughter and schedules reset plus one minute.
    """
    module = load_module()
    result = module.decide(current, state(madre_en_refugio=True), 1000, events)
    assert result[1]["tipo"] == "MOVE_HIJA_REFUGE_Y_PROGRAMAR_DESPERTAR"
    assert result[1]["ejecutor"] == "madre"
    assert result[1]["wake_at"] == reset + 60
    assert result[0]["agotada"] == quota and result[0]["despertar_en"] == reset + 60


def test_m05_control_99_sin_evento_no_produce_movimiento():
    """Before: usage is below exhaustion and no limit event exists.

    During: decide from the mother-refuge state.
    After: no account movement is requested.
    """
    module = load_module()
    result = module.decide(readings(99, 50), state(madre_en_refugio=True), 1000, [])
    assert action_pair(result) == ("NONE", None)


def test_m06_secuencia_reintento_y_retorno():
    """Before: the daughter is exhausted and waiting at a reset wake time.

    During: retry five times, then test the healthy return sequence and reset event.
    After: retry/alert and both return moves occur in the prescribed order.
    """
    module = load_module()
    current = state(
        madre_en_refugio=True,
        hija_en_refugio=True,
        agotada="5h",
        despertar_en=1000,
        reintentos=0,
    )
    for expected in range(1, 6):
        prev_wake = current["despertar_en"]
        now = current["despertar_en"] + 1
        current, action = module.decide(readings(90, 20, now=now), current, now, [])
        assert (
            action["tipo"] == "REINTENTAR_DESPERTAR"
            and current["reintentos"] == expected
        )
        assert action["wake_at"] == prev_wake + 120
        assert current["despertar_en"] == prev_wake + 120
    now = current["despertar_en"] + 1
    current, action = module.decide(readings(90, 20, now=now), current, now, [])
    assert action["tipo"] == "AVISAR_RESET_NO_OBSERVADO"
    now += 900
    current, action = module.decide(
        readings(80, 20, now=now), state(**{**current, "reintentos": 0}), now, []
    )
    assert action["tipo"] == "MOVE_HIJA_PREFERIDA" and current["secuencia_retorno"] == 1
    now += 900
    current, action = module.decide(readings(80, 20, now=now), current, now, [])
    assert (
        action["tipo"] == "MOVE_MADRE_PREFERIDA" and current["secuencia_retorno"] == 2
    )
    current, action = module.decide(
        readings(80, 20, now=now + 900), current, now + 900, ["madre_en_preferida"]
    )
    assert action["tipo"] == "NONE" and current["secuencia_retorno"] == 0


def test_m06_control_wake_futuro_da_esperar():
    """Before: wake time is in the future.

    During: decide once.
    After: the guard returns ESPERAR with no executor.
    """
    module = load_module()
    result = module.decide(
        readings(80, 20, now=940),
        state(
            madre_en_refugio=True, hija_en_refugio=True, agotada="5h", despertar_en=1000
        ),
        940,
        [],
    )
    assert action_pair(result) == ("ESPERAR", None)


def run_cli(tmp_path, cache, state_path, *extra):
    """Run the thin CLI in a subprocess and return its completed process."""
    cache_path = tmp_path / "cache.json"
    if cache is not None:
        account = cache.get("alvarovans")
        if isinstance(account, dict):
            checked = account.get("checked_at")
            checked = checked if isinstance(checked, (int, float)) else time.time()
            account.setdefault("resets", checked + 1000)
            account.setdefault("weekly_resets", checked + 2000)
        cache_path.write_text(json.dumps(cache), encoding="utf-8")
    return subprocess.run(
        [
            sys.executable,
            str(PATH),
            "--cache",
            str(cache_path),
            "--estado",
            str(state_path),
            *extra,
        ],
        capture_output=True,
        text=True,
        check=False,
        env={
            key: value
            for key, value in os.environ.items()
            if key not in {"PYTHONIOENCODING", "PYTHONUTF8"}
        },
    )


@pytest.mark.parametrize("kind", ["absent", "stale", "future", "bad_pct"])
def test_m07_cli_fail_closed(tmp_path, kind):
    """Before: the cache is absent, stale, or contains a non-numeric percentage.

    During: invoke the CLI without saving.
    After: rc 9 emits one NONE JSON line and does not create state.
    """
    state_path = tmp_path / "state.json"
    now = 1000
    cache = (
        None
        if kind == "absent"
        else {
            "alvarovans": {
                "pct": 95,
                "weekly_pct": 20,
                "resets": 2000,
                "weekly_resets": 3000,
                "checked_at": (
                    now - 1500
                    if kind == "stale"
                    else now + 1500
                    if kind == "future"
                    else now - 60
                ),
            }
        }
    )
    if kind == "bad_pct":
        cache["alvarovans"]["pct"] = "no-num"
    result = run_cli(tmp_path, cache, state_path)
    payload = json.loads(result.stdout)
    assert result.returncode == 9 and payload["accion"] == "NONE"
    if kind == "absent":
        assert not (tmp_path / "cache.json").exists()
    assert not state_path.exists()


def test_m07_control_cache_fresca_da_accion(tmp_path):
    """Before: a fresh cache reports less than ten percent remaining.

    During: invoke the CLI.
    After: it requests the mother refuge move.
    """
    now = time.time()
    cache = {
        "alvarovans": {
            "pct": 95,
            "weekly_pct": 20,
            "resets": now + 1000,
            "weekly_resets": now + 2000,
            "checked_at": now - 60,
        }
    }
    result = run_cli(tmp_path, cache, tmp_path / "state.json")
    assert (
        result.returncode == 10
        and json.loads(result.stdout)["accion"] == "MOVE_MADRE_REFUGE"
    )


def test_m08_cli_sin_guardar_no_escribe_y_con_guardar_escribe_atomico(tmp_path):
    """Before: an existing state file is known and cache data is fresh.

    During: invoke once without and once with saving.
    After: only the saving invocation changes JSON state and leaves no temp file.
    """
    now = time.time()
    cache = {
        "alvarovans": {
            "pct": 95,
            "weekly_pct": 20,
            "resets": now + 1000,
            "weekly_resets": now + 2000,
            "checked_at": now - 60,
        }
    }
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps(load_module().ESTADO_INICIAL), encoding="utf-8")
    before = hashlib.sha256(state_path.read_bytes()).hexdigest()
    result = run_cli(tmp_path, cache, state_path)
    assert (
        result.returncode == 10
        and hashlib.sha256(state_path.read_bytes()).hexdigest() == before
    )
    result = run_cli(tmp_path, cache, state_path, "--guardar")
    assert (
        result.returncode == 10
        and hashlib.sha256(state_path.read_bytes()).hexdigest() != before
    )
    assert json.loads(state_path.read_text(encoding="utf-8"))["lecturas"]
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "cache.json",
        "state.json",
    ]


def test_r3m1_cache_y_estado_con_bom_se_leen(tmp_path):
    """Before: cache and state are UTF-8 JSON files prefixed by a BOM.

    During: run the CLI with a realistic cache shape and then a BOM-free control.
    After: neither cache encoding is treated as a measurement failure.
    """
    now = datetime.now(tz=timezone.utc)
    entry = {
        "pct": 95,
        "resets": now.timestamp() + 1000,
        "weekly_pct": 20,
        "weekly_resets": now.timestamp() + 2000,
        "windows": [
            {"id": "session", "label": "5h", "pct": 95, "resets": now.isoformat()}
        ],
        "checked_at": now.astimezone().isoformat(),
    }
    cache_path = tmp_path / "cache.json"
    state_path = tmp_path / "state.json"
    cache_bytes = json.dumps({"alvarovans": entry}).encode("utf-8")
    cache_path.write_bytes(b"\xef\xbb\xbf" + cache_bytes)
    state_path.write_bytes(b'\xef\xbb\xbf{"version":1}')
    result = run_cli(tmp_path, None, state_path)
    assert result.returncode == 10
    cache_path.write_bytes(cache_bytes)
    assert run_cli(tmp_path, None, state_path).returncode == 10


@pytest.mark.parametrize(
    "field",
    ["pct", "weekly_pct", "refugio_pct", "refugio_weekly_pct"],
)
def test_r3m2_negativos_rechazados(tmp_path, field):
    """Before: one measured quota field is negative.

    During: invoke the CLI with that poisoned reading.
    After: fail-closed returns rc 9 and NONE.
    """
    account = {"pct": 50, "weekly_pct": 20, "checked_at": time.time()}
    cache = {"alvarovans": account, "brabander": {"pct": 50, "weekly_pct": 20}}
    if field.startswith("refugio"):
        cache["brabander"]["weekly_pct" if field.endswith("weekly_pct") else "pct"] = -1
    else:
        account[field] = -200 if field == "pct" else -1
    result = run_cli(tmp_path, cache, tmp_path / "state.json")
    assert result.returncode == 9 and json.loads(result.stdout)["accion"] == "NONE"


def test_r3m2_envenenamiento_dos_ticks(tmp_path):
    """Before: the first tick has a negative preferred quota.

    During: run a saving poisoned tick, then replace it with a fresh healthy cache.
    After: the first tick writes no state and the second tick is NONE, not a move.
    """
    state_path = tmp_path / "state.json"
    poisoned = {
        "alvarovans": {"pct": -200, "weekly_pct": 20, "checked_at": time.time() - 150}
    }
    first = run_cli(tmp_path, poisoned, state_path, "--guardar")
    assert first.returncode == 9 and not state_path.exists()
    healthy = {"alvarovans": {"pct": 50, "weekly_pct": 20, "checked_at": time.time()}}
    second = run_cli(tmp_path, healthy, state_path, "--guardar")
    assert second.returncode == 0
    assert json.loads(second.stdout)["accion"] == "NONE"


def test_r3m3_env_flight_roster_path_gana(tmp_path, monkeypatch, capsys):
    """Before: both roster environment variables point to different files.

    During: save once with both variables and once with only the alias.
    After: FLIGHT_ROSTER_PATH wins, then FLIGHT_ROSTER is used as fallback.
    """
    module = load_module()
    now = time.time()
    cache = tmp_path / "cache.json"
    cache.write_text(
        json.dumps(
            {
                "alvarovans": {
                    "pct": 50,
                    "weekly_pct": 20,
                    "resets": now + 1000,
                    "weekly_resets": now + 2000,
                    "checked_at": now,
                }
            }
        ),
        encoding="utf-8",
    )
    roster_a = tmp_path / "a.json"
    roster_b = tmp_path / "b.json"
    roster_a.write_text("A", encoding="utf-8")
    roster_b.write_text("B", encoding="utf-8")
    monkeypatch.setenv("FLIGHT_ROSTER_PATH", str(roster_a))
    monkeypatch.setenv("FLIGHT_ROSTER", str(roster_b))
    state_a = tmp_path / "state_a.json"
    assert (
        module.main(["--cache", str(cache), "--estado", str(state_a), "--guardar"]) == 0
    )
    capsys.readouterr()
    monkeypatch.delenv("FLIGHT_ROSTER_PATH")
    state_b = tmp_path / "state_b.json"
    assert (
        module.main(["--cache", str(cache), "--estado", str(state_b), "--guardar"]) == 0
    )
    capsys.readouterr()
    assert (
        json.loads(state_a.read_text(encoding="utf-8"))["roster_sha12"]
        == hashlib.sha256(b"A").hexdigest()[:12]
    )
    assert (
        json.loads(state_b.read_text(encoding="utf-8"))["roster_sha12"]
        == hashlib.sha256(b"B").hexdigest()[:12]
    )


def test_r3m4_latch_sin_reset_avisar():
    """Before: weekly latch is active but has no observed reset.

    During: decide at an already reached wake time, then with a future reset.
    After: missing reset alerts; an observed future reset still waits.
    """
    module = load_module()
    base = state(
        madre_en_refugio=True,
        hija_en_refugio=True,
        agotada="semanal",
        despertar_en=900,
        secuencia_retorno=1,
    )
    missing = module.decide(readings(80, 97, weekly_resets=None), base, 1000, [])
    future = module.decide(readings(80, 97, weekly_resets=2000), base, 1000, [])
    assert action_pair(missing) == ("AVISAR_RESET_NO_OBSERVADO", "madre")
    assert action_pair(future) == ("ESPERAR", None)


def test_r3m5_checked_at_iso_naive_rc9(tmp_path):
    """Before: checked_at is first naive ISO and then timezone-aware ISO.

    During: invoke the CLI for both cache encodings.
    After: naive ISO fails closed while aware ISO remains measurable.
    """
    cache = {
        "alvarovans": {
            "pct": 95,
            "weekly_pct": 20,
            "checked_at": datetime.now().isoformat(),
        }
    }
    result = run_cli(tmp_path, cache, tmp_path / "state.json")
    assert result.returncode == 9 and json.loads(result.stdout)["accion"] == "NONE"
    cache["alvarovans"]["checked_at"] = datetime.now(tz=timezone.utc).isoformat()
    assert run_cli(tmp_path, cache, tmp_path / "state.json").returncode == 10


def test_r3m6_estado_v1_claves_faltantes_completado(tmp_path):
    """Before: the persisted version-one state only contains its version.

    During: run a fresh preferred reading.
    After: missing state keys are completed and the normal move is returned.
    """
    state_path = tmp_path / "state.json"
    state_path.write_text('{"version":1}', encoding="utf-8")
    cache = {"alvarovans": {"pct": 95, "weekly_pct": 20, "checked_at": time.time()}}
    result = run_cli(tmp_path, cache, state_path)
    assert result.returncode == 10
    assert json.loads(result.stdout)["accion"] == "MOVE_MADRE_REFUGE"


def test_r4m1_secuencia_1_retorna_tras_600():
    module = load_module()
    result = module.decide(
        readings(80, 50),
        state(
            madre_en_refugio=True,
            hija_en_refugio=True,
            agotada="5h",
            despertar_en=1000,
            secuencia_retorno=1,
        ),
        1900,
        [],
    )
    assert action_pair(result) == ("MOVE_MADRE_PREFERIDA", "hija")


def test_r4m1_latch_tras_600_da_esperar():
    module = load_module()
    result = module.decide(
        readings(80, 97, weekly_resets=5000),
        state(
            madre_en_refugio=True, hija_en_refugio=True, agotada="5h", despertar_en=1000
        ),
        1900,
        [],
    )
    assert action_pair(result) == ("ESPERAR", None)


def test_r5m1_retorno_tardio_y_dne_resoluble():
    module = load_module()
    late = module.decide(
        readings(80, 50),
        state(
            madre_en_refugio=True, hija_en_refugio=True, agotada="5h", despertar_en=1000
        ),
        1900,
        [],
    )
    assert action_pair(late) == ("MOVE_HIJA_PREFERIDA", "madre")
    assert late[0]["motivo"] == "retorno-tardio"
    dne = module.decide(
        readings(90, 50),
        state(
            madre_en_refugio=True, hija_en_refugio=True, agotada="5h", despertar_en=1000
        ),
        1900,
        [],
    )
    assert action_pair(dne) == ("DESPERTAR_NO_EJECUTADO", "madre")
    resolved = module.decide(readings(80, 50), dne[0], 1900, [])
    assert action_pair(resolved) == ("MOVE_HIJA_PREFERIDA", "madre")


def test_r5m2_cadencia_real():
    module = load_module()
    base = state(
        madre_en_refugio=True, hija_en_refugio=True, agotada="5h", despertar_en=1000
    )
    first = module.decide(readings(80, 50, now=1000), base, 1000, [])
    second = module.decide(readings(80, 50, now=1300), first[0], 1300, [])
    third = module.decide(
        readings(80, 50, now=2140), second[0], 2140, ["madre_en_preferida"]
    )
    fourth = module.decide(readings(80, 50, now=3400), third[0], 3400, [])
    assert first[1]["tipo"] == "MOVE_HIJA_PREFERIDA"
    assert second[1]["tipo"] == "MOVE_MADRE_PREFERIDA"
    assert third[1]["tipo"] == "NONE" and fourth[1]["tipo"] == "NONE"
    missed = module.decide(readings(80, 50, now=1840), base, 1840, [])
    missed_next = module.decide(readings(80, 50, now=3400), missed[0], 3400, [])
    assert missed[1]["tipo"] == "MOVE_HIJA_PREFERIDA"
    assert missed_next[1]["tipo"] == "MOVE_MADRE_PREFERIDA"


def test_r4m2_ventana_reseteada_devuelve_madre():
    module = load_module()
    base = state(madre_en_refugio=True)
    assert action_pair(module.decide(readings(50, 50), base, 1000, [])) == (
        "MOVE_MADRE_PREFERIDA",
        "hija",
    )
    assert (
        action_pair(module.decide(readings(86, 50), base, 1000, []))[0]
        != "MOVE_MADRE_PREFERIDA"
    )
    assert action_pair(module.decide(readings(95, 50), state(), 1000, [])) == (
        "MOVE_MADRE_REFUGE",
        "hija",
    )
    assert (
        action_pair(
            module.decide(readings(50, 97, weekly_resets=5000), base, 1000, [])
        )[0]
        != "MOVE_MADRE_PREFERIDA"
    )


def test_r4m2_escenario_completo_e1_luego_reset():
    module = load_module()
    now = 1000
    first = module.decide(
        readings(90, 50, now=now),
        state(lecturas=[{"ts": now - 300, "pct": 87}]),
        now,
        [],
    )
    second = module.decide(
        readings(50, 50, now=now + 60), first[0], now + 60, ["madre_en_refugio"]
    )
    assert first[1]["tipo"] == "MOVE_MADRE_REFUGE"
    assert action_pair(second) == ("MOVE_MADRE_PREFERIDA", "hija")


def test_r4m3_latch_5h_no_bloquea_hija():
    module = load_module()
    base = state(
        madre_en_refugio=True, hija_en_refugio=True, agotada="5h", despertar_en=1000
    )
    first = module.decide(readings(80, 97, weekly_resets=5000), base, 1001, [])
    second = module.decide(readings(80, 97, weekly_resets=5000), first[0], 1001, [])
    weekly = module.decide(
        readings(80, 97, weekly_resets=5000),
        state(**{**base, "agotada": "semanal"}),
        1001,
        [],
    )
    assert action_pair(first) == ("MOVE_HIJA_PREFERIDA", "madre")
    assert action_pair(second)[0] != "MOVE_MADRE_PREFERIDA"
    assert action_pair(weekly)[0] != "MOVE_HIJA_PREFERIDA"


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), True, 1795132800000])
def test_r4m4_resets_invalidos_rc9(tmp_path, bad):
    now = time.time()
    cache = {
        "alvarovans": {
            "pct": 95,
            "weekly_pct": 20,
            "resets": bad,
            "weekly_resets": now + 1000,
            "checked_at": now,
        }
    }
    state_path = tmp_path / "state.json"
    result = run_cli(tmp_path, cache, state_path, "--guardar")
    assert result.returncode == 9 and json.loads(result.stdout)["accion"] == "NONE"
    assert not state_path.exists()


def test_r4m4_estado_con_nan_interno_no_emite_nan(tmp_path):
    now = time.time()
    state_path = tmp_path / "state.json"
    state_path.write_text(
        '{"version":1,"lecturas":[{"ts":NaN,"pct":50}]}', encoding="utf-8"
    )
    cache = {
        "alvarovans": {
            "pct": 95,
            "weekly_pct": 20,
            "resets": now + 1000,
            "weekly_resets": now + 2000,
            "checked_at": now,
        }
    }
    result = run_cli(tmp_path, cache, state_path, "--guardar")
    json.loads(
        result.stdout,
        parse_constant=lambda constant: (_ for _ in ()).throw(ValueError(constant)),
    )
    assert result.returncode == 9
    assert "NaN" in state_path.read_text(encoding="utf-8")


def test_r4m5_roster_bom_mismo_sha(tmp_path):
    module = load_module()
    plain = tmp_path / "plain.json"
    bom = tmp_path / "bom.json"
    plain.write_bytes(b'{"roster":1}')
    bom.write_bytes(b"\xef\xbb\xbf" + plain.read_bytes())
    assert module._roster_sha12(plain) == module._roster_sha12(bom)


@pytest.mark.parametrize("field", ["refugio_pct", "refugio_weekly_pct"])
def test_m10_madre_agotada_en_refugio_avisa(field):
    """Before: the mother is in refuge and the refuge account is exhausted.

    During: exhaust either the five-hour or weekly refuge quota.
    After: the mother receives an alert without a movement.
    """
    module = load_module()
    result = module.decide(
        readings(**{field: 100}), state(madre_en_refugio=True), 1000, []
    )
    assert result[1] == {
        "tipo": "MADRE_AGOTADA_EN_REFUGIO",
        "ejecutor": "madre",
        "wake_at": None,
    }


@pytest.mark.parametrize("event", [None, "limite"])
def test_m10_ambas_agotadas_avisa(event):
    """Before: the preferred and refuge accounts are exhausted.

    During: use either a limit event or a 100 percent preferred reading.
    After: the guard emits the terminal alert and no MOVE action.
    """
    module = load_module()
    events = [event] if event else []
    result = module.decide(
        readings(99 if event else 100, refugio_pct=100), state(), 1000, events
    )
    assert result[1] == {
        "tipo": "AMBAS_AGOTADAS",
        "ejecutor": "madre",
        "wake_at": None,
    }
    assert not result[1]["tipo"].startswith("MOVE_")


def test_m10_control_madre_sana_en_refugio_no_avisa():
    """Before: both accounts are healthy while the mother is in refuge.

    During: evaluate the normal state machine.
    After: no terminal alert or movement is emitted.
    """
    module = load_module()
    result = module.decide(
        readings(refugio_pct=50, refugio_weekly_pct=50),
        state(madre_en_refugio=True, hija_en_refugio=True),
        1000,
        [],
    )
    assert action_pair(result) == ("NONE", None)


def test_m11_roster_distinto_aborta():
    """Before: the persisted roster identity differs from the current roster.

    During: decide with otherwise healthy readings.
    After: the cycle aborts before any movement.
    """
    module = load_module()
    result = module.decide(
        readings(roster_sha12="cccc2222dddd"),
        state(roster_sha12="aaaa1111bbbb"),
        1000,
        [],
    )
    assert action_pair(result) == ("ABORTAR_CICLO_Y_AVISAR", "madre")


def test_m11_control_roster_igual_sigue_maquina():
    """Before: the persisted and current roster identities match.

    During: evaluate a preferred reading below ten percent remaining.
    After: the normal refuge movement remains available.
    """
    module = load_module()
    result = module.decide(
        readings(95, roster_sha12="aaaa1111bbbb"),
        state(roster_sha12="aaaa1111bbbb"),
        1000,
        [],
    )
    assert action_pair(result) == ("MOVE_MADRE_REFUGE", "hija")


def test_m12_evento_limite_sin_100_declara_agotada_y_99_no():
    """Before: a 99 percent reading is paired with or without a limit event.

    During: decide both cases while the mother is already in refuge.
    After: only the identified limit event schedules the daughter refuge move.
    """
    module = load_module()
    with_event = module.decide(
        readings(99), state(madre_en_refugio=True), 1000, ["limite"]
    )
    without_event = module.decide(readings(99), state(madre_en_refugio=True), 1000, [])
    assert with_event[1]["tipo"] == "MOVE_HIJA_REFUGE_Y_PROGRAMAR_DESPERTAR"
    assert with_event[1]["wake_at"] == 2060
    assert action_pair(without_event) == ("NONE", None)


@pytest.mark.parametrize(
    "history, current, expected, reason",
    [
        (
            [{"ts": 1000, "pct": 50}],
            readings(76),
            "MOVE_MADRE_REFUGE",
            "suelo-1pt-min",
        ),
        ([{"ts": 1000, "pct": 50}], readings(74), "NONE", "suelo-1pt-min"),
        (
            [{"ts": 1500, "pct": 50}],
            readings(76),
            "MOVE_MADRE_REFUGE",
            "suelo-1pt-min",
        ),
        (
            [{"ts": 700, "pct": 50, "reset": 2000}],
            readings(76, resets=3000),
            "MOVE_MADRE_REFUGE",
            "suelo-1pt-min",
        ),
    ],
)
def test_m13_suelo_proyeccion_parejas_invalidas(history, current, expected, reason):
    """Before: the only historical pair is invalid for projection.

    During: decide with repeated, decreasing, or cross-reset timestamps.
    After: the one-point-per-minute floor controls the decision and reason.
    """
    module = load_module()
    result = module.decide(current, state(lecturas=history), current["checked_at"], [])
    assert result[1]["tipo"] == expected
    assert result[0]["tasa_razon"] == reason


def test_m13_control_pareja_valida_tasa_cero_rem5_30():
    """Before: a same-reset pair is valid and has zero usage slope.

    During: decide at thirty percent remaining.
    After: no refuge move occurs and the valid-pair reason is persisted.
    """
    module = load_module()
    current = readings(70, resets=2000)
    result = module.decide(
        current,
        state(lecturas=[{"ts": 700, "pct": 70, "reset": 2000}]),
        1000,
        [],
    )
    assert action_pair(result) == ("NONE", None)
    assert result[0]["tasa_razon"] == "pareja-valida-tasa-no-positiva"
