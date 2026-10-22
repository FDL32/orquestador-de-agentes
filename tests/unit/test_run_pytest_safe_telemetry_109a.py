"""WOT-2026-109a -- run_history: carga de CPU real, tiempo por fichero, pytest ajenos.

Contexto: el juez de suite (`prompts/suite_optimization.md`) necesita separar
codigo de contencion. Antes de esta ficha `cpu_load_pct` era None en TODAS las
filas (la clase CIM consultada no tiene ese atributo) y la cola larga de la
suite (82-87% del wall) no se persistia.

Cada test dice que mutacion lo pone en rojo. Las sondas REALES (contador de
CPU, listado de procesos) se ejecutan contra la maquina, sin parchear
`_run_cmd` ni `_get_wmi_attribute`: es exactamente donde vivia el defecto (un
mock devolvia "50" para un atributo que el SO nunca entrego).
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import run_pytest_safe as rps


# ---------------------------------------------------------------------------
# CPU: formula pura + contadores reales
# ---------------------------------------------------------------------------


class TestCpuLoadBetween:
    def test_known_deltas_give_exact_percentage(self) -> None:
        # 1000 ticks elapsed, 50 of them idle -> 95.0 % busy.
        # Mutation: returning d_idle/d_total (the idle share) gives 5.0.
        assert rps._cpu_load_between((100, 1000), (150, 2000)) == 95.0

    def test_fully_idle_and_fully_busy_window(self) -> None:
        assert rps._cpu_load_between((0, 0), (500, 500)) == 0.0
        assert rps._cpu_load_between((0, 0), (0, 500)) == 100.0

    @pytest.mark.parametrize(
        ("start", "end"),
        [(None, (1, 2)), ((1, 2), None), (None, None), ((5, 10), (5, 10))],
    )
    def test_missing_or_stalled_samples_are_none_not_zero(self, start, end) -> None:
        # A missing sample or a zero-length window must not become "0 % load":
        # the gap has to stay visible to whoever reads run_history.
        assert rps._cpu_load_between(start, end) is None

    def test_result_is_clamped_to_0_100(self) -> None:
        assert rps._cpu_load_between((0, 0), (900, 100)) == 0.0


class TestProcStat:
    def test_idle_is_idle_plus_iowait_and_total_is_the_sum(self) -> None:
        text = "cpu  10 20 30 400 50 6 7 8 0 0\ncpu0 1 1 1 1 1 1 1 1 0 0\n"
        assert rps._parse_proc_stat(text) == (450, 531)

    @pytest.mark.parametrize(
        "text", ["", "cpu0 1 2 3 4 5", "cpu  1 2 x 4 5", "cpu 1 2"]
    )
    def test_malformed_input_is_none(self, text) -> None:
        assert rps._parse_proc_stat(text) is None


class TestRealCpuProbe:
    def test_real_counters_are_monotonic_and_idle_never_exceeds_total(self) -> None:
        first = rps._read_cpu_counters()
        if first is None:
            pytest.skip("this platform exposes no CPU counter source")
        time.sleep(0.05)
        second = rps._read_cpu_counters()
        assert second is not None
        assert 0 <= first[0] <= first[1]
        assert second[0] >= first[0]
        assert second[1] >= first[1]

    def test_real_probe_returns_a_percentage_with_no_errors(self) -> None:
        # Mutation: restoring the old CIM query (Win32_OperatingSystem has no
        # LoadPercentage) makes this return (None, ["cpu_load: WMI query failed"]).
        if rps._read_cpu_counters() is None:
            pytest.skip("this platform exposes no CPU counter source")
        load, errors = rps._probe_cpu_load(window_s=0.2)
        assert errors == []
        assert load is not None
        assert 0.0 <= load <= 100.0


# ---------------------------------------------------------------------------
# Procesos pytest ajenos: tabla pura + listado real con control positivo
# ---------------------------------------------------------------------------

_RUNNER = "python.exe scripts/run_pytest_safe.py --level all"
_PYTEST = "python.exe -m pytest --durations=0 tests -q"


class TestParseProcessTable:
    def test_skips_malformed_lines_and_keeps_empty_command_lines(self) -> None:
        text = "10 1 cmd a b\nnot a row\n\n  11 10  \nx y z\n12 10 python -m pytest"
        assert rps._parse_process_table(text) == [
            (10, 1, "cmd a b"),
            (11, 10, ""),
            (12, 10, "python -m pytest"),
        ]


class TestCountForeignPytest:
    def _table(self):
        return [
            (1, 0, "init"),
            (5, 1, "powershell.exe"),
            (10, 5, _RUNNER),  # THIS runner
            (11, 10, _PYTEST),  # its own pytest child
            (20, 1, _RUNNER),  # foreign session A: runner...
            (21, 20, _PYTEST),  # ...its pytest child...
            (22, 21, _PYTEST),  # ...and the re-exec'd interpreter below it
            (30, 1, _PYTEST),  # foreign session B: bare pytest
            (40, 1, "python.exe other_script.py"),  # unrelated python
        ]

    def test_counts_sessions_not_processes_and_excludes_ourselves(self) -> None:
        # Mutations that turn this red: not excluding own pid / ancestors /
        # descendants (sessions would be 3 or 4); counting every matched process
        # instead of session roots (sessions would be 4).
        result = rps._count_foreign_pytest(self._table(), own_pid=10)
        assert result == {"sessions": 2, "matched_procs": 4}

    def test_own_descendant_is_never_foreign_even_when_deep(self) -> None:
        table = [(10, 1, _RUNNER), (11, 10, "wrapper"), (12, 11, _PYTEST)]
        assert rps._count_foreign_pytest(table, own_pid=10) == {
            "sessions": 0,
            "matched_procs": 0,
        }

    def test_orphan_of_a_dead_parent_is_foreign(self) -> None:
        # ppid 999 is not in the table (parent already exited): still a root.
        table = [(10, 1, _RUNNER), (50, 999, _PYTEST)]
        assert rps._count_foreign_pytest(table, own_pid=10) == {
            "sessions": 1,
            "matched_procs": 1,
        }

    def test_table_that_cannot_see_us_is_not_evidence_of_zero(self) -> None:
        # Mutation: returning zeros here turns a failed listing into a silent
        # "no contention" reading.
        assert rps._count_foreign_pytest([(20, 1, _RUNNER)], own_pid=10) is None


class TestListProcessesForcesWideColumns:
    def test_posix_ps_call_gets_columns_override_in_env(self, monkeypatch) -> None:
        """WOT-2026-109a (fix): the ``ps`` subprocess must receive a widened
        ``COLUMNS`` in its environment.

        GNU ``ps`` truncates its ``args=`` column to a default line width
        (measured on a real CI runner: exactly 80 chars) whenever it cannot
        see a terminal and ``COLUMNS`` is unset -- silently dropping the
        ``-m pytest`` tail of any sufficiently long cmdline. Mutation that
        turns this red: dropping the ``env=`` kwarg (or passing ``env=None``)
        on the ``ps`` call in ``_list_processes`` -- `_run_cmd` would then
        fall back to inheriting the parent's unmodified environment, and this
        test would see no ``COLUMNS`` override.
        """
        if rps.os.name == "nt":
            pytest.skip("this probe exercises the POSIX ps branch")
        captured: dict[str, object] = {}

        class _FakeResult:
            returncode = 0
            stdout = ""

        def _fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["env"] = kwargs.get("env")
            return _FakeResult()

        monkeypatch.setattr(rps.subprocess, "run", _fake_run)
        monkeypatch.setattr(
            rps.shutil, "which", lambda name: "/usr/bin/ps" if name == "ps" else None
        )
        rps._list_processes()
        assert captured["env"] is not None
        assert captured["env"]["COLUMNS"] == "4096"
        # The override ADDS to the real environment rather than replacing it.
        assert captured["env"].get("PATH") == os.environ.get("PATH")


class TestRealForeignPytestProbe:
    def test_detects_a_real_orphan_pytest_process(self) -> None:
        """Positive control on the REAL listing path (no mocks).

        A grandchild whose command line carries ``-m pytest`` is started by an
        intermediate process that exits, so it is not our descendant -- the same
        shape as another session's pytest. The real probe must count it.
        """
        # The grandchild must not inherit our pipes: a child still holding
        # stdout open would keep subprocess.run(capture_output=True) waiting.
        spawner = (
            "import subprocess, sys\n"
            "p = subprocess.Popen([sys.executable, '-c', "
            "'import time; time.sleep(60)', '-m', 'pytest'], "
            "stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, "
            "stderr=subprocess.DEVNULL)\n"
            "print(p.pid, flush=True)\n"
        )
        out = subprocess.run(
            [sys.executable, "-c", spawner],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        ).stdout.strip()
        orphan_pid = int(out)
        try:
            rows = None
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                rows, errors = rps._list_processes()
                if rows is None:
                    pytest.skip(f"process listing unavailable here: {errors}")
                if any(pid == orphan_pid for pid, _, _ in rows):
                    break
                time.sleep(0.5)
            assert rows is not None
            assert any(pid == orphan_pid for pid, _, _ in rows), "orphan not listed"
            # Same snapshot with and without the orphan: other sessions running
            # on the machine cancel out, so the difference is the orphan alone.
            # Drop the orphan AND its descendants (the Windows venv launcher
            # re-execs the interpreter as a child of the pid we got back).
            gone = {orphan_pid}
            grew = True
            while grew:
                grew = False
                for pid, ppid, _ in rows:
                    if ppid in gone and pid not in gone:
                        gone.add(pid)
                        grew = True
            without = [r for r in rows if r[0] not in gone]
            before = rps._count_foreign_pytest(without, os.getpid())
            after = rps._count_foreign_pytest(rows, os.getpid())
            orphan_row = next((r for r in rows if r[0] == orphan_pid), None)
            print(  # DIAGNOSTIC, temporary: verify the WOT-2026-109a fix empirically
                f"\n[DIAG-109a-FIX] platform={sys.platform!r} "
                f"orphan_row={orphan_row!r} before={before!r} after={after!r}"
            )
            assert before is not None and after is not None
            assert after["matched_procs"] >= before["matched_procs"] + 1
            assert after["sessions"] >= before["sessions"] + 1
        finally:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/F", "/PID", str(orphan_pid)],
                    capture_output=True,
                    timeout=15,
                    check=False,
                )
            else:
                with contextlib.suppress(OSError):
                    os.kill(orphan_pid, 9)


# ---------------------------------------------------------------------------
# Tiempo por fichero y eco de consola
# ---------------------------------------------------------------------------


def _rows(spec):
    return [{"seconds": s, "phase": "call", "nodeid": n} for s, n in spec]


class TestAggregateDurationsByFile:
    def test_sums_every_phase_of_a_file_and_ranks_descending(self) -> None:
        rows = [
            {"seconds": 1.0, "phase": "setup", "nodeid": "tests/a.py::t1"},
            {"seconds": 2.0, "phase": "call", "nodeid": "tests/a.py::t1"},
            {"seconds": 0.5, "phase": "teardown", "nodeid": "tests/a.py::t2"},
            {"seconds": 3.4, "phase": "call", "nodeid": "tests/b.py::t1"},
        ]
        # Mutation: keying by the full nodeid (no split) yields 4 entries.
        assert rps.aggregate_durations_by_file(rows) == [
            {"file": "tests/a.py", "seconds": 3.5, "rows": 3},
            {"file": "tests/b.py", "seconds": 3.4, "rows": 1},
        ]

    def test_ties_break_by_path_and_top_n_cuts(self) -> None:
        rows = _rows([(1.0, "z.py::t"), (1.0, "a.py::t"), (0.1, "m.py::t")])
        result = rps.aggregate_durations_by_file(rows, top_n=2)
        assert [r["file"] for r in result] == ["a.py", "z.py"]

    def test_nodeid_without_separator_is_its_own_key(self) -> None:
        rows = _rows([(2.0, "tests/odd.py"), (1.0, "tests/odd.py")])
        assert rps.aggregate_durations_by_file(rows) == [
            {"file": "tests/odd.py", "seconds": 3.0, "rows": 2}
        ]


class TestParseRunMetricsWidened:
    def _log(self, n_rows: int, hidden: int | None = 12) -> str:
        rows = "\n".join(
            f"1.00s call     tests/f{i % 3}.py::t{i}" for i in range(n_rows)
        )
        hidden_line = (
            f"({hidden} durations < 0.005s hidden.  Use -vv to show these durations.)\n"
            if hidden is not None
            else ""
        )
        return (
            "============ slowest durations ============\n"
            f"{rows}\n{hidden_line}"
            f"============ {n_rows} passed in 99.00s ============\n"
        )

    def test_top_files_see_rows_beyond_the_top_25(self) -> None:
        # The whole point of --durations=0: the long tail is no longer lost.
        # Mutation: building top_files from the already-sliced top_slowest gives
        # rows == 25 instead of 60.
        m = rps.parse_run_metrics(self._log(60))
        assert len(m["top_slowest"]) == 25
        assert m["durations_rows"] == 60
        assert sum(f["rows"] for f in m["top_files"]) == 60
        assert m["durations_covered_s"] == 60.0

    def test_hidden_count_is_parsed_and_absent_is_none(self) -> None:
        assert rps.parse_run_metrics(self._log(3))["durations_hidden"] == 12
        assert (
            rps.parse_run_metrics(self._log(3, hidden=None))["durations_hidden"] is None
        )

    def test_empty_log_degrades_without_raising(self) -> None:
        m = rps.parse_run_metrics("")
        assert m["top_files"] == []
        assert m["durations_rows"] == 0
        assert m["durations_covered_s"] == 0.0
        assert m["durations_hidden"] is None


class TestCapDurationsTableEcho:
    def _lines(self, n_rows: int) -> list[str]:
        return (
            ["collected 100 items", "============ slowest durations ============"]
            + [f"{n_rows - i}.00s call     tests/x.py::t{i}" for i in range(n_rows)]
            + [
                "(5 durations < 0.005s hidden.  Use -vv to show these durations.)",
                "============ 100 passed in 9.00s ============",
            ]
        )

    def test_rows_over_the_limit_are_omitted_and_counted(self) -> None:
        out = rps._cap_durations_table_echo(self._lines(40), limit=25)
        printed_rows = [ln for ln in out if " call " in ln]
        assert len(printed_rows) == 25
        assert printed_rows[0].startswith("40.00s"), (
            "the slowest rows are the ones kept"
        )
        assert any("15 fila(s) de durations omitidas" in ln for ln in out)
        # Everything that is not a table row survives untouched.
        assert out[0] == "collected 100 items"
        assert out[-1] == "============ 100 passed in 9.00s ============"
        assert any("durations < 0.005s hidden" in ln for ln in out)

    def test_short_table_is_untouched_and_gets_no_note(self) -> None:
        lines = self._lines(10)
        assert rps._cap_durations_table_echo(lines, limit=25) == lines

    def test_a_line_that_merely_mentions_the_words_never_opens_a_table(self) -> None:
        lines = ["test says: slowest durations follow"] + [
            f"1.00s call     tests/y.py::t{i}" for i in range(30)
        ]
        assert rps._cap_durations_table_echo(lines, limit=25) == lines

    def test_console_is_capped_but_the_log_keeps_every_row(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        """Through the REAL stream_pytest: a child prints a 40-row table."""
        child = (
            "print('============ slowest durations ============')\n"
            "for i in range(40):\n"
            "    print(f'{40 - i}.00s call     tests/x.py::t{i}')\n"
            "print('============ 40 passed in 9.00s ============')\n"
        )
        log = tmp_path / "last-run.log"
        monkeypatch.setattr(rps, "LAST_RUN_LOG", log)
        rps.stream_pytest([sys.executable, "-c", child])
        printed = capsys.readouterr().out
        assert printed.count(" call ") == 25
        assert "15 fila(s) de durations omitidas" in printed
        assert log.read_text(encoding="utf-8").count(" call ") == 40


class TestInjectedFlag:
    def test_pytest_command_asks_for_the_full_durations_table(self, tmp_path) -> None:
        command, _ = rps.select_test_runner(
            sys.executable,
            pytest_args=["tests", "-q"],
            xdist_flags=[],
            run_dir=tmp_path,
            test_dir="tests",
            _probe=True,
        )
        # Mutation: going back to --durations=25 starves top_files of the tail.
        assert "--durations=0" in command
        assert "--durations=25" not in command


class TestVerdictEnv:
    def test_records_allowlisted_vars_and_only_those(self, monkeypatch) -> None:
        # Mutation: snapshotting the whole environment would leak paths/secrets
        # into run_history; ignoring os.environ would hide PYTHONUTF8=1.
        monkeypatch.setenv("PYTHONUTF8", "1")
        monkeypatch.delenv("PYTHONIOENCODING", raising=False)
        monkeypatch.setenv("AGENT_SECRET_TOKEN_FOR_TEST", "must-not-appear")
        env = rps._collect_verdict_env()
        assert env["PYTHONUTF8"] == "1"
        assert env["PYTHONIOENCODING"] is None
        assert set(env) == set(rps._VERDICT_ENV_VARS)
        assert "must-not-appear" not in repr(env)

    def test_project_root_is_recorded_as_presence_never_as_a_path(
        self, monkeypatch
    ) -> None:
        # Mutation: recording the raw value stores an absolute path in
        # run_history (the file is declared PII-scrubbed).
        monkeypatch.setenv("AGENT_PROJECT_ROOT", "C:/Users/someone/secret/dest")
        env = rps._collect_verdict_env()
        assert env["AGENT_PROJECT_ROOT"] == "<set>"
        assert "someone" not in repr(env)
        monkeypatch.delenv("AGENT_PROJECT_ROOT")
        assert rps._collect_verdict_env()["AGENT_PROJECT_ROOT"] is None

    def test_git_config_value_is_masked_unless_it_is_the_longpaths_flag(
        self, monkeypatch
    ) -> None:
        # GIT_CONFIG_KEY_0/VALUE_0 is how CI injects an Authorization header.
        # Mutation: recording VALUE_0 raw leaks the credential into run_history.
        monkeypatch.setenv("GIT_CONFIG_KEY_0", "http.extraheader")
        monkeypatch.setenv("GIT_CONFIG_VALUE_0", "AUTHORIZATION: basic c2VjcmV0")
        env = rps._collect_verdict_env()
        assert env["GIT_CONFIG_VALUE_0"] == "<set>"
        assert "c2VjcmV0" not in repr(env)
        monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.longpaths")
        monkeypatch.setenv("GIT_CONFIG_VALUE_0", "true")
        assert rps._collect_verdict_env()["GIT_CONFIG_VALUE_0"] == "true"
        monkeypatch.delenv("GIT_CONFIG_VALUE_0")
        assert rps._collect_verdict_env()["GIT_CONFIG_VALUE_0"] is None


class TestDurationsHeaderShape:
    def test_only_pytests_exact_header_opens_a_table(self) -> None:
        # Mutation: matching any line that starts with "=" and mentions the
        # words would let an assertion message open a bogus table.
        rows = [f"1.00s call     tests/y.py::t{i}" for i in range(30)]
        fake = ["=== note: slowest durations are listed below (not a header) ==="]
        assert rps._cap_durations_table_echo(fake + rows, limit=25) == fake + rows
        for header in (
            "=========== slowest durations ===========",
            "=========== slowest 25 durations ===========",
        ):
            out = rps._cap_durations_table_echo([header, *rows], limit=25)
            assert sum(" call " in ln for ln in out) == 25
