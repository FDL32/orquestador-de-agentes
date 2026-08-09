"""Tests for scripts/backlog_reconcile.py (Fase-0 signal collector, NOT a judge).

WOT-2026-021i. Covers: parse of the ## Vista rapida table (reconcile set =
pending/deferred/completed-partial), per-scope repo routing (motor/* -> motor,
destinos/* -> destino, system|infra/* -> n/a), the 3 raw signal families + the
repo-level last-run block, the "no verdict field" boundary, relativization (PII),
exit codes, read-only-ness, and topology resolution via motor_destination_link.json.
Mirrors test_collect_system_health.py conventions (importlib load, monkeypatched
_run, tmp_path fixtures, NO real git).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path


_SPEC = importlib.util.spec_from_file_location(
    "backlog_reconcile",
    Path(__file__).resolve().parents[2] / "scripts" / "backlog_reconcile.py",
)
br = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(br)


MOTOR_SHA = "a" * 40
DEST_SHA = "b" * 40


# ---- Fixture backlog + workspace --------------------------------------------

_BACKLOG = """# Backlog (cola viva)

## Vista rapida

| Prioridad | Ticket | Titulo | Scope | Estado | Depende de | Origen | Reactivation |
|-----------|--------|--------|-------|--------|------------|--------|--------------|
| Baja | WOT-2026-900a | fix agent_controller.py:10 skip_gates behaviour | motor/skip-gates | pending | - | s | - |
| Baja | WOT-2026-900b | flatten destino legacy `some_marker` | destinos/flatten | pending | - | s | - |
| Baja | WOT-2026-900c | espanso launcher tweak | infra/espanso | pending | - | s | - |
| Baja | WOT-2026-900d | host extends copies | system/host | completed-partial | - | s | condition:x |
| Baja | WOT-2026-900e | already closed thing | motor/done | ready-for-review | - | s | - |
| Baja | WT-2026-900f | blocked upstream | system/sec | blocked | - | s | condition:y |
| Baja | WOT-2026-900g | blocked by an archived ticket | motor/x | blocked | WOT-2026-777z | s | - |
| Baja | WOT-2026-900h | pending with archived blocker | motor/y | pending | WOT-2026-777z | s | - |

## Fichas detalladas (tickets vivos)

### WOT-2026-900a - skip gates
- **Scope:** motor/skip-gates
- extra evidence: run_pytest_safe.py:704 and `SKIP_GATES_TOKEN`
"""


def _fake_workspace(tmp_path, *, with_link=False, dest_root_for_link=None):
    """Build a fake destino workspace with a backlog + optional link + last-run."""
    ws = tmp_path / "ws"
    (ws / ".agent" / "collaboration").mkdir(parents=True)
    (ws / ".agent" / "collaboration" / "backlog.md").write_text(
        _BACKLOG, encoding="utf-8"
    )
    psafe = ws / ".agent" / "runtime" / "pytest-safe"
    psafe.mkdir(parents=True)
    (psafe / "last-run.json").write_text(
        json.dumps({"exit_code": 0, "tested_commit_sha": DEST_SHA}), encoding="utf-8"
    )
    if with_link:
        cfg = ws / ".agent" / "config"
        cfg.mkdir(parents=True)
        target = str(dest_root_for_link if dest_root_for_link is not None else ws)
        (cfg / "motor_destination_link.json").write_text(
            json.dumps({"destination_root": target}), encoding="utf-8"
        )
    return ws


def _fake_motor(tmp_path):
    motor = tmp_path / "motor"
    motor.mkdir()
    (motor / "MANIFEST.distribute").write_text("AGENTS.md\n", encoding="utf-8")
    psafe = motor / ".agent" / "runtime" / "pytest-safe"
    psafe.mkdir(parents=True)
    (psafe / "last-run.json").write_text(
        json.dumps({"exit_code": 0, "tested_commit_sha": MOTOR_SHA}), encoding="utf-8"
    )
    return motor


def _fake_run_factory(motor: Path, dest: Path):
    """A _run fake that routes git output by cwd (motor vs dest) and command.

    rev-parse -> distinct SHA per repo; git grep -> a hit ONLY in the motor repo
    (so a motor-scoped ticket routed to the workspace would show 0 hits -> the
    routing test has teeth); ls-files -> tracked only in the motor.
    """
    motor_s = str(motor)

    def _fake(cmd, cwd, timeout=120):
        joined = " ".join(str(c) for c in cmd)
        is_motor = str(cwd) == motor_s
        if "rev-parse" in joined:
            sha = MOTOR_SHA if is_motor else DEST_SHA
            return {
                "cmd": cmd,
                "exit_code": 0,
                "stdout": sha + "\n",
                "stderr": "",
                "ok": True,
            }
        if "log" in joined and "--grep" in joined:
            # A commit mentioning the ticket exists only in the motor.
            if is_motor:
                out = "deadbeefcafe\x1fWOT-2026-900a done\x1f2026-07-10\n"
                return {
                    "cmd": cmd,
                    "exit_code": 0,
                    "stdout": out,
                    "stderr": "",
                    "ok": True,
                }
            return {"cmd": cmd, "exit_code": 1, "stdout": "", "stderr": "", "ok": False}
        if "ls-files" in joined:
            if is_motor:
                return {
                    "cmd": cmd,
                    "exit_code": 0,
                    "stdout": "scripts/x.py\n",
                    "stderr": "",
                    "ok": True,
                }
            return {"cmd": cmd, "exit_code": 0, "stdout": "", "stderr": "", "ok": True}
        if "grep" in joined:
            # Case-insensitive hit exists only in the motor (guards -i + routing).
            if is_motor:
                return {
                    "cmd": cmd,
                    "exit_code": 0,
                    "stdout": "scripts/x.py:1:SKIP_GATES_TOKEN\n",
                    "stderr": "",
                    "ok": True,
                }
            return {"cmd": cmd, "exit_code": 1, "stdout": "", "stderr": "", "ok": False}
        if "status" in joined:
            return {"cmd": cmd, "exit_code": 0, "stdout": "", "stderr": "", "ok": True}
        return {"cmd": cmd, "exit_code": 0, "stdout": "", "stderr": "", "ok": True}

    return _fake


def _run_main(tmp_path, monkeypatch, *, project_root=True, out=None):
    motor = _fake_motor(tmp_path)
    ws = _fake_workspace(tmp_path)
    monkeypatch.setattr(br, "_run", _fake_run_factory(motor, ws))
    out_dir = out or (tmp_path / "out")
    argv = ["--motor-root", str(motor), "--out", str(out_dir)]
    if project_root:
        argv += ["--project-root", str(ws)]
    rc = br.main(argv)
    findings = None
    fp = out_dir / "findings.json"
    if fp.exists():
        findings = json.loads(fp.read_text(encoding="utf-8"))
    return rc, findings, motor, ws, out_dir


# ---- Pure helpers -----------------------------------------------------------


def test_extract_vista_rapida_rows_only_table():
    rows, err = br._extract_vista_rapida_rows(_BACKLOG)
    assert err is None
    ids = [r[br._COL_TICKET] for r in rows]
    assert "WOT-2026-900a" in ids
    # Stops at the '## Fichas' header -> the ficha ### line is NOT a row.
    assert all(not r[0].startswith("###") for r in rows)


def test_scope_repo_routing():
    motor, dest = Path("/m"), Path("/d")
    assert br._scope_repo("motor/x", motor, dest) == ("motor", motor)
    assert br._scope_repo("destinos/x", motor, dest) == ("destino", dest)
    assert br._scope_repo("infra/x", motor, dest) == ("n/a", None)
    assert br._scope_repo("system/x", motor, dest) == ("n/a", None)


def test_harvest_terms_excludes_id_and_tokenizes_scope():
    terms = br._harvest_terms(
        "WOT-2026-900a",
        "motor/skip-gates",
        "fix run_pytest_safe.py:704",
        "`SKIP_TOKEN`",
    )
    assert "WOT-2026-900a" not in terms
    # Scope tokens >=5 chars are kept; short/generic ones (skip, motor) are dropped.
    assert "gates" in terms
    assert "skip" not in terms and "motor" not in terms
    # File paths + backticked idents from titulo/ficha are kept regardless of length.
    assert "run_pytest_safe.py:704" in terms
    assert "SKIP_TOKEN" in terms


def test_unreadable_backlog_exits_1(tmp_path, monkeypatch):
    """DoD-h: a resolvable destino whose backlog is unparseable -> collector self-failure
    exit 1 (never a ticket-level critical)."""
    motor = _fake_motor(tmp_path)
    dest = tmp_path / "dest"
    (dest / ".agent" / "collaboration").mkdir(parents=True)
    # backlog exists but has no '## Vista rapida' table -> unparseable
    (dest / ".agent" / "collaboration" / "backlog.md").write_text(
        "# empty\n", encoding="utf-8"
    )
    monkeypatch.setattr(br, "_run", _fake_run_factory(motor, dest))
    rc = br.main(
        [
            "--motor-root",
            str(motor),
            "--project-root",
            str(dest),
            "--out",
            str(tmp_path / "o"),
        ]
    )
    assert rc == 1


# ---- main() integration -----------------------------------------------------


def test_reconcile_set_is_pending_deferred_completedpartial(tmp_path, monkeypatch):
    """DoD-b: only pending/deferred/completed-partial; excludes blocked/terminal/ficha."""
    _rc, findings, _m, _w, _o = _run_main(tmp_path, monkeypatch)
    ids = {t["ticket_id"] for t in findings["tickets"]}
    assert ids == {
        "WOT-2026-900a",
        "WOT-2026-900b",
        "WOT-2026-900c",
        "WOT-2026-900d",
        "WOT-2026-900h",
    }
    assert "WOT-2026-900e" not in ids  # ready-for-review
    assert "WT-2026-900f" not in ids  # blocked


def test_output_shape_and_note(tmp_path, monkeypatch):
    """DoD-a: findings has the required keys + the exact [RELATO] note + schema."""
    rc, findings, _m, _w, _o = _run_main(tmp_path, monkeypatch)
    assert rc == 0
    assert findings["schema"] == "backlog-reconcile-collector/v0"
    for k in (
        "generated_at",
        "tickets",
        "repos_last_run",
        "automatic_warnings",
        "automatic_criticals",
    ):
        assert k in findings
    assert (
        findings["note"]
        == "Collector output is [RELATO]; the agent produces the verdict (Fase 0)."
    )


def test_routing_motor_ticket_uses_motor_repo(tmp_path, monkeypatch):
    """DoD-c (BLOCKER 1): a motor/* ticket runs signals against the MOTOR.

    The fake yields a commit/grep hit ONLY in the motor; if the ticket were routed
    to the workspace it would show 0 -> this asserts real routing.
    """
    _rc, findings, _m, _w, _o = _run_main(tmp_path, monkeypatch)
    a = next(t for t in findings["tickets"] if t["ticket_id"] == "WOT-2026-900a")
    assert a["repo"] == "motor"
    assert len(a["grep_commits"]) == 1  # visible only in motor
    assert any(d["hits"] > 0 for d in a["dod_terms"])  # -i hit only in motor


def test_routing_infra_ticket_is_na_with_warning(tmp_path, monkeypatch):
    """DoD-c: system/infra scope -> repo n/a, no forced grep, a warning is emitted."""
    _rc, findings, _m, _w, _o = _run_main(tmp_path, monkeypatch)
    c = next(t for t in findings["tickets"] if t["ticket_id"] == "WOT-2026-900c")
    assert c["repo"] == "n/a"
    assert c["grep_commits"] == [] and c["scope_paths"] == [] and c["dod_terms"] == []
    assert any("WOT-2026-900c" in w for w in findings["automatic_warnings"])


def test_no_verdict_field_anywhere(tmp_path, monkeypatch):
    """DoD-d (NON-GOAL, hard): no judgment/classification field exists in the output."""
    _rc, findings, _m, _w, _o = _run_main(tmp_path, monkeypatch)
    for t in findings["tickets"]:
        for forbidden in (
            "reconciliation",
            "classification",
            "evidence_label",
            "likely",
            "verdict",
        ):
            assert not any(forbidden in k.lower() for k in t)


def test_last_run_is_repo_level_not_per_ticket(tmp_path, monkeypatch):
    """DoD-e (BLOCKER 2): repos_last_run has motor+destino; no ticket carries last_run."""
    _rc, findings, _m, _w, _o = _run_main(tmp_path, monkeypatch)
    assert set(findings["repos_last_run"]) == {"motor", "destino"}
    assert findings["repos_last_run"]["motor"]["tested_commit_sha"] == MOTOR_SHA
    assert findings["repos_last_run"]["destino"]["tested_commit_sha"] == DEST_SHA
    # motor last-run sha == motor HEAD -> not stale; both are self-consistent here.
    assert findings["repos_last_run"]["motor"]["stale"] is False
    assert all("last_run" not in t for t in findings["tickets"])


def test_grep_uses_dash_i(tmp_path, monkeypatch):
    """DoD-f: the grep command carries -i (case-insensitive). Guards the 021d regression."""
    calls = []
    motor = _fake_motor(tmp_path)
    ws = _fake_workspace(tmp_path)
    inner = _fake_run_factory(motor, ws)

    def _spy(cmd, cwd, timeout=120):
        calls.append([str(c) for c in cmd])
        return inner(cmd, cwd, timeout)

    monkeypatch.setattr(br, "_run", _spy)
    br.main(
        [
            "--motor-root",
            str(motor),
            "--project-root",
            str(ws),
            "--out",
            str(tmp_path / "o"),
        ]
    )
    grep_calls = [c for c in calls if "grep" in c and "-n" in c]
    assert grep_calls, "expected at least one git grep call"
    assert all("-i" in c for c in grep_calls)


def test_git_log_uses_all_flag(tmp_path, monkeypatch):
    """DoD-k: git log uses --all (survives detached-HEAD/worktree topology)."""
    calls = []
    motor = _fake_motor(tmp_path)
    ws = _fake_workspace(tmp_path)
    inner = _fake_run_factory(motor, ws)

    def _spy(cmd, cwd, timeout=120):
        calls.append([str(c) for c in cmd])
        return inner(cmd, cwd, timeout)

    monkeypatch.setattr(br, "_run", _spy)
    br.main(
        [
            "--motor-root",
            str(motor),
            "--project-root",
            str(ws),
            "--out",
            str(tmp_path / "o"),
        ]
    )
    log_calls = [c for c in calls if "log" in c and any("--grep" in x for x in c)]
    assert log_calls
    assert all("--all" in c for c in log_calls)


def test_relativization_no_pii(tmp_path, monkeypatch):
    """DoD-g: no absolute personal root survives in the written findings JSON."""
    _rc, _f, motor, ws, out_dir = _run_main(tmp_path, monkeypatch)
    raw = (out_dir / "findings.json").read_text(encoding="utf-8")
    assert str(motor) not in raw
    assert str(ws) not in raw
    assert "<MOTOR_ROOT>" in raw and "<DESTINO_ROOT>" in raw


def test_grep_lines_never_reach_findings(tmp_path, monkeypatch):
    """PII barrier: git-grep matched LINES (third-party content that embeds absolute
    paths) go to the gitignored raw/ sink, NEVER into the versioned findings JSON.

    This is the vector the real run surfaced (a grep hit line carried 'C:/Users').
    The findings must carry only the hit COUNT; the raw dump lives under raw/.
    """
    motor = _fake_motor(tmp_path)
    ws = _fake_workspace(tmp_path)

    def _leaky_run(cmd, cwd, timeout=120):
        joined = " ".join(str(c) for c in cmd)
        if "grep" in joined and "-n" in joined:
            # a matched line embedding a personal absolute path (outside the roots)
            return {
                "cmd": cmd,
                "exit_code": 0,
                "stdout": "docs/x.md:1:see C:/Users/someone/other/repo/z.py\n",
                "stderr": "",
                "ok": True,
            }
        if "rev-parse" in joined:
            return {
                "cmd": cmd,
                "exit_code": 0,
                "stdout": MOTOR_SHA + "\n",
                "stderr": "",
                "ok": True,
            }
        return {"cmd": cmd, "exit_code": 0, "stdout": "", "stderr": "", "ok": True}

    monkeypatch.setattr(br, "_run", _leaky_run)
    out_dir = tmp_path / "o"
    br.main(
        ["--motor-root", str(motor), "--project-root", str(ws), "--out", str(out_dir)]
    )
    findings_text = (out_dir / "findings.json").read_text(encoding="utf-8")
    assert (
        "C:/Users/someone" not in findings_text
    )  # the leaky line never reaches findings
    findings = json.loads(findings_text)
    for t in findings["tickets"]:
        for d in t["dod_terms"]:
            assert "lines" not in d  # only {term, hits}
    # The full lines DO land in the gitignored raw/ sink.
    raw = out_dir / "raw" / "grep_hits.txt"
    assert raw.exists() and "someone" in raw.read_text(encoding="utf-8")


def test_bad_motor_root_exits_2(tmp_path):
    notmotor = tmp_path / "x"
    notmotor.mkdir()
    rc = br.main(
        [
            "--motor-root",
            str(notmotor),
            "--project-root",
            str(tmp_path),
            "--out",
            str(tmp_path / "o"),
        ]
    )
    assert rc == 2


def test_unresolved_backlog_link_exits_3(tmp_path, monkeypatch):
    """DoD-h/j: no --project-root and no resolvable link -> degrade with exit 3."""
    motor = _fake_motor(tmp_path)
    monkeypatch.setattr(br, "_run", _fake_run_factory(motor, tmp_path / "ws"))
    # neither --project-root nor --workspace-root -> unresolved
    rc = br.main(["--motor-root", str(motor), "--out", str(tmp_path / "o")])
    assert rc == 3


def test_topology_resolves_via_link(tmp_path, monkeypatch):
    """DoD-j: with only --workspace-root, resolve destination_root from the link."""
    motor = _fake_motor(tmp_path)
    ws = _fake_workspace(tmp_path, with_link=True)  # link -> ws itself
    monkeypatch.setattr(br, "_run", _fake_run_factory(motor, ws))
    rc = br.main(
        [
            "--motor-root",
            str(motor),
            "--workspace-root",
            str(ws),
            "--out",
            str(tmp_path / "o"),
        ]
    )
    assert rc == 0
    findings = json.loads(
        (tmp_path / "o" / "findings.json").read_text(encoding="utf-8")
    )
    assert findings["tickets"]  # resolved the backlog and parsed it


def test_read_only_backlog_unchanged(tmp_path, monkeypatch):
    """DoD-i: the backlog file is byte-identical before vs after a run."""
    motor = _fake_motor(tmp_path)
    ws = _fake_workspace(tmp_path)
    backlog = ws / ".agent" / "collaboration" / "backlog.md"
    before = hashlib.md5(backlog.read_bytes()).hexdigest()  # noqa: S324 - integrity, not security
    monkeypatch.setattr(br, "_run", _fake_run_factory(motor, ws))
    br.main(
        [
            "--motor-root",
            str(motor),
            "--project-root",
            str(ws),
            "--out",
            str(tmp_path / "o"),
        ]
    )
    after = hashlib.md5(backlog.read_bytes()).hexdigest()  # noqa: S324
    assert after == before


def test_out_dir_is_immutable(tmp_path, monkeypatch):
    """The output dir never overwrites an existing one (mirrors collect)."""
    _rc, _f, _m, _w, out_dir = _run_main(tmp_path, monkeypatch, out=tmp_path / "fixed")
    assert out_dir.exists()
    # A second run against the same base appends _NN rather than overwriting.
    second = br._unique_out_dir(tmp_path / "fixed")
    assert second != (tmp_path / "fixed")


# --------------------------------------------------------------------------- #
# WOT-2026-041f: divergence cross-checks -- (e) DEC accepted vs live row,
# (f) blocked row whose blocker is not in the live queue.
#
# Fixtures are SYNTHETIC on purpose. Pinning a live case (e.g. today's 021f /
# 027a) would make the test decay the day that ticket is archived: it would then
# assert against a row that no longer exists, and the failure would look like a
# code regression instead of the calendar moving. Live cases belong in a report
# as a DATED snapshot, never as a test oracle (WOT-2026-024t: criterio
# invariante, evidencia fechada).
# --------------------------------------------------------------------------- #


def _dec(ws, name: str, body: str) -> Path:
    dec_dir = ws / "orchestrator_pipeline" / "decisions"
    dec_dir.mkdir(parents=True, exist_ok=True)
    path = dec_dir / name
    path.write_text(body, encoding="utf-8")
    return path


def test_041f_cross_e_dec_accepted_while_ticket_live(tmp_path):
    """A DEC marking the ticket accepted while its row is LIVE -> divergence."""
    ws = tmp_path / "ws"
    _dec(
        ws,
        "DEC-900a.md",
        "# DEC\n\nDecision sobre WOT-2026-900a: ACCEPTED por el usuario.\n",
    )
    hits = br._signal_dec_accepted("WOT-2026-900a", ws)
    assert len(hits) == 1
    assert hits[0]["line"] == 3
    assert "WOT-2026-900a" in hits[0]["text"]


def test_041f_cross_e_requires_both_id_and_marker_on_same_line(tmp_path):
    """ANTI-FALSE-POSITIVE: the ID alone, or 'accepted' alone, is NOT a signal."""
    ws = tmp_path / "ws"
    _dec(
        ws,
        "DEC-x.md",
        "Se menciona WOT-2026-900a sin veredicto.\nOtra cosa fue accepted.\n",
    )
    assert br._signal_dec_accepted("WOT-2026-900a", ws) == []
    # And a ticket absent from every DEC yields nothing.
    assert br._signal_dec_accepted("WOT-2026-999z", ws) == []


def test_041f_cross_e_missing_dec_dir_is_silent(tmp_path):
    """No DEC tree at all -> empty signal, never an exception (fail-safe)."""
    assert br._signal_dec_accepted("WOT-2026-900a", tmp_path / "nope") == []


def test_041f_cross_f_offqueue_blocker_is_reported(tmp_path):
    """A blocker absent from the live queue is surfaced with its ID."""
    live = frozenset({"WOT-2026-900a", "WOT-2026-900b"})
    out = br._signal_blocker_offqueue("WOT-2026-777z", live)
    assert out == [{"blocker": "WOT-2026-777z", "present_in_live_queue": False}]


def test_041f_cross_f_multi_blocker_cell_splits(tmp_path):
    """A cell may carry several blockers; each is checked independently."""
    live = frozenset({"WOT-2026-900a"})
    out = br._signal_blocker_offqueue("WOT-2026-900a, WOT-2026-888y", live)
    assert [o["blocker"] for o in out] == ["WOT-2026-888y"]


def test_041f_cross_f_no_blocker_is_not_a_divergence(tmp_path):
    """ANTI-FALSE-POSITIVE: '-' / empty means no blocker declared, not a defect."""
    live = frozenset({"WOT-2026-900a"})
    assert br._signal_blocker_offqueue("-", live) == []
    assert br._signal_blocker_offqueue("", live) == []
    # A blocker that IS live is likewise silent.
    assert br._signal_blocker_offqueue("WOT-2026-900a", live) == []


def test_041f_divergences_reach_findings_and_carry_no_verdict(tmp_path, monkeypatch):
    """End-to-end: divergences land in findings.json as SIGNAL, never a verdict.

    The authority contract (`This script NEVER classifies`) is the load-bearing
    clause of WOT-2026-041f: a divergence must not smuggle in a classification.
    """
    motor = _fake_motor(tmp_path)
    ws = _fake_workspace(tmp_path)
    _dec(ws, "DEC-900a.md", "WOT-2026-900a quedo accepted en el consejo.\n")
    monkeypatch.setattr(br, "_run", _fake_run_factory(motor, ws))
    out_dir = tmp_path / "out"
    rc = br.main(
        ["--motor-root", str(motor), "--project-root", str(ws), "--out", str(out_dir)]
    )
    assert rc == 0
    findings = json.loads((out_dir / "findings.json").read_text(encoding="utf-8"))

    kinds = {d["kind"] for d in findings["divergences"]}
    assert "dec_accepted_but_ticket_live" in kinds

    blob = json.dumps(findings["divergences"])
    for verdict in ("LIKELY_DONE", "LIKELY_PENDING", "NEEDS_HUMAN_VERIFY"):
        assert verdict not in blob, (
            f"the collector emitted the verdict {verdict}; it must only emit "
            "evidence -- the AGENT classifies (backlog_reconcile.py docstring)"
        )
    for d in findings["divergences"]:
        assert d["note"], "every divergence must carry its 'signal, not verdict' note"


def test_041f_cross_f_reaches_findings_through_collect_all(tmp_path, monkeypatch):
    """MUTATION-VERIFY of the INTEGRATION POINT, not just the pure helper.

    Regression pin for a surviving mutant found by an adversarial lens: replacing
    ``if status == _BLOCKED_STATE:`` in ``_collect_all`` with ``if False:`` left
    the whole suite green (26/26), because every cross-(f) test called
    ``_signal_blocker_offqueue`` directly. A helper with teeth wired to nothing
    is not a barrier -- the wiring needs its own test.

    The fixture row ``WOT-2026-900g`` is ``blocked`` on ``WOT-2026-777z``, which
    is absent from the live table; ``WT-2026-900f`` is ``blocked`` with ``-`` and
    must stay silent (anti-false-positive on the same path).
    """
    motor = _fake_motor(tmp_path)
    ws = _fake_workspace(tmp_path)
    monkeypatch.setattr(br, "_run", _fake_run_factory(motor, ws))
    out_dir = tmp_path / "out"
    rc = br.main(
        ["--motor-root", str(motor), "--project-root", str(ws), "--out", str(out_dir)]
    )
    assert rc == 0
    findings = json.loads((out_dir / "findings.json").read_text(encoding="utf-8"))

    offqueue = [
        d
        for d in findings["divergences"]
        if d["kind"] == "blocked_with_offqueue_blocker"
    ]
    assert len(offqueue) == 2, (
        "the blocked row AND the pending row with off-queue blockers must reach "
        f"findings.json through _collect_all; got {offqueue}"
    )
    assert offqueue[0]["ticket_id"] == "WOT-2026-900g"
    assert [b["blocker"] for b in offqueue[0]["blockers"]] == ["WOT-2026-777z"]
    assert offqueue[1]["ticket_id"] == "WOT-2026-900h"
    assert [b["blocker"] for b in offqueue[1]["blockers"]] == ["WOT-2026-777z"]
    # The '-' blocked row never becomes a divergence (no blocker declared).
    assert all(d["ticket_id"] != "WT-2026-900f" for d in findings["divergences"])


def test_046g_pending_row_with_archived_blocker_is_divergence(tmp_path, monkeypatch):
    """WOT-2026-046g: pending rows with archived blockers are flagged.

    The fixture row WOT-2026-900h is 'pending' with dependency on WOT-2026-777z,
    which is absent from the live table. Before WOT-2026-046g, only 'blocked'
    rows were checked; now pending/CP rows with dependencies are also checked.
    """
    motor = _fake_motor(tmp_path)
    ws = _fake_workspace(tmp_path)
    monkeypatch.setattr(br, "_run", _fake_run_factory(motor, ws))
    out_dir = tmp_path / "out"
    rc = br.main(
        ["--motor-root", str(motor), "--project-root", str(ws), "--out", str(out_dir)]
    )
    assert rc == 0
    findings = json.loads((out_dir / "findings.json").read_text(encoding="utf-8"))

    offqueue = [
        d
        for d in findings["divergences"]
        if d["kind"] == "blocked_with_offqueue_blocker"
    ]
    ticket_ids = [d["ticket_id"] for d in offqueue]
    # WOT-2026-900h (pending with archived blocker) must appear
    assert "WOT-2026-900h" in ticket_ids, (
        "pending row with archived blocker must be flagged as divergence; "
        f"got divergences: {offqueue}"
    )
    # WOT-2026-900g (blocked with archived blocker) must still appear
    assert "WOT-2026-900g" in ticket_ids
    # The pending row with '-' must NOT appear
    assert all(d["ticket_id"] != "WOT-2026-900a" for d in findings["divergences"])


def test_046i_coverage_block_present(tmp_path, monkeypatch):
    """WOT-2026-046i: findings.json includes a coverage block.

    The consumer can distinguish 'zero divergences' from 'zero coverage'
    without reading the prompt.
    """
    motor = _fake_motor(tmp_path)
    ws = _fake_workspace(tmp_path)
    monkeypatch.setattr(br, "_run", _fake_run_factory(motor, ws))
    out_dir = tmp_path / "out"
    rc = br.main(
        ["--motor-root", str(motor), "--project-root", str(ws), "--out", str(out_dir)]
    )
    assert rc == 0
    findings = json.loads((out_dir / "findings.json").read_text(encoding="utf-8"))

    assert "coverage" in findings, "coverage block must be present in findings.json"
    cov = findings["coverage"]
    assert "states_checked" in cov
    assert "total_rows" in cov
    assert "reconcile_rows" in cov
    assert "blocked_rows" in cov
    assert "divergence_kinds" in cov
    assert "limitation" in cov
    # The fixture has 5 pending/CP rows + 1 blocked + 1 ready-for-review
    assert cov["total_rows"] >= 5
    assert cov["reconcile_rows"] >= 4  # pending + completed-partial
    assert cov["blocked_rows"] >= 1


def test_046g_pending_row_with_live_blocker_not_flagged(tmp_path, monkeypatch):
    """ANTI-FALSE-POSITIVE: pending row whose blocker IS live must not be flagged."""
    motor = _fake_motor(tmp_path)
    ws = _fake_workspace(tmp_path)
    # Add a pending row whose blocker IS in the live queue
    backlog = (ws / ".agent" / "collaboration" / "backlog.md").read_text(
        encoding="utf-8"
    )
    backlog += "| Baja | WOT-2026-900i | pending with live blocker | motor/z | pending | WOT-2026-900a | s | - |\n"
    (ws / ".agent" / "collaboration" / "backlog.md").write_text(
        backlog, encoding="utf-8"
    )
    monkeypatch.setattr(br, "_run", _fake_run_factory(motor, ws))
    out_dir = tmp_path / "out"
    rc = br.main(
        ["--motor-root", str(motor), "--project-root", str(ws), "--out", str(out_dir)]
    )
    assert rc == 0
    findings = json.loads((out_dir / "findings.json").read_text(encoding="utf-8"))
    # WOT-2026-900i must NOT appear in divergences (blocker is live)
    assert all(d["ticket_id"] != "WOT-2026-900i" for d in findings["divergences"])
