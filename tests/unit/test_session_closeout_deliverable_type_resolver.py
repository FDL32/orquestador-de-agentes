"""Barrier tests for `_resolve_deliverable_type_for_ticket` (session_closeout).

Defect reproduced (cierre del vuelo WOT-2026-120a, 2026-10-23): the resolver
returned the `deliverable_type` of the FIRST backlog line that CONTAINED the id
as a substring, live backlog before archive. The live rows of 120b (`mixed`) and
120c (`code`) cite "WOT-2026-120a" in prose, so they won over the real archived
row of 120a (`documentation`), the targets file was stamped `mixed` and the
Loop Execution Barrier demanded 4 lenses instead of 2.

Contract now pinned:
  (a) a mention in the row of ANOTHER ticket never decides the type;
  (b) among the ticket's OWN rows, live wins over archive;
  (c) the id is matched against the raw ID cell, cell 1 or cell 2 (both real
      table layouts of the destino);
  (d) a token is cleaned of trailing punctuation/quotes before matching;
  (e) several valid tokens in the own row -> the strictest one (074e: prose
      `documentation` + Metadata `code,` -> `code`, fail-closed);
  (f) cleaning never promotes a type: `documentation` + `documentation,`
      stays `documentation` (104p);
  (g) no own row, or an own row with only invalid tokens -> `code` fallback.

Row texts are excerpts of REAL rows of the destino backlog (2026-10-23), cut
around their `deliverable_type:` cells. Each test is mutation-verified (see
its docstring).
"""

from __future__ import annotations

import sys
from pathlib import Path


_MOTOR_ROOT = Path(__file__).resolve().parents[2]
if str(_MOTOR_ROOT) not in sys.path:
    sys.path.insert(0, str(_MOTOR_ROOT))

from scripts import session_closeout  # noqa: E402
from scripts.session_closeout import BACKLOG_ARCHIVE_REL, BACKLOG_REL  # noqa: E402


_HEADER = "| Prioridad | ID | Titulo | Estado | Reactivation |\n|---|---|---|---|---|\n"

# Real excerpts (destino backlog.md / _archive/backlog_done.md, 2026-10-23).
ROW_120B_LIVE = (
    "| Media | WOT-2026-120b | ARTEFACTO OPERATIVO AJENO EN `orchestrator_pipeline/"
    "arranques/` BLOQUEA EL `--session-close` DE CUALQUIER SESION DEL WORKSPACE. "
    "Medido en el cierre de WOT-2026-120a 2026-10-23 (prepush closeout FAIL 054g). "
    "Origen-confirmado: hallazgo. deliverable_type: mixed, delivery_authority: "
    "repo_destino | pending | - |"
)
ROW_120C_LIVE = (
    "| Media | WOT-2026-120c | FRICCIONES DE HERRAMIENTA DE CIERRE MEDIDAS EN EL "
    "VUELO WOT-2026-120a (2026-10-23), registradas como [PROCESO-CIERRE] en el "
    "Bloque 2.5 del execution_log. Origen-confirmado: hallazgo. deliverable_type: "
    "code, delivery_authority: repo_motor | pending | - |"
)
ROW_120A_ARCHIVE = (
    "| Media | WOT-2026-120a | [CERRADO 2026-10-23: cierre canonico por bus en "
    "destino 849db65d] Ficha: `.agent/planning/FICHA_WOT-2026-120a_gates_contexto.md` "
    "deliverable_type: documentation, delivery_authority: repo_motor. | completed | "
    "commit:a830de56 |"
)
ROW_074E = (
    "| Media | WOT-2026-074e | `pre_handoff_guard._read_deliverable_type_from_content` "
    "con Metadata `code` + prosa ANTERIOR `deliverable_type: documentation` -> "
    "devuelve `documentation` (engano=True). R4 gates + el plan del propio ticket no "
    "debe contener literales deliverable_type: fuera de Metadata. deliverable_type: "
    "code, delivery_authority: repo_motor | completed | commit:0000000 |"
)
ROW_104P = (
    '| Baja | WOT-2026-104p | la ficha ya lo marcaba "opcional" y se mantiene el '
    "ticket dentro de `deliverable_type: documentation` sin anadir superficie de "
    "codigo nueva. No resuelve alta-concurrente real. deliverable_type: "
    "documentation, delivery_authority: repo_motor | completed | commit:0000000 |"
)
ROW_054H_BANANA_ONLY = (
    "| Media | WOT-2026-054h | la 4a mutacion del DoD de 048g: "
    "`deliverable_type: banana` en fila del baseline debe dar ROJO | pending | - |"
)


def _write(root: Path, live: list[str], archive: list[str]) -> Path:
    (root / BACKLOG_REL).parent.mkdir(parents=True, exist_ok=True)
    (root / BACKLOG_ARCHIVE_REL).parent.mkdir(parents=True, exist_ok=True)
    (root / BACKLOG_REL).write_text(_HEADER + "\n".join(live) + "\n", encoding="utf-8")
    (root / BACKLOG_ARCHIVE_REL).write_text(
        _HEADER + "\n".join(archive) + "\n", encoding="utf-8"
    )
    return root


def _resolve(root: Path, ticket_id: str) -> str:
    return session_closeout._resolve_deliverable_type_for_ticket(root, ticket_id)


def test_a_prose_mention_in_another_live_row_does_not_win(tmp_path: Path) -> None:
    """(a) The exact 120a case: live 120b/120c cite the id, the real row is archived.

    Mutation proof: matching the id as a substring of the whole line (the old
    `if ticket_id not in line`) returns `mixed` from 120b -> this test fails.
    """
    root = _write(tmp_path, [ROW_120B_LIVE, ROW_120C_LIVE], [ROW_120A_ARCHIVE])
    assert _resolve(root, "WOT-2026-120a") == "documentation"


def test_b_own_live_row_wins_over_own_archive_row(tmp_path: Path) -> None:
    """(b) Live before archive, but only among rows whose ID cell is the ticket.

    Mutation proof: reading the archive surface first returns `documentation`
    -> this test fails.
    """
    live_own = ROW_120A_ARCHIVE.replace(
        "deliverable_type: documentation", "deliverable_type: analysis"
    )
    root = _write(tmp_path, [ROW_120B_LIVE, live_own], [ROW_120A_ARCHIVE])
    assert _resolve(root, "WOT-2026-120a") == "analysis"


def test_c_id_in_first_cell_layout_is_an_own_row(tmp_path: Path) -> None:
    """(c) 186 archived rows use `| <ID> | ...` (ID in cell 1), not cell 2.

    Mutation proof: comparing only cell 2 finds no own row -> `code` fallback
    -> this test fails.
    """
    cell1 = "| WOT-2026-120a | Media | gates de contexto. deliverable_type: documentation | completed |"
    root = _write(tmp_path, [ROW_120B_LIVE], [cell1])
    assert _resolve(root, "WOT-2026-120a") == "documentation"


def test_c_bis_id_cell_must_match_exactly_not_as_prefix(tmp_path: Path) -> None:
    """(c) The ID cell is compared raw and whole: `WOT-2026-120ab` is not 120a.

    Mutation proof: `startswith` on the cell makes 120ab's `mixed` row count
    as own -> the result is `mixed` and this test fails.
    """
    other = "| Media | WOT-2026-120ab | otro ticket. deliverable_type: mixed | pending | - |"
    root = _write(tmp_path, [other], [ROW_120A_ARCHIVE])
    assert _resolve(root, "WOT-2026-120a") == "documentation"


def test_d_trailing_punctuation_is_cleaned_before_matching(tmp_path: Path) -> None:
    """(d) 103 real rows write `code,`; 19 write `documentation,`.

    Mutation proof: without cleaning, `documentation,` is not a known type ->
    no valid token -> `code` fallback -> this test fails.
    """
    root = _write(tmp_path, [], [ROW_120A_ARCHIVE])
    assert _resolve(root, "WOT-2026-120a") == "documentation"


def test_e_several_tokens_resolve_to_the_strictest(tmp_path: Path) -> None:
    """(e) 074e cites `documentation` in prose and declares `code,` in Metadata.

    Mutation proof: taking the FIRST valid token returns `documentation` (the
    least strict) -> this test fails.
    """
    root = _write(tmp_path, [], [ROW_074E])
    assert _resolve(root, "WOT-2026-074e") == "code"


def test_f_cleaning_never_promotes_the_type(tmp_path: Path) -> None:
    """(f) 104p: `documentation` backticked + `documentation,` -> `documentation`.

    Mutation proof: treating any unclean token as unknown-and-strict (fallback
    `code` per token) returns `code` -> this test fails.
    """
    root = _write(tmp_path, [], [ROW_104P])
    assert _resolve(root, "WOT-2026-104p") == "documentation"


def test_g_only_invalid_tokens_or_no_own_row_falls_back_to_code(tmp_path: Path) -> None:
    """(g) An own row with only `banana`, or only prose mentions -> `code`.

    Mutation proof: returning the raw first token yields `banana`; ignoring the
    own-row requirement yields `mixed` for 120a -> this test fails.
    """
    root = _write(tmp_path, [ROW_054H_BANANA_ONLY, ROW_120B_LIVE], [])
    assert _resolve(root, "WOT-2026-054h") == "code"
    assert _resolve(root, "WOT-2026-120a") == "code"
    assert _resolve(tmp_path / "missing", "WOT-2026-120a") == "code"
