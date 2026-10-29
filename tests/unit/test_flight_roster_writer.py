"""Tests for scripts.flight_roster_writer (WOT-2026-136b).

Tests construct fixtures INLINE (dicts/strings Python), never copy from
real flight files. Each test imports its module under test INSIDE the
test function to ensure independent ModuleNotFoundError on failure.
"""

import builtins
import copy
import json
import os
import unittest.mock
from pathlib import Path

import pytest


def roster_path(tmp_path: Path) -> Path:
    """Construct a minimal flight_roster.json-like fixture on disk."""
    data = {
        "active_roles": {
            "_schema_note": "roster v1",
            "orquestador": {
                "threadId": "orq-001",
                "version": 3,
                "status": "active",
            },
            "supervisor": {
                "threadId": "sup-001",
                "version": 1,
                "status": "active",
            },
        },
        "rules": {
            "resolution": "manual",
            "read_when": "on_call",
            "apply_at": "on_enter",
            "host_change": "notify",
            "who_edits": "SUPERVISOR-2",
            "record": True,
            "independence": True,
            "session_codes": ["wot", "wp"],
        },
        "roster_fixes": [
            {"fix": "v1_compat", "applied": True},
        ],
        "sessions": [
            {"id": "sess-001", "status": "done"},
        ],
    }
    path = tmp_path / "flight_roster.json"
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def changes_log_path(tmp_path: Path) -> Path:
    """Construct a roster_changes.jsonl fixture (4 lines, ends with \\n).

    Lines 1-2 use the canonical schema (ts/by/change/detail/reason).
    Lines 3-4 use the legacy schema (ts/por/cambio/motivo).
    """
    content = (
        '{"ts": "2026-10-26T10:00:00+00:00", "by": "test", "change": '
        '"estado_transition", "detail": "role=orquestador ACTIVO -> '
        'PENDIENTE_ACK", "reason": "smoke"}\n'
        '{"ts": "2026-10-26T11:00:00+00:00", "by": "test", "change": '
        '"write_conflict", "detail": "role=supervisor intento=0 '
        'version_esperada=1 version_real=2", "reason": "smoke"}\n'
        '{"ts": "2026-10-26T09:00:00", "por": "legacy", "cambio": '
        '"estado_transition", "motivo": "old reason"}\n'
        '{"ts": "2026-10-26T09:30:00", "por": "legacy", "cambio": '
        '"control", "motivo": "old reason 2"}\n'
    )
    path = tmp_path / "roster_changes.jsonl"
    path.write_bytes(content.encode("utf-8"))
    return path


def changes_log_path_sin_newline_final(tmp_path: Path) -> Path:
    """Same as changes_log_path but WITHOUT a final \\n."""
    content = (
        '{"ts": "2026-10-26T10:00:00+00:00", "by": "test", "change": '
        '"estado_transition", "detail": "role=orquestador ACTIVO -> '
        'PENDIENTE_ACK", "reason": "smoke"}\n'
        '{"ts": "2026-10-26T11:00:00+00:00", "by": "test", "change": '
        '"write_conflict", "detail": "role=supervisor intento=0 '
        'version_esperada=1 version_real=2", "reason": "smoke"}\n'
        '{"ts": "2026-10-26T09:00:00", "por": "legacy", "cambio": '
        '"estado_transition", "motivo": "old reason"}\n'
        '{"ts": "2026-10-26T09:30:00", "por": "legacy", "cambio": '
        '"control", "motivo": "old reason 2"}'
    )
    path = tmp_path / "roster_changes_no_nl.jsonl"
    path.write_bytes(content.encode("utf-8"))
    return path


class TestWriteRoleEstado:
    """Tests for write_role_estado."""

    def test_01_write_role_estado_transicion_valida_incrementa_version_y_registra_linea_canonica(
        self, tmp_path
    ):
        from scripts.flight_roster_writer import write_role_estado

        roster_p = roster_path(tmp_path)
        changes_p = changes_log_path(tmp_path)

        write_role_estado(
            roster_p,
            "supervisor",
            "PENDIENTE_ACK",
            changes_log_path=changes_p,
            actor="test",
            reason="smoke",
        )

        # Re-parse and verify state
        roster_new = json.loads(roster_p.read_text(encoding="utf-8"))
        assert roster_new["active_roles"]["supervisor"]["estado"] == "PENDIENTE_ACK"
        assert roster_new["active_roles"]["supervisor"]["version"] == 2

        # Verify changes log: exactly one new line added
        log_lines = [
            line
            for line in changes_p.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert len(log_lines) == 5  # 4 original + 1 new

        new_line = json.loads(log_lines[-1])
        assert set(new_line.keys()) == {"ts", "by", "change", "detail", "reason"}
        assert new_line["by"] == "test"

    def test_02_write_role_estado_no_migra_ni_toca_lineas_antiguas_del_log(
        self, tmp_path
    ):
        from scripts.flight_roster_writer import write_role_estado

        roster_p = roster_path(tmp_path)
        changes_p = changes_log_path(tmp_path)

        # Read original content
        original_content = changes_p.read_text(encoding="utf-8")
        original_lines = [
            line for line in original_content.splitlines() if line.strip()
        ]
        assert len(original_lines) == 4

        write_role_estado(
            roster_p,
            "supervisor",
            "PENDIENTE_ACK",
            changes_log_path=changes_p,
            actor="test",
            reason="smoke",
        )

        # Verify first 4 lines are byte-identical
        new_content = changes_p.read_text(encoding="utf-8")
        new_lines = [line for line in new_content.splitlines() if line.strip()]
        for i in range(4):
            assert original_lines[i] == new_lines[i]

    def test_03_write_role_estado_transicion_invalida_lanza_roster_invalid_transition(
        self, tmp_path
    ):
        from scripts.flight_roster_writer import (
            RosterInvalidTransition,
            write_role_estado,
        )

        roster_p = roster_path(tmp_path)
        changes_p = changes_log_path(tmp_path)

        with pytest.raises(RosterInvalidTransition):
            write_role_estado(
                roster_p,
                "orquestador",
                "SALIENTE_MUERTO",
                changes_log_path=changes_p,
                actor="test",
                reason="smoke",
            )

        # Roster must not have changed
        roster_new = json.loads(roster_p.read_text(encoding="utf-8"))
        assert "estado" not in roster_new["active_roles"]["orquestador"]

    def test_04_write_role_estado_ts_por_argumento_se_rechaza_sin_leer_nada(
        self, tmp_path
    ):
        from scripts.flight_roster_writer import write_role_estado

        roster_p = roster_path(tmp_path)
        changes_p = changes_log_path(tmp_path)

        with unittest.mock.patch(
            "scripts.flight_roster_writer._read_roster"
        ) as mock_read:
            with pytest.raises(ValueError):
                write_role_estado(
                    roster_p,
                    "supervisor",
                    "PENDIENTE_ACK",
                    changes_log_path=changes_p,
                    actor="test",
                    reason="smoke",
                    ts="2026-10-29T00:00:00",
                )
            assert mock_read.call_count == 0

    def test_05_write_role_estado_campo_desconocido_lanza_roster_unknown_field(
        self, tmp_path
    ):
        from scripts.flight_roster_writer import (
            RosterUnknownField,
            write_role_estado,
        )

        roster_p = roster_path(tmp_path)

        # Inject an extra key into the supervisor entry
        roster_data = json.loads(roster_p.read_text(encoding="utf-8"))
        roster_data["active_roles"]["supervisor"]["campo_inventado"] = 1
        roster_p.write_bytes(
            (json.dumps(roster_data, indent=2) + "\n").encode("utf-8"),
        )

        before_bytes = roster_p.read_bytes()
        with pytest.raises(RosterUnknownField):
            write_role_estado(
                roster_p,
                "supervisor",
                "PENDIENTE_ACK",
                changes_log_path=changes_log_path(tmp_path),
                actor="test",
                reason="smoke",
            )
        after_bytes = roster_p.read_bytes()
        assert before_bytes == after_bytes, "Roster must be byte-identical"

    def test_06_write_role_estado_segundo_escritor_reintenta_una_vez_y_choca_otra_vez_falla(
        self, tmp_path
    ):
        from scripts.flight_roster_writer import (
            RosterWriteConflict,
            write_role_estado,
        )

        roster_p = roster_path(tmp_path)
        changes_p = changes_log_path(tmp_path)

        _side_effect_idx = [0]
        mutable_side_effects = [
            {
                "active_roles": {
                    "orquestador": {"version": 1},
                    "supervisor": {"version": 1},
                }
            },
            {
                "active_roles": {
                    "orquestador": {"version": 2},
                    "supervisor": {"version": 2},
                }
            },
            copy.deepcopy(
                {
                    "active_roles": {
                        "orquestador": {"version": 2},
                        "supervisor": {"version": 2},
                    },
                }
            ),
            {
                "active_roles": {
                    "orquestador": {"version": 3},
                    "supervisor": {"version": 3},
                }
            },
        ]

        def mock_read(path):
            idx = _side_effect_idx[0]
            _side_effect_idx[0] += 1
            return copy.deepcopy(mutable_side_effects[idx])

        with (
            unittest.mock.patch(
                "scripts.flight_roster_writer._read_roster", side_effect=mock_read
            ),
            pytest.raises(RosterWriteConflict),
        ):
            write_role_estado(
                roster_p,
                "supervisor",
                "PENDIENTE_ACK",
                changes_log_path=changes_p,
                actor="test",
                reason="smoke",
            )

        assert _side_effect_idx[0] == 4  # exactly 4 calls

        # Two NEW write_conflict lines added (fixture has 1 existing)
        log_lines = [
            line
            for line in changes_p.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        conflict_lines = [line for line in log_lines if '"write_conflict"' in line]
        assert len(conflict_lines) == 3  # 1 from fixture + 2 new

    def test_10_write_role_estado_transicion_misma_a_misma_es_no_op(self, tmp_path):
        from scripts.flight_roster_writer import write_role_estado

        roster_p = roster_path(tmp_path)
        changes_p = changes_log_path(tmp_path)

        before_content = roster_p.read_bytes()

        result = write_role_estado(
            roster_p,
            "supervisor",
            "ACTIVO",
            changes_log_path=changes_p,
            actor="test",
            reason="smoke",
        )

        after_content = roster_p.read_bytes()
        after_log_lines = [
            line
            for line in changes_p.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

        assert before_content == after_content, "Roster must be byte-identical"
        assert len(after_log_lines) == 4, "No new line in changes log"
        assert result == json.loads(before_content.decode("utf-8"))

    def test_11_write_role_estado_roundtrip_invalido_lanza_roster_roundtrip_error(
        self, tmp_path
    ):
        from scripts.flight_roster_writer import (
            RosterRoundTripError,
            _assert_roundtrip_identical,
        )

        # Tuple serializes to list in JSON: round-trip fails
        with pytest.raises(RosterRoundTripError):
            _assert_roundtrip_identical({"x": (1, 2)})

    def test_11_bis_write_role_estado_roundtrip_checks_anteriores_al_os_replace(
        self, tmp_path
    ):
        import scripts.flight_roster_writer

        roster_p = roster_path(tmp_path)
        changes_p = changes_log_path(tmp_path)

        call_order = []
        real_assert = scripts.flight_roster_writer._assert_roundtrip_identical
        real_replace = os.replace
        from scripts.flight_roster_writer import write_role_estado

        def tracked_assert(data):
            call_order.append("assert")
            return real_assert(data)

        def tracked_replace(src, dst):
            call_order.append("replace")
            return real_replace(src, dst)

        with (
            unittest.mock.patch(
                "scripts.flight_roster_writer._assert_roundtrip_identical",
                side_effect=tracked_assert,
            ),
            unittest.mock.patch(
                "scripts.flight_roster_writer.os.replace", side_effect=tracked_replace
            ),
        ):
            write_role_estado(
                roster_p,
                "supervisor",
                "PENDIENTE_ACK",
                changes_log_path=changes_p,
                actor="test",
                reason="smoke",
            )

        assert call_order.index("assert") < call_order.index("replace")

    def test_14_write_role_estado_rol_desconocido_lanza_roster_unknown_field(
        self, tmp_path
    ):
        from scripts.flight_roster_writer import (
            RosterUnknownField,
            write_role_estado,
        )

        roster_p = roster_path(tmp_path)
        changes_p = changes_log_path(tmp_path)

        roster_before = roster_p.read_bytes()
        log_before = changes_p.read_bytes()
        with pytest.raises(RosterUnknownField):
            write_role_estado(
                roster_p,
                "rol_que_no_existe",
                "ACTIVO",
                changes_log_path=changes_p,
                actor="test",
                reason="smoke",
            )
        with pytest.raises(RosterUnknownField):
            write_role_estado(
                roster_p,
                "_schema_note",
                "ACTIVO",
                changes_log_path=changes_p,
                actor="test",
                reason="smoke",
            )
        roster_after = roster_p.read_bytes()
        log_after = changes_p.read_bytes()
        assert roster_before == roster_after, "Roster must be byte-identical"
        assert log_before == log_after, "Changes log must be byte-identical"

    def test_write_role_estado_old_estado_vacio_lanza_roster_invalid_transition(
        self, tmp_path
    ):
        from scripts.flight_roster_writer import (
            RosterInvalidTransition,
            write_role_estado,
        )

        roster_p = roster_path(tmp_path)

        # Inject empty string estado (present but unrecognized)
        roster_data = json.loads(roster_p.read_text(encoding="utf-8"))
        roster_data["active_roles"]["orquestador"]["estado"] = ""
        roster_p.write_bytes(
            (json.dumps(roster_data, indent=2) + "\n").encode("utf-8"),
        )

        with pytest.raises(RosterInvalidTransition):
            write_role_estado(
                roster_p,
                "orquestador",
                "PENDIENTE_ACK",
                changes_log_path=changes_log_path(tmp_path),
                actor="test",
                reason="smoke",
            )

        # Roster must not have changed
        roster_after = json.loads(roster_p.read_text(encoding="utf-8"))
        assert roster_after["active_roles"]["orquestador"]["estado"] == ""

    def test_write_role_estado_old_estado_garbage_igual_a_new_estado_lanza_roster_invalid_transition(
        self, tmp_path
    ):
        from scripts.flight_roster_writer import (
            RosterInvalidTransition,
            write_role_estado,
        )

        roster_p = roster_path(tmp_path)

        # Inject garbage estado (present, non-empty, unrecognized)
        roster_data = json.loads(roster_p.read_text(encoding="utf-8"))
        roster_data["active_roles"]["supervisor"]["estado"] = "FOO"
        roster_p.write_bytes(
            (json.dumps(roster_data, indent=2) + "\n").encode("utf-8"),
        )

        with pytest.raises(RosterInvalidTransition):
            write_role_estado(
                roster_p,
                "supervisor",
                "FOO",
                changes_log_path=changes_log_path(tmp_path),
                actor="test",
                reason="smoke",
            )

        # Roster must not have changed
        roster_after = json.loads(roster_p.read_text(encoding="utf-8"))
        assert roster_after["active_roles"]["supervisor"]["estado"] == "FOO"


class TestWriteRoleEstadoNoOpConcurrency:
    """Tests for CAS retry no-op path (B1/D2)."""

    def test_write_role_estado_segundo_escritor_logra_misma_transicion_concurrente_es_no_op(
        self, tmp_path
    ):
        from scripts.flight_roster_writer import write_role_estado

        roster_p = roster_path(tmp_path)
        changes_p = changes_log_path(tmp_path)

        mock_calls = [
            {
                "active_roles": {
                    "orquestador": {
                        "threadId": "orq-001",
                        "version": 3,
                        "status": "active",
                    },
                    "supervisor": {
                        "threadId": "sup-001",
                        "version": 1,
                        "status": "active",
                    },
                },
            },
            {
                "active_roles": {
                    "orquestador": {
                        "threadId": "orq-001",
                        "version": 3,
                        "status": "active",
                    },
                    "supervisor": {
                        "threadId": "sup-001",
                        "version": 2,
                        "status": "active",
                    },
                }
            },
            {
                "active_roles": {
                    "orquestador": {
                        "threadId": "orq-001",
                        "version": 3,
                        "status": "active",
                    },
                    "supervisor": {
                        "threadId": "sup-001",
                        "version": 2,
                        "status": "active",
                        "estado": "PENDIENTE_ACK",
                    },
                }
            },
        ]
        _mock_idx = [0]

        def mock_read(path):
            idx = _mock_idx[0]
            _mock_idx[0] += 1
            return copy.deepcopy(mock_calls[idx])

        with unittest.mock.patch(
            "scripts.flight_roster_writer._read_roster", side_effect=mock_read
        ):
            result = write_role_estado(
                roster_p,
                "supervisor",
                "PENDIENTE_ACK",
                changes_log_path=changes_p,
                actor="test",
                reason="smoke",
            )

        assert result["active_roles"]["supervisor"]["estado"] == "PENDIENTE_ACK"

        # Verify exactly 3 _read_roster calls (initial + attempt 1 re-read + no-op before fresh)
        assert _mock_idx[0] == 3

        # Exactly one new line in changes log (the write_conflict from attempt 0)
        log_lines = [
            line
            for line in changes_p.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert len(log_lines) == 5  # 4 original + 1 new write_conflict

    def test_write_role_estado_reintento_con_old_estado_vacio_lanza_roster_invalid_transition(
        self, tmp_path
    ):
        """Fix 2: CAS retry re-read must validate old_estado before no-op."""
        from scripts.flight_roster_writer import (
            RosterInvalidTransition,
            write_role_estado,
        )

        roster_p = roster_path(tmp_path)
        changes_p = changes_log_path(tmp_path)

        # Read bytes before call to verify immutability after exception
        roster_p_bytes_before = roster_p.read_bytes()

        mock_calls = [
            # Read 1 (initial, outside loop): supervisor with estado="PENDIENTE_ACK"
            {
                "active_roles": {
                    "orquestador": {
                        "threadId": "orq-001",
                        "version": 3,
                        "status": "active",
                    },
                    "supervisor": {
                        "threadId": "sup-001",
                        "version": 1,
                        "status": "active",
                        "estado": "PENDIENTE_ACK",
                    },
                },
            },
            # Read 2 (CAS check attempt 0): version mismatch -> retry
            {
                "active_roles": {
                    "orquestador": {
                        "threadId": "orq-001",
                        "version": 3,
                        "status": "active",
                    },
                    "supervisor": {
                        "threadId": "sup-001",
                        "version": 2,
                        "status": "active",
                    },
                }
            },
            # Read 3 (re-read base attempt 1): corrupt estado="" (not recognized)
            {
                "active_roles": {
                    "orquestador": {
                        "threadId": "orq-001",
                        "version": 3,
                        "status": "active",
                    },
                    "supervisor": {
                        "threadId": "sup-001",
                        "version": 2,
                        "status": "active",
                        "estado": "",
                    },
                }
            },
        ]
        _mock_idx = [0]

        def mock_read(path):
            idx = _mock_idx[0]
            _mock_idx[0] += 1
            return copy.deepcopy(mock_calls[idx])

        with (
            unittest.mock.patch(
                "scripts.flight_roster_writer._read_roster", side_effect=mock_read
            ),
            pytest.raises(RosterInvalidTransition),
        ):
            write_role_estado(
                roster_p,
                "supervisor",
                "ACTIVO",
                changes_log_path=changes_p,
                actor="test",
                reason="smoke",
            )

        # Verify roster immutability: the roster must not have changed
        # (the changes log was legitimately modified by the write_conflict
        # line from attempt 0, but the roster file is untouched).
        assert roster_p.read_bytes() == roster_p_bytes_before

        # Exactly 3 reads (initial + attempt 0 CAS check + attempt 1 re-read)
        assert _mock_idx[0] == 3


class TestAppendChangeLineNoTruncate:
    """Tests for D1: _append_change_line must never truncate."""

    def test_append_change_line_no_trunca_contenido_existente_sin_newline_final(
        self, tmp_path
    ):
        from scripts.flight_roster_writer import write_role_estado

        roster_p = roster_path(tmp_path)
        roster_data = json.loads(roster_p.read_text(encoding="utf-8"))
        roster_data["active_roles"]["supervisor"]["estado"] = "ACTIVO"
        roster_p.write_bytes(
            (json.dumps(roster_data, indent=2) + "\n").encode("utf-8"),
        )

        changes_p = changes_log_path_sin_newline_final(tmp_path)
        original_bytes = changes_p.read_bytes()

        real_open = builtins.open
        opens_on_log = []

        def tracking_open(file, mode="r", *args, **kwargs):
            if Path(file) == changes_p:
                opens_on_log.append(mode)
            return real_open(file, mode, *args, **kwargs)

        with unittest.mock.patch("builtins.open", side_effect=tracking_open):
            write_role_estado(
                roster_p,
                "supervisor",
                "PENDIENTE_ACK",
                changes_log_path=changes_p,
                actor="test",
                reason="smoke",
            )

        after_bytes = changes_p.read_bytes()
        assert after_bytes.startswith(original_bytes)
        assert after_bytes[len(original_bytes)] == ord("\n")
        new_line_json = json.loads(after_bytes[len(original_bytes) + 1 :])
        assert set(new_line_json.keys()) == {"ts", "by", "change", "detail", "reason"}
        assert new_line_json["change"] == "estado_transition"

        truncating_modes = {"w", "wb", "w+", "w+b", "r+", "r+b", "rb+", "wt", "w+t"}
        assert not any(m in truncating_modes for m in opens_on_log), (
            f"una apertura del log uso un modo que trunca: {opens_on_log}"
        )
        assert "ab" in opens_on_log, (
            f"la insercion del newline lider debe usar 'ab' puro: {opens_on_log}"
        )


class TestSeedAuthorityAndRules:
    """Tests for seed_authority_and_rules."""

    def test_07_seed_authority_and_rules_anade_los_cinco_campos_de_autoridad_con_nota(
        self, tmp_path
    ):
        from scripts.flight_roster_writer import seed_authority_and_rules

        roster_p = roster_path(tmp_path)
        changes_p = changes_log_path(tmp_path)

        result = seed_authority_and_rules(
            roster_p,
            actor="test",
            changes_log_path=changes_p,
            reason="smoke",
        )

        authority = result["autoridad"]
        assert set(authority.keys()) == {
            "merge",
            "push",
            "suite_canonica",
            "admision_ticket_nuevo",
            "backends_retirados",
            "nota",
        }
        assert authority["merge"] == "SUPERVISOR-2"

    def test_08_seed_authority_and_rules_anade_session_relief_y_nunca_toca_active_roles(
        self, tmp_path
    ):
        from scripts.flight_roster_writer import seed_authority_and_rules

        roster_p = roster_path(tmp_path)
        changes_p = changes_log_path(tmp_path)

        before_active_roles = json.loads(
            roster_p.read_text(encoding="utf-8"),
        )["active_roles"]
        before_roster_fixes = json.loads(
            roster_p.read_text(encoding="utf-8"),
        )["roster_fixes"]
        before_sessions = json.loads(
            roster_p.read_text(encoding="utf-8"),
        )["sessions"]
        before_rules_keys = sorted(
            json.loads(
                roster_p.read_text(encoding="utf-8"),
            )["rules"].keys()
        )

        result = seed_authority_and_rules(
            roster_p,
            actor="test",
            changes_log_path=changes_p,
            reason="smoke",
        )

        # Check session_relief
        sr = result["rules"]["session_relief"]
        assert set(sr.keys()) == {"orquestadora", "implantacion", "triaje"}
        for slot in sr.values():
            assert slot["plazo_sin_progreso"] > 0
            assert slot["sensible_a_causa"] in {
                "determinista",
                "no_determinista",
            }

        # active_roles unchanged
        assert result["active_roles"] == before_active_roles
        assert result["roster_fixes"] == before_roster_fixes
        assert result["sessions"] == before_sessions
        # Before keys must be a subset of the new keys (session_relief is added)
        before_key_set = set(before_rules_keys)
        new_key_set = set(result["rules"].keys())
        assert before_key_set.issubset(new_key_set)
        assert "session_relief" in new_key_set

    def test_09_seed_authority_and_rules_es_idempotente_en_llamadas_secuenciales_y_nunca_anade_supervisores_antiguos(
        self, tmp_path
    ):
        from scripts.flight_roster_writer import seed_authority_and_rules

        roster_p = roster_path(tmp_path)
        changes_p = changes_log_path(tmp_path)

        seed_authority_and_rules(
            roster_p,
            actor="test",
            changes_log_path=changes_p,
            reason="smoke",
        )
        after_first = roster_p.read_bytes()

        seed_authority_and_rules(
            roster_p,
            actor="test",
            changes_log_path=changes_p,
            reason="smoke",
        )
        after_second = roster_p.read_bytes()

        assert after_first == after_second, "Must be byte-identical after second call"
        assert "supervisores_antiguos" not in after_second.decode("utf-8")


class TestAppendChangeLine:
    """Tests for _append_change_line defensive newline."""

    def test_13_append_change_line_garantiza_salto_de_linea_si_el_log_no_termina_en_newline(
        self, tmp_path
    ):
        from scripts.flight_roster_writer import write_role_estado

        roster_p = roster_path(tmp_path)
        # Update supervisor to ACTIVO first so the fixture's implicit
        # ACTIVO matches
        roster_data = json.loads(roster_p.read_text(encoding="utf-8"))
        roster_data["active_roles"]["supervisor"]["estado"] = "ACTIVO"
        roster_p.write_bytes(
            (json.dumps(roster_data, indent=2) + "\n").encode("utf-8"),
        )

        changes_p = changes_log_path_sin_newline_final(tmp_path)

        before_lines = [
            line
            for line in changes_p.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert len(before_lines) == 4

        write_role_estado(
            roster_p,
            "supervisor",
            "PENDIENTE_ACK",
            changes_log_path=changes_p,
            actor="test",
            reason="smoke",
        )

        after_lines = [
            line
            for line in changes_p.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert len(after_lines) == 5

        # Verify both the original last line and new line are valid JSON
        assert json.loads(after_lines[-2])  # original line 4
        assert json.loads(after_lines[-1])  # new line


class TestCliMain:
    """Tests for the CLI main function."""

    def test_12_cli_main_mapea_conflicto_a_exit_2_con_mensaje_de_escalada(
        self, tmp_path, capsys
    ):
        from scripts.flight_roster_writer import main

        roster_p = roster_path(tmp_path)
        changes_p = changes_log_path(tmp_path)

        mutable_side_effects = [
            {
                "active_roles": {
                    "orquestador": {"version": 1},
                    "supervisor": {"version": 1},
                }
            },
            {
                "active_roles": {
                    "orquestador": {"version": 2},
                    "supervisor": {"version": 2},
                }
            },
            copy.deepcopy(
                {
                    "active_roles": {
                        "orquestador": {"version": 2},
                        "supervisor": {"version": 2},
                    },
                }
            ),
            {
                "active_roles": {
                    "orquestador": {"version": 3},
                    "supervisor": {"version": 3},
                }
            },
        ]
        _side_effect_idx = [0]

        def mock_read(path):
            idx = _side_effect_idx[0]
            _side_effect_idx[0] += 1
            return copy.deepcopy(mutable_side_effects[idx])

        with unittest.mock.patch(
            "scripts.flight_roster_writer._read_roster", side_effect=mock_read
        ):
            rc = main(
                [
                    "--roster",
                    str(roster_p),
                    "--role",
                    "supervisor",
                    "--estado",
                    "PENDIENTE_ACK",
                    "--changes-log",
                    str(changes_p),
                    "--actor",
                    "test",
                    "--reason",
                    "smoke",
                ]
            )
            assert rc == 2

        err = capsys.readouterr().err
        assert "ESCALAR A SUPERVISOR-2" in err

    def test_15_cli_main_mapea_transicion_invalida_a_exit_3(self, tmp_path, capsys):
        from scripts.flight_roster_writer import main

        roster_p = roster_path(tmp_path)
        changes_p = changes_log_path(tmp_path)

        rc = main(
            [
                "--roster",
                str(roster_p),
                "--role",
                "orquestador",
                "--estado",
                "SALIENTE_MUERTO",
                "--changes-log",
                str(changes_p),
                "--actor",
                "test",
                "--reason",
                "smoke",
            ]
        )
        assert rc == 3

        err = capsys.readouterr().err
        assert len(err) > 0

        # Roster must not have changed
        roster_new = json.loads(roster_p.read_text(encoding="utf-8"))
        assert "estado" not in roster_new["active_roles"]["orquestador"]
