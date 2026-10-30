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
            "who_edits": "autoridad-titular",
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

        # Two sup-nuevo write_conflict lines added (fixture has 1 existing)
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
    """Tests for seed_authority_and_rules (WOT-2026-136b legacy, now migrated to new behavior).

    The old behavior seeded both authority and session_relief. The new behavior
    (WOT-2026-136f) fails closed if authority is absent. See TestSeedAuthorityAndRulesNew.
    """

    def _make_roster_with_authority(self, tmp_path: Path) -> Path:
        roster_data = {
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
            "autoridad": {
                "merge": "autoridad-titular",
                "push": "autoridad-titular",
                "suite_canonica": "autoridad-titular",
                "admision_ticket_nuevo": "autoridad-titular",
                "backends_retirados": "autoridad-titular",
                "nota": "la autoridad no se hereda por posicion en la cadena; fuente: roster active_roles.supervisor",
            },
            "rules": {
                "resolution": "manual",
            },
            "roster_fixes": [
                {"fix": "v1_compat", "applied": True},
            ],
            "sessions": [
                {"id": "sess-001", "status": "done"},
            ],
        }
        p = tmp_path / "flight_roster.json"
        p.write_text(json.dumps(roster_data, indent=2) + "\n", encoding="utf-8")
        return p

    def test_07_seed_authority_and_rules_anade_los_cinco_campos_de_autoridad_con_nota(
        self, tmp_path
    ):
        """test_07 migrated: authority block is now user-provided, not seeded."""
        from scripts.flight_roster_writer import seed_authority_and_rules

        # Use fixture with authority present -> seeds only session_relief
        roster_p = self._make_roster_with_authority(tmp_path)
        changes_p = changes_log_path(tmp_path)

        result = seed_authority_and_rules(
            roster_p,
            actor="test",
            changes_log_path=changes_p,
            reason="smoke",
        )

        # Authority was already present, only session_relief added
        assert "autoridad" in result
        sr = result["rules"]["session_relief"]
        assert set(sr.keys()) == {"triaje", "orquestadora", "implantacion"}

    def test_08_seed_authority_and_rules_anade_session_relief_y_nunca_toca_active_roles(
        self, tmp_path
    ):
        """test_08 migrated: authority present, seeds only session_relief."""
        from scripts.flight_roster_writer import seed_authority_and_rules

        roster_p = self._make_roster_with_authority(tmp_path)
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

    def test_09_seed_authority_and_rules_es_idempotente_en_llamadas_secuenciales_y_nunca_anade_supervisores_antiguos(
        self, tmp_path
    ):
        """test_09 migrated: idempotency test with authority present."""
        from scripts.flight_roster_writer import seed_authority_and_rules

        roster_p = self._make_roster_with_authority(tmp_path)
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
        assert "conflicto de escritura" in err

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


# --- WOT-2026-136f: write_supervisor tests (DoD 1-2) ---


class TestSeedAuthorityAndRulesNew:
    """Tests for seed_authority_and_rules new behavior (DoD 3-4, WOT-2026-136f)."""

    def _make_roster(self, tmp_path: Path, with_autoridad: bool = False) -> Path:
        roster_data = {
            "active_roles": {"orquestador": {"threadId": "orq-001", "version": 1}},
            "rules": {},
        }
        if with_autoridad:
            roster_data["autoridad"] = {"merge": "user-decided"}
        p = tmp_path / "flight_roster.json"
        p.write_text(json.dumps(roster_data, indent=2) + "\n", encoding="utf-8")
        return p

    def test_seed_no_autoridad_raises(self, tmp_path):
        """DoD 3: autoridad ausente -> RosterUnknownField (bloquea semilla)."""
        from scripts.flight_roster_writer import (
            RosterUnknownField,
            seed_authority_and_rules,
        )

        roster_p = self._make_roster(tmp_path, with_autoridad=False)
        changes_p = tmp_path / "roster_changes.jsonl"
        changes_p.write_text("", encoding="utf-8")

        with pytest.raises(RosterUnknownField):
            seed_authority_and_rules(
                roster_p,
                actor="test",
                changes_log_path=changes_p,
                reason="smoke",
            )

    def test_seed_with_autoridad_only_session_relief(self, tmp_path):
        """DoD 3: autoridad presente, session_relief ausente -> siembra solo session_relief."""
        from scripts.flight_roster_writer import seed_authority_and_rules

        roster_p = self._make_roster(tmp_path, with_autoridad=True)
        changes_p = tmp_path / "roster_changes.jsonl"
        changes_p.write_text("", encoding="utf-8")

        result = seed_authority_and_rules(
            roster_p,
            actor="test",
            changes_log_path=changes_p,
            reason="smoke",
        )

        assert "autoridad" in result
        assert "session_relief" in result["rules"]
        log_lines = [
            line
            for line in changes_p.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert len(log_lines) == 1
        assert "session_relief" in log_lines[0]
        assert "autoridad" not in log_lines[0]

    def test_seed_both_present_is_noop(self, tmp_path):
        """DoD 3: ambos presentes -> no-op."""
        from scripts.flight_roster_writer import seed_authority_and_rules

        roster_data = {
            "active_roles": {"orquestador": {"threadId": "orq-001"}},
            "autoridad": {"merge": "user"},
            "rules": {"session_relief": {"triaje": {"plazo_sin_progreso": 15}}},
        }
        roster_p = tmp_path / "flight_roster.json"
        roster_p.write_text(json.dumps(roster_data, indent=2) + "\n", encoding="utf-8")
        changes_p = tmp_path / "roster_changes.jsonl"
        changes_p.write_text("", encoding="utf-8")
        before = roster_p.read_bytes()

        seed_authority_and_rules(
            roster_p,
            actor="test",
            changes_log_path=changes_p,
            reason="smoke",
        )

        after = roster_p.read_bytes()
        assert before == after, "Roster must be byte-identical (no-op)"

    def test_seed_rotation_does_not_touch_autoridad(self, tmp_path):
        """DoD 3: rotation no toca autoridad (se prueba via write_supervisor)."""
        from scripts.flight_roster_writer import write_supervisor

        roster_data = {
            "active_roles": {
                "orquestador": {
                    "threadId": "mcp:orq-nuevo",
                    "predecessor_threadId": "mcp:orq-previo",
                    "session_code": "orq8",
                    "version": 4,
                    "status": "active",
                },
                "supervisor": {
                    "threadId": "mcp:sup-antiguo",
                    "session_code": "sup-antiguo",
                    "predecessor_threadId": "",
                    "version": 3,
                    "status": "active",
                },
            },
            "autoridad": {"merge": "user-decided"},
            "rules": {},
        }
        roster_p = tmp_path / "flight_roster.json"
        roster_p.write_text(json.dumps(roster_data, indent=2) + "\n", encoding="utf-8")
        changes_p = tmp_path / "roster_changes.jsonl"
        changes_p.write_text("", encoding="utf-8")
        before_autoridad = dict(roster_data["autoridad"])

        write_supervisor(
            roster_p,
            "mcp:orq-previo",
            "mcp:orq-previo-code",
            changes_log_path=changes_p,
            actor="test",
            reason="relevo normal",
        )

        # Authority must remain untouched.
        after = json.loads(roster_p.read_text(encoding="utf-8"))
        assert after["autoridad"] == before_autoridad

    def test_07_seed_no_autoridad_lanza_roster_unknown_field(self, tmp_path):
        """test_07: autoridad ausente -> error (migrado del test_07 antiguo)."""
        from scripts.flight_roster_writer import (
            RosterUnknownField,
            seed_authority_and_rules,
        )

        roster_p = self._make_roster(tmp_path, with_autoridad=False)
        changes_p = tmp_path / "roster_changes.jsonl"
        changes_p.write_text("", encoding="utf-8")

        with pytest.raises(RosterUnknownField):
            seed_authority_and_rules(
                roster_p,
                actor="test",
                changes_log_path=changes_p,
                reason="smoke",
            )

    def test_08_seed_with_autoridad_siembra_session_relief(self, tmp_path):
        """test_08: autoridad presente -> siembra solo session_relief (migrado)."""
        from scripts.flight_roster_writer import seed_authority_and_rules

        roster_p = self._make_roster(tmp_path, with_autoridad=True)
        changes_p = tmp_path / "roster_changes.jsonl"
        changes_p.write_text("", encoding="utf-8")

        result = seed_authority_and_rules(
            roster_p,
            actor="test",
            changes_log_path=changes_p,
            reason="smoke",
        )

        sr = result["rules"]["session_relief"]
        assert set(sr.keys()) == {"triaje", "orquestadora", "implantacion"}
        for slot in sr.values():
            assert slot["plazo_sin_progreso"] > 0


class TestCliRotation:
    """Tests for CLI rotation flags (DoD 6, WOT-2026-136f)."""

    def test_28_cli_supervisor_rotation_ok(self, tmp_path, capsys):
        """DoD 6: CLI rotation -> rc 0."""
        from scripts.flight_roster_writer import main

        roster_data = {
            "active_roles": {
                "orquestador": {
                    "threadId": "mcp:orq-nuevo",
                    "predecessor_threadId": "mcp:orq-previo",
                    "version": 4,
                    "status": "active",
                },
                "supervisor": {
                    "threadId": "mcp:sup-antiguo",
                    "session_code": "sup-antiguo",
                    "version": 3,
                    "status": "active",
                },
            },
            "rules": {},
        }
        roster_p = tmp_path / "flight_roster.json"
        roster_p.write_text(json.dumps(roster_data, indent=2) + "\n", encoding="utf-8")
        changes_p = tmp_path / "roster_changes.jsonl"
        changes_p.write_text("", encoding="utf-8")

        rc = main(
            [
                "--roster",
                str(roster_p),
                "--supervisor-thread",
                "mcp:orq-previo",  # predecessor of mcp:orq-nuevo
                "--supervisor-code",
                "mcp:orq7",
                "--changes-log",
                str(changes_p),
                "--actor",
                "test",
                "--reason",
                "relevo",
            ]
        )
        assert rc == 0
        new_sup = json.loads(roster_p.read_text(encoding="utf-8"))["active_roles"][
            "supervisor"
        ]
        assert new_sup["threadId"] == "mcp:orq-previo"

    def test_29_cli_supervisor_rotation_with_exception(self, tmp_path, capsys):
        """DoD 6: CLI rotation with exception -> rc 0."""
        from scripts.flight_roster_writer import main

        roster_data = {
            "active_roles": {
                "orquestador": {
                    "threadId": "mcp:orq-nuevo",
                    "predecessor_threadId": "mcp:orq-previo",
                    "version": 4,
                    "status": "active",
                },
                "supervisor": {
                    "threadId": "mcp:sup-antiguo",
                    "session_code": "sup-antiguo",
                    "version": 3,
                    "status": "active",
                },
            },
            "rules": {},
        }
        roster_p = tmp_path / "flight_roster.json"
        roster_p.write_text(json.dumps(roster_data, indent=2) + "\n", encoding="utf-8")
        changes_p = tmp_path / "roster_changes.jsonl"
        changes_p.write_text("", encoding="utf-8")

        rc = main(
            [
                "--roster",
                str(roster_p),
                "--supervisor-thread",
                "mcp:sup-diferente",
                "--supervisor-code",
                "mcp:diferente",
                "--excepcion",
                "supervisor efectivo distinto",
                "--changes-log",
                str(changes_p),
                "--actor",
                "test",
                "--reason",
                "excepcion",
            ]
        )
        assert rc == 0
        after = json.loads(roster_p.read_text(encoding="utf-8"))
        assert after["active_roles"]["supervisor"]["threadId"] == "mcp:sup-diferente"
        assert "excepcion_supervisor" in after
        assert after["excepcion_supervisor"]["motivo"] == "supervisor efectivo distinto"
        assert "excepcion_supervisor" in after

    def test_30_cli_rotation_validation_error(self, tmp_path, capsys):
        """DoD 6: CLI closed failure -> rc 3, no traceback."""
        from scripts.flight_roster_writer import main

        roster_data = {
            "active_roles": {
                "orquestador": {
                    "threadId": "orq-nuevo",
                    "predecessor_threadId": "orq-previo",
                    "version": 4,
                    "status": "active",
                },
                "supervisor": {
                    "threadId": "sup-antiguo",
                    "session_code": "sup-antiguo",
                    "version": 3,
                    "status": "active",
                },
            },
            "rules": {},
        }
        roster_p = tmp_path / "flight_roster.json"
        roster_p.write_text(json.dumps(roster_data, indent=2) + "\n", encoding="utf-8")
        changes_p = tmp_path / "roster_changes.jsonl"
        changes_p.write_text("", encoding="utf-8")

        rc = main(
            [
                "--roster",
                str(roster_p),
                "--supervisor-thread",
                "diferenteERENT",  # != predecessor, no excepcion
                "--supervisor-code",
                "diferente",
                "--changes-log",
                str(changes_p),
                "--actor",
                "test",
                "--reason",
                "no excepcion",
            ]
        )
        assert rc == 3
        err = capsys.readouterr().err
        assert "Traceback" not in err

    def test_31_cli_mixed_flags(self, tmp_path, capsys):
        """DoD 6: mixing --role and --supervisor-thread -> rc 3."""
        from scripts.flight_roster_writer import main

        roster_data = {
            "active_roles": {
                "orquestador": {
                    "threadId": "orq-previo",
                    "version": 1,
                    "status": "active",
                },
                "supervisor": {"threadId": "mcp:sup", "version": 1, "status": "active"},
            },
            "rules": {},
        }
        roster_p = tmp_path / "flight_roster.json"
        roster_p.write_text(json.dumps(roster_data, indent=2) + "\n", encoding="utf-8")
        changes_p = tmp_path / "roster_changes.jsonl"
        changes_p.write_text("", encoding="utf-8")

        rc = main(
            [
                "--roster",
                str(roster_p),
                "--role",
                "builder",
                "--supervisor-thread",
                "orq-previo",
                "--changes-log",
                str(changes_p),
                "--actor",
                "test",
                "--reason",
                "mixed",
            ]
        )
        assert rc == 3

    def test_32_cli_missing_base_flag(self, tmp_path, capsys):
        """DoD 6: missing --roster -> rc 3 (not argparse 2)."""
        from scripts.flight_roster_writer import main

        rc = main(
            [
                "--role",
                "builder",
                "--estado",
                "ACTIVO",
                "--changes-log",
                "/tmp/x.jsonl",
                "--actor",
                "test",
                "--reason",
                "test",
            ]
        )
        assert rc == 3

    def test_32_b_cli_incomplete_supervisor_flags(self, tmp_path, capsys):
        """DoD 6: --supervisor-thread without --supervisor-code -> rc 3."""
        from scripts.flight_roster_writer import main

        roster_data = {
            "active_roles": {
                "orquestador": {
                    "threadId": "orq-previo",
                    "version": 1,
                    "status": "active",
                },
                "supervisor": {"threadId": "mcp:sup", "version": 1, "status": "active"},
            },
            "rules": {},
        }
        roster_p = tmp_path / "flight_roster.json"
        roster_p.write_text(json.dumps(roster_data, indent=2) + "\n", encoding="utf-8")
        changes_p = tmp_path / "roster_changes.jsonl"
        changes_p.write_text("", encoding="utf-8")

        rc = main(
            [
                "--roster",
                str(roster_p),
                "--supervisor-thread",
                "orq-previo",
                "--changes-log",
                str(changes_p),
                "--actor",
                "test",
                "--reason",
                "incomplete",
            ]
        )
        assert rc == 3


class TestZeroLiterals:
    """Tests for DoD 4: zero session IDs in writer code."""

    def test_writer_no_session_ids_in_code(self, tmp_path):
        """DoD 4: writer source has zero session IDs."""
        import re

        writer_path = (
            Path(__file__).resolve().parent.parent.parent
            / "scripts"
            / "flight_roster_writer.py"
        )
        content = writer_path.read_text(encoding="utf-8")

        session_re = re.compile(r"\b(SUPERVISOR|OR|CO|IM|TR)-[0-9]+(\.[0-9]+)?\b")
        matches = session_re.findall(content)
        assert len(matches) == 0, (
            f"Writer source must not contain session IDs, found {len(matches)}: {matches}"
        )

    def test_rotation_cli_message_no_session_ids(self, tmp_path):
        """DoD 4: CLI conflict message does not name sessions."""
        import re

        writer_path = (
            Path(__file__).resolve().parent.parent.parent
            / "scripts"
            / "flight_roster_writer.py"
        )
        content = writer_path.read_text(encoding="utf-8")

        session_re = re.compile(r"\b(SUPERVISOR|OR|CO|IM|TR)-[0-9]+(\.[0-9]+)?\b")
        matches = session_re.findall(content)
        assert len(matches) == 0, (
            f"Writer must not contain session IDs, found {len(matches)}: {matches}"
        )


class TestWriteSupervisor:
    """Tests for write_supervisor (WOT-2026-136f DoD 1-2)."""

    def _make_roster_with_predecessor(
        self, tmp_path: Path, orq_thread: str, orq_pred: str, sup_thread: str
    ) -> Path:
        roster_data = {
            "active_roles": {
                "orquestador": {
                    "threadId": orq_thread,
                    "session_code": "orq-previo",
                    "predecessor_threadId": orq_pred,
                    "version": 3,
                    "status": "active",
                },
                "supervisor": {
                    "threadId": sup_thread,
                    "session_code": "SUP-code",
                    "predecessor_threadId": "",
                    "version": 1,
                    "status": "active",
                },
            },
            "rules": {"resolution": "manual"},
        }
        p = tmp_path / "flight_roster.json"
        p.write_text(json.dumps(roster_data, indent=2) + "\n", encoding="utf-8")
        return p

    def test_write_supervisor_happy_path(self, tmp_path):
        """DoD 1: supervisor = predecessor -> rotation succeeds with cascada."""
        from scripts.flight_roster_writer import write_supervisor

        roster_p = self._make_roster_with_predecessor(
            tmp_path, "mcp:orq-previo", "mcp:sup-viejo", "mcp:sup-antiguo"
        )
        changes_p = tmp_path / "roster_changes.jsonl"
        changes_p.write_text("", encoding="utf-8")

        result = write_supervisor(
            roster_p,
            "mcp:sup-viejo",  # predecessor of orquestador (mcp:orq-previo)
            "mcp:sup-viejo",
            changes_log_path=changes_p,
            actor="test",
            reason="relevo",
        )

        new_sup = result["active_roles"]["supervisor"]
        assert new_sup["threadId"] == "mcp:sup-viejo"
        assert new_sup["session_code"] == "mcp:sup-viejo"
        assert new_sup["version"] == 2
        assert new_sup["predecessor_threadId"] == "mcp:sup-antiguo"
        assert new_sup["status"] == "active"
        cad = result["cadena_contexto"]
        assert len(cad) == 1
        assert cad[0]["threadId"] == "mcp:sup-antiguo"
        log_lines = [
            line
            for line in changes_p.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert len(log_lines) == 1
        assert "supervisor_rotation" in log_lines[0]

    def test_write_supervisor_with_excepcion(self, tmp_path):
        """DoD 1: supervisor != predecessor + excepcion -> writes excepcion_supervisor."""
        from scripts.flight_roster_writer import write_supervisor

        roster_p = self._make_roster_with_predecessor(
            tmp_path, "mcp:orq-previo", "mcp:sup-viejo", "mcp:sup-antiguo"
        )
        changes_p = tmp_path / "roster_changes.jsonl"
        changes_p.write_text("", encoding="utf-8")

        result = write_supervisor(
            roster_p,
            "mcp:sup-diferente",
            "diff-code",
            changes_log_path=changes_p,
            actor="test",
            reason="supervisor efectivo distinto",
            excepcion="supervisor efectivo distinto del predecesor",
        )

        assert result["active_roles"]["supervisor"]["threadId"] == "mcp:sup-diferente"
        exc = result["excepcion_supervisor"]
        assert exc["motivo"] == "supervisor efectivo distinto del predecesor"
        assert exc["coordinadora_threadId"] == "mcp:orq-previo"

    def test_write_supervisor_after_excepcion_cleans_excepcion(self, tmp_path):
        """DoD 1: rotation without excepcion after a previous one -> clears excepcion."""
        from scripts.flight_roster_writer import write_supervisor

        roster_data = {
            "active_roles": {
                "orquestador": {
                    "threadId": "mcp:orq-nuevo",
                    "predecessor_threadId": "mcp:orq-previo",
                    "version": 4,
                    "status": "active",
                },
                "supervisor": {
                    "threadId": "mcp:sup-diferente",
                    "session_code": "diferente",
                    "predecessor_threadId": "mcp:diferente-PREV",
                    "version": 2,
                    "status": "active",
                },
            },
            "excepcion_supervisor": {
                "coordinadora_threadId": "mcp:co-antigua",
                "supervisor_threadId": "mcp:sup-diferente",
                "motivo": "old",
                "desde": "2026-01-01",
            },
            "rules": {},
        }
        roster_p = tmp_path / "flight_roster.json"
        roster_p.write_text(json.dumps(roster_data, indent=2) + "\n", encoding="utf-8")
        changes_p = tmp_path / "roster_changes.jsonl"
        changes_p.write_text("", encoding="utf-8")

        result = write_supervisor(
            roster_p,
            "mcp:orq-previo",  # predecessor of mcp:orq-nuevo, no excepcion -> cleans excepcion
            "mcp:orq-previo-code",
            changes_log_path=changes_p,
            actor="test",
            reason="relevo normal",
        )

        assert "excepcion_supervisor" not in result

    def test_write_supervisor_no_op_same_threadid(self, tmp_path):
        """DoD 2: no-op when supervisor threadId already equals current supervisor."""
        from scripts.flight_roster_writer import write_supervisor

        # Build roster where supervisor.threadId = "mcp:sup-mismo"
        roster_data = {
            "active_roles": {
                "orquestador": {
                    "threadId": "mcp:orq-nuevo",
                    "predecessor_threadId": "mcp:orq-previo",
                    "session_code": "orq8",
                    "version": 4,
                    "status": "active",
                },
                "supervisor": {
                    "threadId": "mcp:sup-mismo",  # same as what we're passing
                    "session_code": "sup-mismo",
                    "predecessor_threadId": "",
                    "version": 3,
                    "status": "active",
                },
            },
            "rules": {},
        }
        roster_p = tmp_path / "flight_roster.json"
        roster_p.write_text(json.dumps(roster_data, indent=2) + "\n", encoding="utf-8")
        changes_p = tmp_path / "roster_changes.jsonl"
        changes_p.write_text(
            '{"ts":"2026-01-01","by":"x","change":"old","detail":"old","reason":"old"}\n',
            encoding="utf-8",
        )
        before = roster_p.read_bytes()
        log_before = changes_p.read_bytes()

        result = write_supervisor(
            roster_p,
            "mcp:sup-mismo",  # same as current supervisor.threadId -> no-op
            "mcp:sup-mismo-sup-nuevo",  # different session_code
            changes_log_path=changes_p,
            actor="test",
            reason="no-op",
        )

        after = roster_p.read_bytes()
        log_after = changes_p.read_bytes()
        assert after == before
        assert log_after == log_before
        # session_code should NOT be corrected (no-op wins)
        assert result["active_roles"]["supervisor"]["session_code"] == "sup-mismo"
        assert result["active_roles"]["supervisor"]["version"] == 3

    def test_write_supervisor_supervisor_is_orquestador(self, tmp_path):
        """DoD 2: nuevo supervisor = orquestador activo -> RosterInvalidSupervisor."""
        from scripts.flight_roster_writer import (
            RosterInvalidSupervisor,
            write_supervisor,
        )

        roster_p = self._make_roster_with_predecessor(
            tmp_path, "orq-previo", "sup-viejo", "sup-antiguo"
        )
        changes_p = tmp_path / "roster_changes.jsonl"
        changes_p.write_text("", encoding="utf-8")

        with pytest.raises(RosterInvalidSupervisor):
            write_supervisor(
                roster_p,
                "orq-previo",
                "orq7-code",
                changes_log_path=changes_p,
                actor="test",
                reason="invalid",
            )

    def test_write_supervisor_in_cascada(self, tmp_path):
        """DoD 2: threadId ya en la cascada -> RosterInvalidSupervisor."""
        from scripts.flight_roster_writer import (
            RosterInvalidSupervisor,
            write_supervisor,
        )

        roster_data = {
            "active_roles": {
                "orquestador": {
                    "threadId": "orq-nuevo",
                    "predecessor_threadId": "orq-previo",
                    "version": 4,
                    "status": "active",
                },
                "supervisor": {
                    "threadId": "sup-nuevo",
                    "session_code": "sup-nuevo",
                    "version": 3,
                    "status": "active",
                },
            },
            "rules": {},
            "cadena_contexto": [
                {
                    "threadId": "orq-previo",
                    "session_code": "orq7",
                    "hasta": "2026-01-01",
                }
            ],
        }
        roster_p = tmp_path / "flight_roster.json"
        roster_p.write_text(json.dumps(roster_data, indent=2) + "\n", encoding="utf-8")
        changes_p = tmp_path / "roster_changes.jsonl"
        changes_p.write_text("", encoding="utf-8")

        with pytest.raises(RosterInvalidSupervisor):
            write_supervisor(
                roster_p,
                "orq-previo",
                "orq7-code",
                changes_log_path=changes_p,
                actor="test",
                reason="in cascada",
            )

    def test_write_supervisor_missing_supervisor_mapping(self, tmp_path):
        """DoD 2: active_roles.supervisor ausente -> RosterInvalidSupervisor."""
        from scripts.flight_roster_writer import (
            RosterInvalidSupervisor,
            write_supervisor,
        )

        roster_data = {
            "active_roles": {
                "orquestador": {
                    "threadId": "orq-previo",
                    "predecessor_threadId": "sup-viejo",
                    "version": 3,
                    "status": "active",
                },
            },
            "rules": {},
        }
        roster_p = tmp_path / "flight_roster.json"
        roster_p.write_text(json.dumps(roster_data, indent=2) + "\n", encoding="utf-8")
        changes_p = tmp_path / "roster_changes.jsonl"
        changes_p.write_text("", encoding="utf-8")

        with pytest.raises(RosterInvalidSupervisor):
            write_supervisor(
                roster_p,
                "sup-nuevo",
                "sup-nuevo-code",
                changes_log_path=changes_p,
                actor="test",
                reason="missing",
            )

    def test_write_supervisor_no_excepcion_cuando_difiere(self, tmp_path):
        """DoD 2: supervisor != predecessor sin excepcion -> RosterInvalidSupervisor."""
        from scripts.flight_roster_writer import (
            RosterInvalidSupervisor,
            write_supervisor,
        )

        roster_p = self._make_roster_with_predecessor(
            tmp_path, "orq-previo", "sup-viejo", "sup-antiguo"
        )
        changes_p = tmp_path / "roster_changes.jsonl"
        changes_p.write_text("", encoding="utf-8")

        with pytest.raises(RosterInvalidSupervisor):
            write_supervisor(
                roster_p,
                "sup-diferente",
                "diferente-code",
                changes_log_path=changes_p,
                actor="test",
                reason="missing exception",
            )

    def test_write_supervisor_ts_rejected(self, tmp_path):
        """ts by argument -> ValueError."""
        from scripts.flight_roster_writer import write_supervisor

        roster_p = self._make_roster_with_predecessor(
            tmp_path, "orq-previo", "sup-viejo", "sup-antiguo"
        )
        changes_p = tmp_path / "roster_changes.jsonl"
        changes_p.write_text("", encoding="utf-8")

        with pytest.raises(ValueError, match="ts por argumento"):
            write_supervisor(
                roster_p,
                "orq-previo",
                "orq7-code",
                changes_log_path=changes_p,
                actor="test",
                reason="relevo",
                ts="2026-01-01",
            )

    def test_write_supervisor_cas_conflict_two_attempts(self, tmp_path):
        """CAS conflict in both attempts -> RosterWriteConflict."""
        import copy

        from scripts.flight_roster_writer import (
            RosterWriteConflict,
            write_supervisor,
        )

        roster_p = self._make_roster_with_predecessor(
            tmp_path, "orq-previo", "sup-viejo", "sup-antiguo"
        )
        changes_p = tmp_path / "roster_changes.jsonl"
        changes_p.write_text("", encoding="utf-8")

        _idx = [0]
        side_effects = [
            {  # idx 0: validation read
                "active_roles": {
                    "orquestador": {
                        "threadId": "mcp:orq-nuevo",
                        "predecessor_threadId": "mcp:orq-previo",
                        "session_code": "orq8",
                        "version": 1,
                    },
                    "supervisor": {
                        "threadId": "mcp:sup-antiguo",
                        "session_code": "sup-antiguo",
                        "version": 1,
                    },
                },
                "rules": {},
            },
            {  # idx 1: CAS read 1
                "active_roles": {
                    "orquestador": {
                        "threadId": "mcp:orq-nuevo",
                        "predecessor_threadId": "mcp:orq-previo",
                        "session_code": "orq8",
                        "version": 1,
                    },
                    "supervisor": {
                        "threadId": "mcp:sup-antiguo",
                        "session_code": "sup-antiguo",
                        "version": 1,
                    },
                },
                "rules": {},
            },
            {  # idx 2: CAS read 2
                "active_roles": {
                    "orquestador": {
                        "threadId": "mcp:orq-nuevo",
                        "predecessor_threadId": "mcp:orq-previo",
                        "session_code": "orq8",
                        "version": 2,
                    },
                    "supervisor": {
                        "threadId": "mcp:sup-antiguo",
                        "session_code": "sup-antiguo",
                        "version": 2,
                    },
                },
                "rules": {},
            },
            {  # idx 3: CAS read 3 (stale)
                "active_roles": {
                    "orquestador": {
                        "threadId": "mcp:orq-nuevo",
                        "predecessor_threadId": "mcp:orq-previo",
                        "session_code": "orq8",
                        "version": 2,
                    },
                    "supervisor": {
                        "threadId": "mcp:sup-antiguo",
                        "session_code": "sup-antiguo",
                        "version": 2,
                    },
                },
                "rules": {},
            },
            {  # idx 4: extra stale
                "active_roles": {
                    "orquestador": {
                        "threadId": "mcp:orq-nuevo",
                        "predecessor_threadId": "mcp:orq-previo",
                        "session_code": "orq8",
                        "version": 2,
                    },
                    "supervisor": {
                        "threadId": "mcp:sup-antiguo",
                        "session_code": "sup-antiguo",
                        "version": 2,
                    },
                },
                "rules": {},
            },
        ]

        def mock_read(path):
            idx = _idx[0]
            _idx[0] += 1
            if idx >= len(side_effects):
                idx = len(side_effects) - 1
            return copy.deepcopy(side_effects[idx])

        # Simulate write conflicts on first two attempts.
        _write_attempt = [0]

        def mock_atomic_write(path, data):
            _write_attempt[0] += 1
            if _write_attempt[0] <= 2:
                # Simulate CAS failure: a concurrent writer bumped the version
                raise RosterWriteConflict(
                    f"conflicto de escritura (intento {_write_attempt[0]}: "
                    f"conflicto de version)"
                )

        with (
            unittest.mock.patch(
                "scripts.flight_roster_writer._read_roster", side_effect=mock_read
            ),
            unittest.mock.patch(
                "scripts.flight_roster_writer._atomic_write_json",
                side_effect=mock_atomic_write,
            ),
        ):
            pytest.raises(  # noqa: RUF061
                RosterWriteConflict,
                write_supervisor,
                roster_p,
                "mcp:orq-previo",
                "mcp:sup-nuevo-code",
                changes_log_path=changes_p,
                actor="test",
                reason="conflict",
            )

    def test_write_supervisor_cascada_orquestador(self, tmp_path):
        """F36: orquestador ya en cadena_contexto -> RosterInvalidSupervisor."""
        from scripts.flight_roster_writer import (
            RosterInvalidSupervisor,
            write_supervisor,
        )

        roster_data = {
            "active_roles": {
                "orquestador": {
                    "threadId": "orq-nuevo",
                    "predecessor_threadId": "orq-previo",
                    "session_code": "orq8",
                    "version": 4,
                    "status": "active",
                },
                "supervisor": {
                    "threadId": "sup-antiguo",
                    "session_code": "sup-antiguo",
                    "predecessor_threadId": "",
                    "version": 3,
                    "status": "active",
                },
            },
            "rules": {},
            "cadena_contexto": [
                {"threadId": "orq-nuevo", "session_code": "orq8", "hasta": "2026-01-01"}
            ],
        }
        roster_p = tmp_path / "flight_roster.json"
        roster_p.write_text(json.dumps(roster_data, indent=2) + "\n", encoding="utf-8")
        changes_p = tmp_path / "roster_changes.jsonl"
        changes_p.write_text("", encoding="utf-8")

        with pytest.raises(RosterInvalidSupervisor):
            write_supervisor(
                roster_p,
                "orq-nuevo",  # = predecessor, but orquestador ya en cascada
                "orq8-code",
                changes_log_path=changes_p,
                actor="test",
                reason="orquestador in cascada",
            )

    def test_write_supervisor_cascada_supervisor_is_orquestador(self, tmp_path):
        """F36: supervisor saliente == orquestador activo -> RosterInvalidSupervisor."""
        from scripts.flight_roster_writer import (
            RosterInvalidSupervisor,
            write_supervisor,
        )

        roster_data = {
            "active_roles": {
                "orquestador": {
                    "threadId": "orq-previo",
                    "predecessor_threadId": "sup-viejo",
                    "version": 3,
                    "status": "active",
                },
                "supervisor": {
                    "threadId": "orq-previo",
                    "session_code": "orq7",
                    "version": 2,
                    "status": "active",
                },
            },
            "rules": {},
        }
        roster_p = tmp_path / "flight_roster.json"
        roster_p.write_text(json.dumps(roster_data, indent=2) + "\n", encoding="utf-8")
        changes_p = tmp_path / "roster_changes.jsonl"
        changes_p.write_text("", encoding="utf-8")

        with pytest.raises(RosterInvalidSupervisor):
            write_supervisor(
                roster_p,
                "sup-nuevo",
                "sup-nuevo-code",
                changes_log_path=changes_p,
                actor="test",
                reason="supervisor is orquestador",
            )

    def test_write_supervisor_active_roles_not_mapping(self, tmp_path):
        """F37: active_roles no es mapping -> RosterInvalidSupervisor."""
        from scripts.flight_roster_writer import (
            RosterInvalidSupervisor,
            write_supervisor,
        )

        roster_data = {"active_roles": None, "rules": {}}
        roster_p = tmp_path / "flight_roster.json"
        roster_p.write_text(json.dumps(roster_data, indent=2) + "\n", encoding="utf-8")
        changes_p = tmp_path / "roster_changes.jsonl"
        changes_p.write_text("", encoding="utf-8")

        with pytest.raises(RosterInvalidSupervisor):
            write_supervisor(
                roster_p,
                "mcp:valid",
                "code",
                changes_log_path=changes_p,
                actor="test",
                reason="active_roles None",
            )

    def test_write_supervisor_supervisor_not_mapping(self, tmp_path):
        """F37: active_roles.supervisor no es mapping -> RosterInvalidSupervisor."""
        from scripts.flight_roster_writer import (
            RosterInvalidSupervisor,
            write_supervisor,
        )

        roster_data = {
            "active_roles": {
                "orquestador": {
                    "threadId": "orq-previo",
                    "version": 1,
                    "status": "active",
                },
                "supervisor": "not-a-mapping",
            },
            "rules": {},
        }
        roster_p = tmp_path / "flight_roster.json"
        roster_p.write_text(json.dumps(roster_data, indent=2) + "\n", encoding="utf-8")
        changes_p = tmp_path / "roster_changes.jsonl"
        changes_p.write_text("", encoding="utf-8")

        with pytest.raises(RosterInvalidSupervisor):
            write_supervisor(
                roster_p,
                "mcp:new",
                "code",
                changes_log_path=changes_p,
                actor="test",
                reason="supervisor not mapping",
            )

    def test_write_supervisor_orquestador_not_mapping(self, tmp_path):
        """F37: active_roles.orquestador no es mapping -> RosterInvalidSupervisor."""
        from scripts.flight_roster_writer import (
            RosterInvalidSupervisor,
            write_supervisor,
        )

        roster_data = {
            "active_roles": {
                "orquestador": "not-a-mapping",
                "supervisor": {"threadId": "mcp:sup", "version": 1, "status": "active"},
            },
            "rules": {},
        }
        roster_p = tmp_path / "flight_roster.json"
        roster_p.write_text(json.dumps(roster_data, indent=2) + "\n", encoding="utf-8")
        changes_p = tmp_path / "roster_changes.jsonl"
        changes_p.write_text("", encoding="utf-8")

        with pytest.raises(RosterInvalidSupervisor):
            write_supervisor(
                roster_p,
                "mcp:new",
                "code",
                changes_log_path=changes_p,
                actor="test",
                reason="orquestador not mapping",
            )

    def test_write_supervisor_missing_fields(self, tmp_path):
        """DoD 2: active_roles.supervisor sin threadId/session_code/version -> RosterInvalidSupervisor."""
        from scripts.flight_roster_writer import (
            RosterInvalidSupervisor,
            write_supervisor,
        )

        roster_data = {
            "active_roles": {
                "orquestador": {
                    "threadId": "orq-nuevo",
                    "predecessor_threadId": "orq-previo",
                    "version": 4,
                    "status": "active",
                },
                "supervisor": {
                    "status": "active",
                    # missing threadId, session_code, version
                },
            },
            "rules": {},
        }
        roster_p = tmp_path / "flight_roster.json"
        roster_p.write_text(json.dumps(roster_data, indent=2) + "\n", encoding="utf-8")
        changes_p = tmp_path / "roster_changes.jsonl"
        changes_p.write_text("", encoding="utf-8")

        with pytest.raises(RosterInvalidSupervisor):
            write_supervisor(
                roster_p,
                "mcp:new",
                "code",
                changes_log_path=changes_p,
                actor="test",
                reason="missing fields",
            )

    def test_write_supervisor_orquestador_missing_fields(self, tmp_path):
        """DoD 2: active_roles.orquestador sin predecessor_threadId -> RosterInvalidSupervisor."""
        from scripts.flight_roster_writer import (
            RosterInvalidSupervisor,
            write_supervisor,
        )

        roster_data = {
            "active_roles": {
                "orquestador": {
                    "threadId": "orq-nuevo",
                    # missing predecessor_threadId
                    "version": 4,
                    "status": "active",
                },
                "supervisor": {
                    "threadId": "sup-antiguo",
                    "session_code": "sup-antiguo",
                    "version": 3,
                    "status": "active",
                },
            },
            "rules": {},
        }
        roster_p = tmp_path / "flight_roster.json"
        roster_p.write_text(json.dumps(roster_data, indent=2) + "\n", encoding="utf-8")
        changes_p = tmp_path / "roster_changes.jsonl"
        changes_p.write_text("", encoding="utf-8")

        with pytest.raises(RosterInvalidSupervisor):
            write_supervisor(
                roster_p,
                "orq-nuevo",
                "orq8-code",
                changes_log_path=changes_p,
                actor="test",
                reason="orquestador missing predecessor",
            )

    def test_write_supervisor_excepcion_given_but_supervisor_is_predecessor(
        self, tmp_path
    ):
        """DoD 2: excepcion pasada pero supervisor == predecesor -> RosterInvalidSupervisor."""
        from scripts.flight_roster_writer import (
            RosterInvalidSupervisor,
            write_supervisor,
        )

        roster_p = self._make_roster_with_predecessor(
            tmp_path, "orq-previo", "sup-viejo", "sup-antiguo"
        )
        changes_p = tmp_path / "roster_changes.jsonl"
        changes_p.write_text("", encoding="utf-8")

        with pytest.raises(RosterInvalidSupervisor):
            write_supervisor(
                roster_p,
                "sup-viejo",  # = predecessor
                "sup-viejo-code",
                changes_log_path=changes_p,
                actor="test",
                reason="excepcion redundante",
                excepcion="motivo",
            )

    def test_write_supervisor_two_consecutive_rotations_first_level_cascada(
        self, tmp_path
    ):
        """R1: two consecutive rotations leave BOTH outgoing supervisors in
        first-level cascada, most recent first, without nested
        active_roles.orquestador.cadena_contexto."""
        from scripts.flight_roster_writer import write_supervisor

        # Initial roster: orq-2 (predecessor=sup-B), sup-A current.
        # We want to rotate sup-A -> sup-B (who is predecessor of orq-2).
        roster_data = {
            "active_roles": {
                "orquestador": {
                    "threadId": "mcp:orq-2",
                    "predecessor_threadId": "mcp:sup-B",
                    "session_code": "orq2",
                    "version": 3,
                    "status": "active",
                },
                "supervisor": {
                    "threadId": "mcp:sup-A",
                    "session_code": "supA",
                    "predecessor_threadId": "",
                    "version": 1,
                    "status": "active",
                },
            },
            "rules": {},
        }
        roster_p = tmp_path / "flight_roster.json"
        roster_p.write_text(json.dumps(roster_data, indent=2) + "\n", encoding="utf-8")
        changes_p = tmp_path / "roster_changes.jsonl"
        changes_p.write_text("", encoding="utf-8")

        # First rotation: sup-B (predecessor of orq-2, != current sup-A) -> moves sup-A to cascada.
        result1 = write_supervisor(
            roster_p,
            "mcp:sup-B",
            "mcp:supB-code",
            changes_log_path=changes_p,
            actor="test",
            reason="first rotation",
        )

        # cascada has sup-A at first level (the outgoing supervisor)
        cad1 = result1["cadena_contexto"]
        assert isinstance(cad1, list)
        assert len(cad1) == 1
        assert cad1[0]["threadId"] == "mcp:sup-A"
        # No nested cascada under orquestador
        assert "cadena_contexto" not in result1["active_roles"]["orquestador"]
        # New supervisor is now sup-B
        assert result1["active_roles"]["supervisor"]["threadId"] == "mcp:sup-B"

        # Second rotation: rotate sup-B -> sup-C (new predecessor of a new orq).
        # This time the new supervisor IS the old supervisor, so it's a no-op.
        # To get a second real rotation, we need a roster where the current
        # supervisor differs from the predecessor being set.
        # Build: orq-3 (predecessor=sup-D), sup-B current, sup-D is the new sup.
        roster_data2 = {
            "active_roles": {
                "orquestador": {
                    "threadId": "mcp:orq-3",
                    "predecessor_threadId": "mcp:sup-D",
                    "session_code": "orq3",
                    "version": 4,
                    "status": "active",
                },
                "supervisor": {
                    "threadId": "mcp:sup-B",
                    "session_code": "supB",
                    "predecessor_threadId": "mcp:sup-A",
                    "version": 2,
                    "status": "active",
                },
            },
            "rules": {},
            # cascada already has sup-A at first level from first rotation
            "cadena_contexto": [
                {"threadId": "mcp:sup-A", "session_code": "supA", "hasta": "2026-01-01"}
            ],
        }
        roster_p.write_text(json.dumps(roster_data2, indent=2) + "\n", encoding="utf-8")
        changes_p.write_text("", encoding="utf-8")

        result = write_supervisor(
            roster_p,
            "mcp:sup-D",  # predecessor of orq-3, != current sup-B
            "mcp:supD-code",
            changes_log_path=changes_p,
            actor="test",
            reason="second rotation",
        )

        # cascada at first level: [sup-B, sup-A] (most recent first)
        cad = result["cadena_contexto"]
        assert isinstance(cad, list)
        assert len(cad) == 2
        assert cad[0]["threadId"] == "mcp:sup-B"
        assert cad[1]["threadId"] == "mcp:sup-A"

        # No nested cascada under orquestador.
        assert "cadena_contexto" not in result["active_roles"]["orquestador"]

        # Log has 1 supervisor_rotation line (fresh log for second rotation).
        log_lines = [
            line
            for line in changes_p.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert len(log_lines) == 1
        assert "supervisor_rotation" in log_lines[0]

    # --- No-op precedence (plan DoD 2, work_plan l.44 and l.125): when the requested
    # --- threadId is already the active supervisor the no-op WINS, nothing is
    # --- written and the log does not grow, even if the rest of the data is corrupt.

    def _noop_roster(self, mutate=None) -> dict:
        """Rotation roster whose active supervisor is the one requested by the no-op cases."""
        roster = _rotation_roster()
        if mutate is not None:
            mutate(roster)
        return roster

    def _assert_noop_untouched(self, tmp_path, roster, thread):
        """Call write_supervisor and assert it neither raised nor touched roster/log."""
        from scripts.flight_roster_writer import write_supervisor

        roster_p, changes_p = _write_rotation_files(tmp_path, roster)
        before_r, before_l = roster_p.read_bytes(), changes_p.read_bytes()
        write_supervisor(
            roster_p,
            thread,
            "sv",
            changes_log_path=changes_p,
            actor="test",
            reason="noop",
        )
        assert roster_p.read_bytes() == before_r
        assert changes_p.read_bytes() == before_l

    def test_a_noop_wins_when_supervisor_equals_orchestrator(self, tmp_path):
        """A: corrupt roster (supervisor == orchestrator), same id requested -> no-op."""

        def mutate(r):
            r["active_roles"]["supervisor"]["threadId"] = "mcp:orq-actual"

        self._assert_noop_untouched(
            tmp_path, self._noop_roster(mutate), "mcp:orq-actual"
        )

    def test_b_noop_wins_when_supervisor_is_also_in_cascade(self, tmp_path):
        """B: the plan's literal case, already fixed and also in the cascade -> no-op."""

        def mutate(r):
            r["cadena_contexto"] = [{"threadId": "mcp:sup-viejo", "session_code": "sv"}]

        self._assert_noop_untouched(
            tmp_path, self._noop_roster(mutate), "mcp:sup-viejo"
        )

    def test_c_noop_wins_with_corrupt_cascade(self, tmp_path):
        """C: already fixed and cadena_contexto is garbage (string) -> no-op."""

        def mutate(r):
            r["cadena_contexto"] = "corrupta"

        self._assert_noop_untouched(
            tmp_path, self._noop_roster(mutate), "mcp:sup-viejo"
        )

    def test_d_noop_wins_when_orchestrator_is_in_cascade(self, tmp_path):
        """D: already fixed and the orchestrator figures in the cascade -> no-op."""

        def mutate(r):
            r["cadena_contexto"] = [
                {"threadId": "mcp:orq-actual", "session_code": "oa"}
            ]

        self._assert_noop_untouched(
            tmp_path, self._noop_roster(mutate), "mcp:sup-viejo"
        )

    def test_e1_noop_does_not_mask_requesting_the_orchestrator(self, tmp_path):
        """E1 control: a different supervisor is fixed and the orchestrator is requested -> raises."""
        from scripts.flight_roster_writer import (
            RosterInvalidSupervisor,
            write_supervisor,
        )

        roster_p, changes_p = _write_rotation_files(tmp_path, self._noop_roster())
        before = roster_p.read_bytes()
        with pytest.raises(RosterInvalidSupervisor):
            write_supervisor(
                roster_p,
                "mcp:orq-actual",
                "sv",
                changes_log_path=changes_p,
                actor="test",
                reason="e1",
            )
        assert roster_p.read_bytes() == before
        assert changes_p.read_text(encoding="utf-8") == ""

    def test_e2_noop_does_not_mask_corrupt_cascade_for_another_supervisor(
        self, tmp_path
    ):
        """E2 control: corrupt cascade and a supervisor other than the fixed one -> raises."""
        from scripts.flight_roster_writer import (
            RosterInvalidSupervisor,
            write_supervisor,
        )

        def mutate(r):
            r["cadena_contexto"] = "corrupta"

        roster_p, changes_p = _write_rotation_files(tmp_path, self._noop_roster(mutate))
        before = roster_p.read_bytes()
        with pytest.raises(RosterInvalidSupervisor):
            write_supervisor(
                roster_p,
                "mcp:sup-previo",
                "sp",
                changes_log_path=changes_p,
                actor="test",
                reason="e2",
            )
        assert roster_p.read_bytes() == before
        assert changes_p.read_text(encoding="utf-8") == ""


class TestT1McpPrefix:
    """T1: mcp: prefix validation on write_supervisor supervisor threadId."""

    def test_write_supervisor_predecessor_without_mcp_prefix_raises(self, tmp_path):
        """T1: rotation where supervisor (predecessor) lacks mcp: prefix -> RosterInvalidSupervisor.

        The predecessor "sup-viejo" is otherwise valid (exists, not orquestador, etc.)
        but the mcp: prefix check must catch it. Roster must be byte-identical
        and log must not grow.
        """
        from scripts.flight_roster_writer import (
            RosterInvalidSupervisor,
            write_supervisor,
        )

        roster_data = {
            "active_roles": {
                "orquestador": {
                    "threadId": "mcp:orq-nuevo",
                    "predecessor_threadId": "sup-viejo",  # NO mcp: prefix
                    "session_code": "orq8",
                    "version": 4,
                    "status": "active",
                },
                "supervisor": {
                    "threadId": "mcp:sup-antiguo",
                    "session_code": "sup-antiguo",
                    "predecessor_threadId": "",
                    "version": 3,
                    "status": "active",
                },
            },
            "rules": {},
        }
        roster_p = tmp_path / "flight_roster.json"
        roster_p.write_text(
            json.dumps(roster_data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        changes_p = tmp_path / "roster_changes.jsonl"
        changes_p.write_text(
            '{"ts":"2026-01-01","by":"x","change":"old","detail":"old","reason":"old"}\n',
            encoding="utf-8",
        )

        before_roster = roster_p.read_bytes()
        before_log = changes_p.read_bytes()

        with pytest.raises(RosterInvalidSupervisor):
            write_supervisor(
                roster_p,
                "sup-viejo",  # predecessor without mcp: prefix
                "sup-viejo-code",
                changes_log_path=changes_p,
                actor="test",
                reason="missing prefix",
            )

        after_roster = roster_p.read_bytes()
        after_log = changes_p.read_bytes()
        assert before_roster == after_roster, "Roster must be byte-identical"
        assert before_log == after_log, "Changes log must not grow"


class TestT2RequiredException:
    """T2: required exception validation in write_supervisor."""

    def test_rotation_non_predecessor_without_exception_raises(self, tmp_path):
        """T2: rotation to valid mcp: threadId that is NOT predecessor and no excepcion -> RosterInvalidSupervisor."""
        from scripts.flight_roster_writer import (
            RosterInvalidSupervisor,
            write_supervisor,
        )

        roster_data = {
            "active_roles": {
                "orquestador": {
                    "threadId": "mcp:orq-nuevo",
                    "predecessor_threadId": "mcp:orq-previo",
                    "session_code": "orq8",
                    "version": 4,
                    "status": "active",
                },
                "supervisor": {
                    "threadId": "mcp:sup-antiguo",
                    "session_code": "sup-antiguo",
                    "predecessor_threadId": "",
                    "version": 3,
                    "status": "active",
                },
            },
            "rules": {},
        }
        roster_p = tmp_path / "flight_roster.json"
        roster_p.write_text(
            json.dumps(roster_data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        changes_p = tmp_path / "roster_changes.jsonl"
        changes_p.write_text("", encoding="utf-8")

        before_roster = roster_p.read_bytes()
        before_log = changes_p.read_bytes()

        with pytest.raises(RosterInvalidSupervisor):
            write_supervisor(
                roster_p,
                "mcp:sup-distinto",  # valid mcp: but not predecessor
                "mcp:distinto-code",
                changes_log_path=changes_p,
                actor="test",
                reason="no exception",
            )

        after_roster = roster_p.read_bytes()
        after_log = changes_p.read_bytes()
        assert before_roster == after_roster
        assert before_log == after_log

    def test_rotation_empty_excepcion_treated_as_absent(self, tmp_path):
        """T2: excepcion="" (empty string) normalizes to absent -> same as no exception."""
        from scripts.flight_roster_writer import (
            RosterInvalidSupervisor,
            write_supervisor,
        )

        roster_data = {
            "active_roles": {
                "orquestador": {
                    "threadId": "mcp:orq-nuevo",
                    "predecessor_threadId": "mcp:orq-previo",
                    "session_code": "orq8",
                    "version": 4,
                    "status": "active",
                },
                "supervisor": {
                    "threadId": "mcp:sup-antiguo",
                    "session_code": "sup-antiguo",
                    "predecessor_threadId": "",
                    "version": 3,
                    "status": "active",
                },
            },
            "rules": {},
        }
        roster_p = tmp_path / "flight_roster.json"
        roster_p.write_text(
            json.dumps(roster_data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        changes_p = tmp_path / "roster_changes.jsonl"
        changes_p.write_text("", encoding="utf-8")

        with pytest.raises(RosterInvalidSupervisor):
            write_supervisor(
                roster_p,
                "mcp:sup-distinto",
                "mcp:distinto-code",
                changes_log_path=changes_p,
                actor="test",
                reason="excepcion vacio",
                excepcion="",  # empty -> normalized to absent
            )

    def test_rotation_whitespace_excepcion_treated_as_absent(self, tmp_path):
        """T2: excepcion='   ' (only spaces) normalizes to absent -> RosterInvalidSupervisor."""
        from scripts.flight_roster_writer import (
            RosterInvalidSupervisor,
            write_supervisor,
        )

        roster_data = {
            "active_roles": {
                "orquestador": {
                    "threadId": "mcp:orq-nuevo",
                    "predecessor_threadId": "mcp:orq-previo",
                    "session_code": "orq8",
                    "version": 4,
                    "status": "active",
                },
                "supervisor": {
                    "threadId": "mcp:sup-antiguo",
                    "session_code": "sup-antiguo",
                    "predecessor_threadId": "",
                    "version": 3,
                    "status": "active",
                },
            },
            "rules": {},
        }
        roster_p = tmp_path / "flight_roster.json"
        roster_p.write_text(
            json.dumps(roster_data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        changes_p = tmp_path / "roster_changes.jsonl"
        changes_p.write_text("", encoding="utf-8")

        with pytest.raises(RosterInvalidSupervisor):
            write_supervisor(
                roster_p,
                "mcp:sup-distinto",
                "mcp:distinto-code",
                changes_log_path=changes_p,
                actor="test",
                reason="excepcion spaces",
                excepcion="   ",  # whitespace only -> normalized to absent
            )

    def test_rotation_orquestador_without_predecessor_and_no_exception_raises(
        self, tmp_path
    ):
        """T2: orquestador sin predecessor_threadId, sin excepcion -> RosterInvalidSupervisor."""
        from scripts.flight_roster_writer import (
            RosterInvalidSupervisor,
            write_supervisor,
        )

        roster_data = {
            "active_roles": {
                "orquestador": {
                    "threadId": "mcp:orq-nuevo",
                    # sin predecessor_threadId
                    "session_code": "orq8",
                    "version": 4,
                    "status": "active",
                },
                "supervisor": {
                    "threadId": "mcp:sup-antiguo",
                    "session_code": "sup-antiguo",
                    "predecessor_threadId": "",
                    "version": 3,
                    "status": "active",
                },
            },
            "rules": {},
        }
        roster_p = tmp_path / "flight_roster.json"
        roster_p.write_text(
            json.dumps(roster_data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        changes_p = tmp_path / "roster_changes.jsonl"
        changes_p.write_text("", encoding="utf-8")

        with pytest.raises(RosterInvalidSupervisor):
            write_supervisor(
                roster_p,
                "mcp:sup-distinto",
                "mcp:distinto-code",
                changes_log_path=changes_p,
                actor="test",
                reason="sin predecesor ni excepcion",
            )


class TestT3CliMixingFlags:
    """T3: CLI mixing --role and --supervisor-thread -> rc 3."""

    def test_cli_role_and_supervisor_thread_together_rc3(self, tmp_path, capsys):
        """T3: --role and --estado together with --supervisor-thread and --supervisor-code -> exit 3."""
        from scripts.flight_roster_writer import main

        roster_data = {
            "active_roles": {
                "orquestador": {
                    "threadId": "mcp:orq-nuevo",
                    "predecessor_threadId": "mcp:orq-previo",
                    "version": 4,
                    "status": "active",
                },
                "supervisor": {
                    "threadId": "mcp:sup-antiguo",
                    "session_code": "sup-antiguo",
                    "version": 3,
                    "status": "active",
                },
            },
            "rules": {},
        }
        roster_p = tmp_path / "flight_roster.json"
        roster_p.write_text(
            json.dumps(roster_data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        changes_p = tmp_path / "roster_changes.jsonl"
        changes_p.write_text("", encoding="utf-8")

        rc = main(
            [
                "--roster",
                str(roster_p),
                "--role",
                "builder",
                "--estado",
                "ACTIVO",
                "--supervisor-thread",
                "mcp:orq-previo",
                "--supervisor-code",
                "mcp:orq7",
                "--changes-log",
                str(changes_p),
                "--actor",
                "test",
                "--reason",
                "mixed",
            ]
        )
        assert rc == 3, f"Expected rc 3 for mixed flags, got {rc}"

        err = capsys.readouterr().err
        assert "Traceback" not in err, "No traceback on validation error"

    def test_cli_role_without_supervisor_code_rc3(self, tmp_path, capsys):
        """T3: --role with only --supervisor-thread (no --supervisor-code) -> rc 3."""
        from scripts.flight_roster_writer import main

        roster_data = {
            "active_roles": {
                "orquestador": {
                    "threadId": "mcp:orq-nuevo",
                    "predecessor_threadId": "mcp:orq-previo",
                    "version": 4,
                    "status": "active",
                },
                "supervisor": {
                    "threadId": "mcp:sup-antiguo",
                    "session_code": "sup-antiguo",
                    "version": 3,
                    "status": "active",
                },
            },
            "rules": {},
        }
        roster_p = tmp_path / "flight_roster.json"
        roster_p.write_text(
            json.dumps(roster_data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        changes_p = tmp_path / "roster_changes.jsonl"
        changes_p.write_text("", encoding="utf-8")

        rc = main(
            [
                "--roster",
                str(roster_p),
                "--role",
                "builder",
                "--supervisor-thread",
                "mcp:orq-previo",
                "--changes-log",
                str(changes_p),
                "--actor",
                "test",
                "--reason",
                "role_plus_thread",
            ]
        )
        assert rc == 3, f"Expected rc 3 for role + thread only, got {rc}"

        err = capsys.readouterr().err
        assert "Traceback" not in err


def _rotation_roster() -> dict:
    """Inline roster for rotation tests: supervisor can rotate to the predecessor.

    Before: none. During: builds the dict only (no I/O). After: returns a roster
    whose orchestrator predecessor differs from the current supervisor.
    """
    return {
        "active_roles": {
            "orquestador": {
                "threadId": "mcp:orq-actual",
                "predecessor_threadId": "mcp:sup-previo",
                "session_code": "oa",
                "version": 4,
                "status": "active",
            },
            "supervisor": {
                "threadId": "mcp:sup-viejo",
                "session_code": "sv",
                "predecessor_threadId": "",
                "version": 3,
                "status": "active",
            },
        },
        "rules": {},
    }


def _write_rotation_files(tmp_path: Path, roster: dict) -> tuple[Path, Path]:
    """Write the roster and an empty changes log under tmp_path (LF, UTF-8)."""
    roster_p = tmp_path / "flight_roster.json"
    changes_p = tmp_path / "roster_changes.jsonl"
    roster_p.write_text(json.dumps(roster, indent=2) + "\n", encoding="utf-8")
    changes_p.write_text("", encoding="utf-8")
    return roster_p, changes_p


class TestCasRevalidation:
    """DoD 2 validations run on every CAS attempt over the freshly read state."""

    def _rotate_with_midflight_change(self, tmp_path, monkeypatch, mutate):
        """Run write_supervisor while another writer changes the file after read 1.

        Before: tmp_path available. During: wraps the module reader so that,
        after the first read, the on-disk roster is rewritten by `mutate`
        without touching any version (so the CAS version check still passes).
        After: returns (roster_path, changes_path, bytes_before_rotation).
        """
        import scripts.flight_roster_writer as fw

        roster_p, changes_p = _write_rotation_files(tmp_path, _rotation_roster())
        real_read = fw._read_roster
        calls = {"n": 0}

        def reader(path):
            data = real_read(path)
            calls["n"] += 1
            if calls["n"] == 1:
                changed = json.loads(Path(path).read_text(encoding="utf-8"))
                mutate(changed)
                Path(path).write_text(
                    json.dumps(changed, indent=2) + "\n", encoding="utf-8"
                )
            return data

        monkeypatch.setattr(fw, "_read_roster", reader)
        return roster_p, changes_p

    def test_b1_reread_with_orchestrator_in_cascade_fails_closed(
        self, tmp_path, monkeypatch
    ):
        """M-B: a re-read state with the orchestrator already in the cascade must not be written."""
        from scripts.flight_roster_writer import (
            RosterInvalidSupervisor,
            write_supervisor,
        )

        def mutate(changed):
            changed["cadena_contexto"] = [
                {"threadId": "mcp:orq-actual", "session_code": "oa"}
            ]

        roster_p, changes_p = self._rotate_with_midflight_change(
            tmp_path, monkeypatch, mutate
        )
        with pytest.raises(RosterInvalidSupervisor):
            write_supervisor(
                roster_p,
                "mcp:sup-previo",
                "sp",
                changes_log_path=changes_p,
                actor="test",
                reason="b1",
            )
        after = json.loads(roster_p.read_text(encoding="utf-8"))
        assert after["active_roles"]["supervisor"]["threadId"] == "mcp:sup-viejo"
        assert "supervisor_rotation" not in changes_p.read_text(encoding="utf-8")

    def test_b2_reread_with_other_predecessor_fails_closed(self, tmp_path, monkeypatch):
        """Control: a re-read predecessor change invalidates the requested supervisor."""
        from scripts.flight_roster_writer import (
            RosterInvalidSupervisor,
            write_supervisor,
        )

        def mutate(changed):
            changed["active_roles"]["orquestador"]["predecessor_threadId"] = (
                "mcp:otro-pred"
            )

        roster_p, changes_p = self._rotate_with_midflight_change(
            tmp_path, monkeypatch, mutate
        )
        with pytest.raises(RosterInvalidSupervisor):
            write_supervisor(
                roster_p,
                "mcp:sup-previo",
                "sp",
                changes_log_path=changes_p,
                actor="test",
                reason="b2",
            )
        after = json.loads(roster_p.read_text(encoding="utf-8"))
        assert after["active_roles"]["supervisor"]["threadId"] == "mcp:sup-viejo"
        assert "supervisor_rotation" not in changes_p.read_text(encoding="utf-8")


class TestGuardImportFailClosedSubprocess:
    """The writer fails closed when the guard helper cannot be imported (M10)."""

    @staticmethod
    def _run_isolated(tmp_path: Path, files: tuple[str, ...]):
        """Copy the named scripts into an isolated tree and run the writer CLI.

        Before: tmp_path available, the scripts exist in the real tree.
        During: creates the subdirectory (mkdir(parents=True)), copies all
        named files plus `flight/thread_id.py` to iso/scripts, and runs the copy
        as a subprocess with a foreign cwd, so no real module can be resolved.
        After: returns (CompletedProcess, roster_path, roster_bytes_before).
        """
        import shutil
        import subprocess
        import sys

        scripts_dir = Path(__file__).resolve().parents[2] / "scripts"
        iso = tmp_path / "iso" / "scripts"
        iso.mkdir(parents=True)
        for name in files:
            shutil.copy(scripts_dir / name, iso / name)
        # WOT-2026-136h (N1a): always copy flight/thread_id.py to the isolated tree.
        thread_id_src = scripts_dir / "flight" / "thread_id.py"
        if thread_id_src.exists():
            flight_dir = iso / "flight"
            flight_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy(thread_id_src, flight_dir / "thread_id.py")
        roster_p, changes_p = _write_rotation_files(tmp_path, _rotation_roster())
        before = roster_p.read_bytes()
        proc = subprocess.run(
            [
                sys.executable,
                str(iso / "flight_roster_writer.py"),
                "--roster",
                str(roster_p),
                "--changes-log",
                str(changes_p),
                "--actor",
                "test",
                "--reason",
                "import-check",
                "--supervisor-thread",
                "mcp:sup-previo",
                "--supervisor-code",
                "sp",
            ],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
        )
        return proc, roster_p, before

    def test_c1_missing_guard_module_fails_closed(self, tmp_path):
        """Without the guard module the rotation exits 3 and leaves the roster intact."""
        proc, roster_p, before = self._run_isolated(
            tmp_path, ("flight_roster_writer.py",)
        )
        assert proc.returncode == 3, proc.stdout + proc.stderr
        assert roster_p.read_bytes() == before
        assert "Traceback" not in proc.stderr

    def test_c2_guard_module_alongside_rotates(self, tmp_path):
        """Positive control: with the guard module next to the writer the same call rotates."""
        proc, roster_p, before = self._run_isolated(
            tmp_path,
            ("flight_roster_writer.py", "check_roster_matches_acting_thread.py"),
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert roster_p.read_bytes() != before
        data = json.loads(roster_p.read_text(encoding="utf-8"))
        assert data["active_roles"]["supervisor"]["threadId"] == "mcp:sup-previo"


# --- Tabular sweep of the CLI class: unexpected input => rc 3 + state intact,
# --- never a Traceback (WOT-2026-136f). Cells mirror the Manager sweep.

_SWEEP_GOOD_ROT = ["--supervisor-thread", "mcp:sup-previo", "--supervisor-code", "sp"]
_SWEEP_ROLE_OK = ["--role", "orquestador", "--estado", "PENDIENTE_ACK"]
_SWEEP_OPT = {
    "role": "--role",
    "estado": "--estado",
    "thread": "--supervisor-thread",
    "code": "--supervisor-code",
}


def _sweep_flag_cells() -> list:  # noqa: C901
    """Build the flags cells: 16 presence subsets x valid/invalid x +excepcion.

    Before: none.  During: pure enumeration (no I/O).  After: returns a list of
    pytest.param(flags, allowed_rc, id) covering role/estado/thread/code.
    """
    import itertools

    names = ("role", "estado", "thread", "code")
    cells = []
    for present in itertools.product((0, 1), repeat=4):
        d = dict(zip(names, present, strict=True))
        for valid in (True, False):
            for exc in (False, True):
                if not any(present) and not valid:
                    continue
                val = {
                    "role": "orquestador" if valid else "nope",
                    "estado": "PENDIENTE_ACK" if valid else "NOPE",
                    "thread": ("mcp:otro-sup" if exc else "mcp:sup-previo")
                    if valid
                    else "sin-prefijo",
                    "code": "sp" if valid else "",
                }
                flags: list[str] = []
                for n in names:
                    if d[n]:
                        flags += [_SWEEP_OPT[n], val[n]]
                if exc:
                    flags += ["--excepcion", "motivo-x"]
                role_complete = bool(d["role"] and d["estado"])
                role_any = bool(d["role"] or d["estado"])
                rot_any = bool(d["thread"] or d["code"])
                rot_complete = bool(d["thread"] and d["code"])
                if role_any and rot_any:
                    exp = {3}
                elif role_any:
                    exp = {0} if (role_complete and valid and not exc) else {3}
                elif rot_any:
                    exp = {0} if (rot_complete and valid) else {3}
                else:
                    exp = {3}
                ident = (
                    "flags-"
                    + "+".join(n for n in names if d[n])
                    + ("-valid" if valid else "-invalid")
                    + ("-exc" if exc else "")
                )
                cells.append(pytest.param(flags, exp, id=ident))
    return cells


def _sweep_mut(fn) -> dict:
    """Return a rotation roster mutated by fn (inline, no shared fixture)."""
    roster = _rotation_roster()
    fn(roster)
    return roster


_SWEEP_CHAIN_CELLS = [
    pytest.param(
        [{"threadId": "mcp:otro", "session_code": "x"}], {0}, id="cadena-lista-valida"
    ),
    pytest.param([], {0}, id="cadena-vacia"),
    pytest.param("__ABSENT__", {0}, id="cadena-ausente"),
    pytest.param("corrupta", {3}, id="cadena-string"),
    pytest.param({"a": 1}, {3}, id="cadena-dict"),
    pytest.param(5, {3}, id="cadena-int"),
    pytest.param(None, {0}, id="cadena-null-es-ausente"),
    pytest.param([1, "x"], {3}, id="cadena-elementos-no-dict"),
    pytest.param([{"session_code": "x"}], {3}, id="cadena-elemento-sin-threadid"),
]

_SWEEP_ROTATION_ROSTERS = {
    "active_roles-ausente": lambda r: r.pop("active_roles"),
    "active_roles-string": lambda r: r.__setitem__("active_roles", "x"),
    "orquestador-ausente": lambda r: r["active_roles"].pop("orquestador"),
    "orquestador-no-mapping": lambda r: r["active_roles"].__setitem__(
        "orquestador", "x"
    ),
    "orquestador-version-str": lambda r: r["active_roles"]["orquestador"].__setitem__(
        "version", "4"
    ),
    "supervisor-ausente": lambda r: r["active_roles"].pop("supervisor"),
    "supervisor-version-str": lambda r: r["active_roles"]["supervisor"].__setitem__(
        "version", "3"
    ),
    "supervisor-sin-session-code": lambda r: r["active_roles"]["supervisor"].pop(
        "session_code"
    ),
    "predecessor-int": lambda r: r["active_roles"]["orquestador"].__setitem__(
        "predecessor_threadId", 7
    ),
}

_SWEEP_ROLE_ROSTERS = {
    "active_roles-ausente": lambda r: r.pop("active_roles"),
    "active_roles-string": lambda r: r.__setitem__("active_roles", "x"),
    "rol-ausente": lambda r: r["active_roles"].pop("orquestador"),
    "rol-no-mapping": lambda r: r["active_roles"].__setitem__("orquestador", "x"),
    "estado-actual-invalido": lambda r: r["active_roles"]["orquestador"].__setitem__(
        "estado", "RARO"
    ),
    "rol-version-str": lambda r: r["active_roles"]["orquestador"].__setitem__(
        "version", "4"
    ),
}

_SWEEP_RAW_FILES = {
    "json-invalido": "{not json",
    "top-level-lista": "[1,2]",
    "vacio": "",
    "no-existe": None,
}


def _sweep_cli(tmp_path: Path, roster_obj, flags: list[str], raw=None):
    """Run the writer CLI in-process on a temp roster and report what happened.

    Before: tmp_path available.  During: writes the roster (object or raw text;
    raw None => no file), an empty log, runs main(argv); any exception that
    escapes main is a failure of the fail-closed contract.
    After: returns (rc, roster_and_log_untouched).
    """
    from scripts.flight_roster_writer import main

    roster_p = tmp_path / "flight_roster.json"
    changes_p = tmp_path / "roster_changes.jsonl"
    if roster_obj is not None:
        roster_p.write_text(json.dumps(roster_obj, indent=2) + "\n", encoding="utf-8")
    elif raw is not None:
        roster_p.write_text(raw, encoding="utf-8")
    changes_p.write_text("", encoding="utf-8")
    before_r = roster_p.read_bytes() if roster_p.exists() else None
    before_l = changes_p.read_bytes()
    argv = [
        "--roster", str(roster_p), "--changes-log", str(changes_p),
        "--actor", "test", "--reason", "sweep", *flags,
    ]  # fmt: skip
    try:
        rc = main(argv)
    except Exception as exc:  # the point is to detect any escape
        pytest.fail(f"excepcion escapo de main (Traceback en el CLI): {exc!r}")
    after_r = roster_p.read_bytes() if roster_p.exists() else None
    return rc, (before_r == after_r and before_l == changes_p.read_bytes())


class TestCliSweep:
    """Family F/C/R/M cells: rc in the allowed set, state intact on rc 3, no escape."""

    @pytest.mark.parametrize("flags,allowed", _sweep_flag_cells())
    def test_f_flag_cells(self, tmp_path, flags, allowed):
        """F: every flag combination gives the allowed rc; rc 3 leaves state intact."""
        rc, intact = _sweep_cli(tmp_path, _rotation_roster(), flags)
        assert rc in allowed, f"rc={rc}, permitido={sorted(allowed)}"
        assert rc != 3 or intact

    @pytest.mark.parametrize("chain,allowed", _SWEEP_CHAIN_CELLS)
    def test_c_cadena_contexto_cells(self, tmp_path, chain, allowed):
        """C: cadena_contexto of any type: valid/absent/null rotate, others fail closed."""
        roster = _rotation_roster()
        if chain != "__ABSENT__":
            roster["cadena_contexto"] = chain
        rc, intact = _sweep_cli(tmp_path, roster, _SWEEP_GOOD_ROT)
        assert rc in allowed, f"rc={rc}, permitido={sorted(allowed)}"
        assert rc != 3 or intact

    @pytest.mark.parametrize("name", sorted(_SWEEP_ROTATION_ROSTERS))
    def test_r_rotation_roster_shape_cells(self, tmp_path, name):
        """R: malformed roster shapes fail closed (rc 3, state intact) in rotation mode."""
        roster = _sweep_mut(_SWEEP_ROTATION_ROSTERS[name])
        rc, intact = _sweep_cli(tmp_path, roster, _SWEEP_GOOD_ROT)
        assert rc == 3 and intact

    def test_r_stale_excepcion_string_is_cleaned_or_rejected(self, tmp_path):
        """R: a stale malformed excepcion_supervisor is cleaned by a rotation (rc 0) or rc 3."""
        roster = _sweep_mut(lambda r: r.__setitem__("excepcion_supervisor", "x"))
        rc, intact = _sweep_cli(tmp_path, roster, _SWEEP_GOOD_ROT)
        assert rc in {0, 3}
        assert rc != 3 or intact

    @pytest.mark.parametrize("raw_name", sorted(_SWEEP_RAW_FILES))
    def test_r_rotation_unreadable_file_cells(self, tmp_path, raw_name):
        """R: unreadable / non-mapping roster file fails closed in rotation mode."""
        rc, intact = _sweep_cli(
            tmp_path, None, _SWEEP_GOOD_ROT, raw=_SWEEP_RAW_FILES[raw_name]
        )
        assert rc == 3 and intact

    @pytest.mark.parametrize("name", sorted(_SWEEP_ROLE_ROSTERS))
    def test_m_role_mode_roster_shape_cells(self, tmp_path, name):
        """M: malformed roster shapes fail closed (rc 3, state intact) in role mode."""
        roster = _sweep_mut(_SWEEP_ROLE_ROSTERS[name])
        rc, intact = _sweep_cli(tmp_path, roster, _SWEEP_ROLE_OK)
        assert rc == 3 and intact

    def test_m_role_mode_forbidden_transition(self, tmp_path):
        """M: a transition not in the table (ACTIVO -> SALIENTE_MUERTO) is rc 3, intact."""
        roster = _sweep_mut(
            lambda r: r["active_roles"]["orquestador"].__setitem__("estado", "ACTIVO")
        )
        flags = ["--role", "orquestador", "--estado", "SALIENTE_MUERTO"]
        rc, intact = _sweep_cli(tmp_path, roster, flags)
        assert rc == 3 and intact

    @pytest.mark.parametrize("raw_name", sorted(_SWEEP_RAW_FILES))
    def test_m_role_mode_unreadable_file_cells(self, tmp_path, raw_name):
        """M: unreadable / non-mapping roster file fails closed in role mode."""
        rc, intact = _sweep_cli(
            tmp_path, None, _SWEEP_ROLE_OK, raw=_SWEEP_RAW_FILES[raw_name]
        )
        assert rc == 3 and intact
