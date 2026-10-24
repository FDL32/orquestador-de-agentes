#!/usr/bin/env python3
"""Tests for scripts/measure_recall_quality.py (WOT-2026-124e).

Hermetic: uses temporary fixture data, never the live archive or live git repo.
The recall function is injected (default = subprocess) except for one integration
test that uses the real subprocess.

Ronda 6 (WOT-2026-124e) changes:
- Unit = citation, not lesson.
- Recall cache by query text.
- Surface FALLO removes citation from surface denominator.
- Fase: all-phase-FALLO removes from fase denominator; at least one HIT -> HIT.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


# Ensure motor root is on sys.path for imports.
MOTOR_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(MOTOR_ROOT))

from scripts.measure_recall_quality import (  # noqa: E402
    _CITE_PATTERN,
    _GIT_GREP_PATHS,
    _build_queries_for_citations,
    _derive_fase_queries,
    _derive_surface_query,
    _extract_markdown_section,
    _filter_excluded_citations,
    _generate_report,
    _git_grep_cites,
    _intersect_with_pool,
    _is_hit,
    _measure_hits,
    _recall_run,
)


# Module-level reference to subprocess.run for restoring mocks.
_original_subprocess_run = subprocess.run


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_fake_citation(
    filename: str, obs_id: str, line_num: int = 10
) -> tuple[str, str, int]:
    return (filename, obs_id, line_num)


def _make_fake_lesson(
    obs_id: str = "obs-test-lesson-1",
    topic: str = "testing",
    signal: str = "REGLA: no hagas cosas malas.",
    timestamp: str = "2026-10-01T00:00:00",
    status: str = "",
) -> dict:
    entry: dict = {
        "id": obs_id,
        "topic": topic,
        "signal": signal,
        "timestamp": timestamp,
    }
    if status:
        entry["status"] = status
    return entry


#: Controlled fake recall: hit for queries in _fake_hit_queries,
#: rc=1 for queries in _fake_rc_fail_queries, otherwise miss.
_fake_hit_queries: set[str] = set()
_fake_rc_fail_queries: set[str] = set()
_fake_recall_call_count: dict[str, int] = {}
#: The lesson ID that the recall should return as HIT.
_fake_hit_obs_id: str = "obs-test-lesson-1"


def _controlled_recall(
    motor_root: Path,
    query: str,
    destino_root: Path,
    limit: int,
) -> tuple[int, str, str]:
    """Controlled recall tracking call count for cache tests."""
    _fake_recall_call_count[query] = _fake_recall_call_count.get(query, 0) + 1
    if query in _fake_rc_fail_queries:
        return (1, "", "")
    if query in _fake_hit_queries:
        return (0, f"- {_fake_hit_obs_id}: test rule (test)\n", "")
    return (0, "", "")


def _hit_recall_for(citation_obs_id: str):
    """Return a recall function that hits the given citation obs_id for any query."""

    def _inner(motor_root, query, destino_root, limit):
        return (0, f"- {citation_obs_id}: test rule (test)\n", "")

    return _inner


# ---------------------------------------------------------------------------
# (i) Derivacion de query de SUPERFICIE: stem normal, stem useless, root excluded
# ---------------------------------------------------------------------------


class TestSurfaceQuery:
    """Tests for _derive_surface_query."""

    def test_normal_stem(self):
        """Normal stem returns the stem."""
        assert (
            _derive_surface_query("scripts/check_backlog_admission.py")
            == "check_backlog_admission"
        )

    def test_useless_stem_uses_parent(self):
        """Useless stem (AGENTS) falls back to parent dir name."""
        assert _derive_surface_query("docs/AGENTS.md") == "docs"

    def test_useless_stem_root_excluded(self):
        """If parent is root (empty name), the citation is excluded."""
        assert _derive_surface_query("AGENTS.md") is None

    def test_useless_stem_parent_also_useless(self):
        """If both stem and parent are in the useless list, excluded."""
        assert _derive_surface_query("CLAUDE.md") is None

    def test_useless_stem_valid_parent(self):
        """Useless stem with a valid parent directory returns parent."""
        assert _derive_surface_query("prompts/CLAUDE.md") == "prompts"

    def test_init_stem_uses_parent(self):
        """__init__ stem falls back to parent."""
        result = _derive_surface_query("bus/__init__.py")
        assert result == "bus"

    def test_conftest_stem_uses_parent(self):
        """conftest stem falls back to parent."""
        result = _derive_surface_query("tests/conftest.py")
        assert result == "tests"


# ---------------------------------------------------------------------------
# (ii) Derivacion de FASE: header with term, no term -> "sin seccion"
# ---------------------------------------------------------------------------


class TestFaseQuery:
    """Tests for _derive_fase_queries and section extraction."""

    def test_header_with_fase_term(self):
        """Section containing a fase term returns that term."""
        assert _derive_fase_queries("## Cierre de sesion") == ["cierre"]

    def test_header_with_multiple_fase_terms(self):
        """Section with multiple fase terms returns all of them."""
        terms = _derive_fase_queries("## Commit y suite del test")
        assert "commit" in terms
        assert "suite" in terms

    def test_header_no_fase_term(self):
        """Section without any fase term returns all 8 vocabulary terms."""
        terms = _derive_fase_queries("## Introduccion")
        assert len(terms) == 8
        assert set(terms) == set(
            [
                "commit",
                "suite",
                "push",
                "cierre",
                "encoding",
                "backlog",
                "bus",
                "memoria",
            ]
        )

    def test_python_file_no_section(self):
        """Non-markdown file returns empty string (no section)."""
        section = _extract_markdown_section(
            "scripts/check_guard_wiring.py", 100, MOTOR_ROOT
        )
        assert section == ""

    def test_section_extraction(self):
        """Can extract markdown heading from a file."""
        section = _extract_markdown_section("AGENTS.md", 2, MOTOR_ROOT)
        assert section == "AGENTS.md - Instrucciones transversales"


# ---------------------------------------------------------------------------
# (iii) Hit/miss with injected recall; rc != 0 = failure, not hit
# ---------------------------------------------------------------------------


class TestHitMiss:
    """Tests for _is_hit and end-to-end hit measurement."""

    def test_hit_with_id(self):
        """Lesson id appears at line start -> HIT."""
        result = _is_hit(
            rc=0,
            stdout="- obs-test-lesson-1: regla de prueba (test)",
            lesson_id="obs-test-lesson-1",
            lesson_topic="",
            lesson_signal="",
        )
        assert result is True

    def test_miss_id_not_in_output(self):
        """Lesson id not in output -> MISS."""
        result = _is_hit(
            rc=0,
            stdout="- obs-other-lesson: otra regla (test)",
            lesson_id="obs-test-lesson-1",
            lesson_topic="",
            lesson_signal="",
        )
        assert result is False

    def test_rc_not_zero_is_not_hit(self):
        """rc != 0 -> NOT a hit (it's a failure)."""
        result = _is_hit(
            rc=1,
            stdout="",
            lesson_id="obs-test-lesson-1",
            lesson_topic="",
            lesson_signal="",
        )
        assert result is False

    def test_rc_not_zero_is_not_miss_either(self):
        """rc != 0 is a failure state, not a miss. The caller handles it."""
        result = _is_hit(
            rc=127,
            stdout="command not found",
            lesson_id="obs-test-lesson-1",
            lesson_topic="",
            lesson_signal="",
        )
        assert result is False

    def test_empty_output_is_miss(self):
        """Empty stdout with rc=0 -> MISS."""
        result = _is_hit(
            rc=0,
            stdout="",
            lesson_id="obs-test-lesson-1",
            lesson_topic="",
            lesson_signal="",
        )
        assert result is False

    def test_no_id_lesson_match(self):
        """No-id lesson: topic and signal match."""
        result = _is_hit(
            rc=0,
            stdout="- testing: REGLA: no hagas cosas malas (test)",
            lesson_id="",
            lesson_topic="testing",
            lesson_signal="REGLA: no hagas cosas malas",
        )
        assert result is True

    def test_no_id_lesson_no_match(self):
        """No-id lesson: topic matches but signal doesn't -> MISS."""
        result = _is_hit(
            rc=0,
            stdout="- testing: otra senal diferente (test)",
            lesson_id="",
            lesson_topic="testing",
            lesson_signal="REGLA: no hagas cosas malas.",
        )
        assert result is False


# ---------------------------------------------------------------------------
# Ronda 6 tests: per-citation unit, cache, failure handling
# ---------------------------------------------------------------------------


class TestCitationUnitDenominator:
    """DoD c: unit = non-excluded citation.

    Two citations from the SAME lesson with different stems (one hits, one
    misses) plus a citation from another lesson -> surface denominator 3,
    hits 1; in the per-lesson table the first lesson is HIT.
    """

    def test_two_citations_same_lesson_different_stems(self):
        """2 citations from same lesson, 1 hit + 1 miss + 1 from another lesson."""
        global _fake_hit_queries, _fake_hit_obs_id
        _fake_hit_queries = {"check_backlog"}
        _fake_hit_obs_id = "obs-lesson-a"
        citations = [
            _make_fake_citation("scripts/check_backlog.py", "obs-lesson-a", 10),
            _make_fake_citation("scripts/ensemble_dispatch.py", "obs-lesson-a", 20),
            _make_fake_citation("scripts/test.py", "obs-lesson-b", 30),
        ]
        pool_by_id = {
            "obs-lesson-a": {"topic": "test", "signal": "signal"},
            "obs-lesson-b": {"topic": "test", "signal": "signal"},
        }

        queries = _build_queries_for_citations(citations, pool_by_id, MOTOR_ROOT)
        hits, denoms, _lesson_res, _failures, _cit_sum = _measure_hits(
            queries,
            citations,
            pool_by_id,
            MOTOR_ROOT,
            MOTOR_ROOT,
            5,
            _controlled_recall,
        )

        # Surface: 3 citations with surface query, 1 hit (check_backlog)
        assert denoms["superficie"] == 3
        assert hits["superficie"] == 1
        # Union: all 3 citations are in union (none excluded)
        assert denoms["union"] == 3
        assert hits["union"] == 1

    def test_per_lesson_aggregate_informative(self):
        """Per-lesson table: lesson-a is HIT (one of its citations hit)."""
        citations = [
            _make_fake_citation("scripts/check_backlog.py", "obs-lesson-a", 10),
            _make_fake_citation("scripts/ensemble_dispatch.py", "obs-lesson-a", 20),
            _make_fake_citation("scripts/test.py", "obs-lesson-b", 30),
        ]
        pool_by_id = {
            "obs-lesson-a": {"topic": "test", "signal": "signal"},
            "obs-lesson-b": {"topic": "test", "signal": "signal"},
        }

        queries = _build_queries_for_citations(citations, pool_by_id, MOTOR_ROOT)
        recall_fn = _hit_recall_for("obs-lesson-a")
        _hits, _denoms, lesson_res, _failures, _cs = _measure_hits(
            queries, citations, pool_by_id, MOTOR_ROOT, MOTOR_ROOT, 5, recall_fn
        )

        # lesson-a: one of its citations hit on surface -> HIT
        assert lesson_res["obs-lesson-a"]["superficie_hit"] is True
        # lesson-b: no citations hit
        assert lesson_res["obs-lesson-b"]["superficie_hit"] is False


class TestCache:
    """Cache: two citations with same stem -> recall_fn called ONCE for that query."""

    def test_same_stem_uses_cache(self):
        """Two citations in same file share surface query -> cached."""
        call_count: dict[str, int] = {}

        def _counted_recall(motor_root, query, destino_root, limit):
            call_count[query] = call_count.get(query, 0) + 1
            return (0, "- obs-cit-1: test rule (test)\n", "")

        citations = [
            _make_fake_citation("scripts/check_backlog.py", "obs-cit-1", 10),
            _make_fake_citation("scripts/check_backlog.py", "obs-cit-2", 20),
        ]
        pool_by_id = {
            "obs-cit-1": {"topic": "test", "signal": "signal"},
            "obs-cit-2": {"topic": "test", "signal": "signal"},
        }

        queries = _build_queries_for_citations(citations, pool_by_id, MOTOR_ROOT)
        _hits, _denoms, _lr, _failures, _cs = _measure_hits(
            queries, citations, pool_by_id, MOTOR_ROOT, MOTOR_ROOT, 5, _counted_recall
        )

        # The surface query "check_backlog" should have been called exactly once
        assert call_count.get("check_backlog", 0) == 1

    def test_different_stems_called_separately(self):
        """Two citations in different files -> separate calls for surface queries."""
        call_count: dict[str, int] = {}

        def _counted_recall(motor_root, query, destino_root, limit):
            call_count[query] = call_count.get(query, 0) + 1
            return (0, "- obs-cit-1: test rule (test)\n", "")

        citations = [
            _make_fake_citation("scripts/check_backlog.py", "obs-cit-1", 10),
            _make_fake_citation("scripts/ensemble_dispatch.py", "obs-cit-2", 20),
        ]
        pool_by_id = {
            "obs-cit-1": {"topic": "test", "signal": "signal"},
            "obs-cit-2": {"topic": "test", "signal": "signal"},
        }

        queries = _build_queries_for_citations(citations, pool_by_id, MOTOR_ROOT)
        _hits, _denoms, _lr, _failures, _cs = _measure_hits(
            queries, citations, pool_by_id, MOTOR_ROOT, MOTOR_ROOT, 5, _counted_recall
        )

        # "check_backlog" and "ensemble_dispatch" should each be called once
        assert call_count.get("check_backlog", 0) == 1
        assert call_count.get("ensemble_dispatch", 0) == 1


class TestSurfaceFailure:
    """A citation whose surface query is FALLO (rc 2) -> outside surface denominator,
    present in Fallos, still counts in phase if its phase queries are valid.
    """

    def test_surface_fallo_removes_from_surface_denominator(self):
        """Citation with surface FALLO -> not in surface denominator, in failures."""
        citations = [
            _make_fake_citation("scripts/check_backlog.py", "obs-fail-cit", 10),
            _make_fake_citation("scripts/test.py", "obs-ok-cit", 20),
        ]
        pool_by_id = {
            "obs-fail-cit": {"topic": "test", "signal": "signal"},
            "obs-ok-cit": {"topic": "test", "signal": "signal"},
        }

        queries = _build_queries_for_citations(citations, pool_by_id, MOTOR_ROOT)

        # "fail-cit" recall: always FALLO (rc 2)
        def _fail_recall(motor_root, query, destino_root, limit):
            return (2, "", "git error")

        # "ok-cit" recall: miss (rc 0, wrong obs_id)
        def _ok_recall(motor_root, query, destino_root, limit):
            return (0, "- obs-fake-cit: test rule (test)\n", "")

        # We need a recall that behaves differently per citation.
        # Since recall is called per query and both citations share surface queries...
        # Actually: fail-cit surface = "check_backlog", ok-cit surface = "test"
        # If "check_backlog" always FALLO and "test" always MISS, we get:
        # fail-cit: surface FALLO -> excluded from surface denom
        # ok-cit: surface MISS -> in surface denom
        def _smart_recall(motor_root, query, destino_root, limit):
            if query == "check_backlog":
                return (2, "", "git error")  # FALLO for fail-cit surface
            if query == "test":
                return (
                    0,
                    "- obs-fake-cit: test rule (test)\n",
                    "",
                )  # MISS for ok-cit surface
            return (0, "", "")  # Phase queries -> MISS

        hits, denoms, _lr, failures, _cs = _measure_hits(
            queries, citations, pool_by_id, MOTOR_ROOT, MOTOR_ROOT, 5, _smart_recall
        )

        # Surface: fail-cit excluded (FALLO), ok-cit counted but MISS -> 0 hits
        assert hits["superficie"] == 0
        assert denoms["superficie"] == 1  # only obs-ok-cit
        # Union: both counted (phase not all-failed for fail-cit since ok recall is used)
        assert denoms["union"] == 2
        # Failures list
        assert len(failures) == 1
        assert "obs-fail-cit" in failures[0]
        assert "rc=2" in failures[0]


class TestPhasePartialFailure:
    """Fase: a citation with 2 phase queries, one FALLO and one HIT -> HIT of phase
    and inside the denominator.
    """

    def test_phase_one_fallo_one_hit(self):
        """Citation with phase FALLO + phase HIT -> fase HIT and in denominator."""
        recall_count = {"called": 0}

        def _mixed_recall(motor_root, query, destino_root, limit):
            recall_count["called"] += 1
            if query == "suite":
                return (2, "", "error")  # FALLO
            if query == "commit":
                return (0, "- obs-mixed-cit: test rule (test)\n", "")  # HIT
            return (0, "", "")  # MISS

        citations = [
            _make_fake_citation("scripts/check_backlog.py", "obs-mixed-cit", 10),
        ]
        pool_by_id = {"obs-mixed-cit": {"topic": "test", "signal": "signal"}}

        queries = _build_queries_for_citations(citations, pool_by_id, MOTOR_ROOT)
        hits, denoms, _lr, failures, _cs = _measure_hits(
            queries, citations, pool_by_id, MOTOR_ROOT, MOTOR_ROOT, 5, _mixed_recall
        )

        # Phase: HIT from "commit" query
        assert hits["fase"] == 1
        assert denoms["fase"] == 1  # not all phase queries failed
        # Union: HIT (noqa: ERA001)
        assert hits["union"] == 1
        assert denoms["union"] == 1
        # DoD c: todo rc != 0 se reporta aparte, tambien los de fase
        assert failures == ["obs-mixed-cit:fase:suite:rc=2"]


class TestRecallFormat:
    """Recall injected ALWAYS in the real (rc, stdout, stderr) form."""

    def test_recall_triple_form(self):
        """Injected recall returns (rc, stdout, stderr) tuple."""

        def _triple_recall(motor_root, query, destino_root, limit):
            return (0, "- obs-triple-cit: test\n", "")

        citations = [
            _make_fake_citation("scripts/test.py", "obs-triple-cit", 10),
        ]
        pool_by_id = {"obs-triple-cit": {"topic": "test", "signal": "signal"}}

        queries = _build_queries_for_citations(citations, pool_by_id, MOTOR_ROOT)
        hits, _denoms, _lr, _failures, _cs = _measure_hits(
            queries, citations, pool_by_id, MOTOR_ROOT, MOTOR_ROOT, 5, _triple_recall
        )

        assert hits["superficie"] == 1


# ---------------------------------------------------------------------------
# (iv) Fail-closed: no citations -> rc != 0 and --out does NOT exist
# ---------------------------------------------------------------------------


class TestFailClosed:
    """Tests for fail-closed behavior."""

    def test_all_citations_excluded_returns_one(self):
        """All citations filtered out -> fail-closed."""
        citations = [
            ("AGENTS.md", "obs-x", 1),
            ("CLAUDE.md", "obs-y", 2),
        ]
        filtered, excluded = _filter_excluded_citations(
            citations, "measure_recall_quality"
        )
        assert len(filtered) == 0
        assert excluded == 2


class TestFailClosedIntegration:
    """Integration test for fail-closed: empty universe -> rc != 0."""

    def test_empty_universe_rc_nonzero(self, tmp_path: Path):
        """Empty git grep universe -> main returns rc != 0 and --out doesn't exist."""
        repo_dir = tmp_path / "fake_repo"
        repo_dir.mkdir()
        subprocess.run(["git", "init"], cwd=repo_dir, capture_output=True, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=repo_dir,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=repo_dir,
            capture_output=True,
            check=True,
        )

        archive_dir = tmp_path / "destino" / ".agent" / "runtime" / "memory" / "archive"
        archive_dir.mkdir(parents=True)
        (archive_dir / "test.jsonl").write_text("", encoding="utf-8")

        output_path = tmp_path / "output.md"

        result = subprocess.run(
            [
                sys.executable,
                str(MOTOR_ROOT / "scripts" / "measure_recall_quality.py"),
                "--motor-root",
                str(repo_dir),
                "--destino-root",
                str(tmp_path / "destino"),
                "--out",
                str(output_path),
            ],
            capture_output=True,
            text=True,
            cwd=str(MOTOR_ROOT),
        )

        assert result.returncode != 0
        assert not output_path.exists()


# ---------------------------------------------------------------------------
# (v) Determinism: two runs on same fixture produce byte-identical --out
#       except the date line.
# ---------------------------------------------------------------------------


class TestDeterminism:
    """Tests for deterministic output."""

    def test_deterministic_output(self, tmp_path: Path):
        """Two runs on same data produce identical output except date line."""
        hit_type1 = {"superficie": 2, "fase": 3, "union": 4}
        denoms1 = {"superficie": 5, "fase": 6, "union": 7}
        lessons1 = {
            "obs-a": {
                "superficie_hit": True,
                "fase_hit": True,
                "section": "Test Section",
                "has_superficie_query": True,
                "cit_indices": [0],
            },
            "obs-b": {
                "superficie_hit": False,
                "fase_hit": False,
                "section": "",
                "has_superficie_query": False,
                "cit_indices": [1],
            },
        }
        citation_summary1 = {
            0: {
                "filename": "scripts/test.py",
                "obs_id": "obs-a",
                "line": 10,
                "section": "Test Section",
                "surface_hit": True,
                "fase_hit": True,
                "union_hit": True,
            },
            1: {
                "filename": "scripts/check.py",
                "obs_id": "obs-b",
                "line": 20,
                "section": "",
                "surface_hit": False,
                "fase_hit": False,
                "union_hit": False,
            },
        }
        excluded1 = 2
        failures1 = ["obs-a:superficie:q1:rc=1"]
        pool1 = [{"id": "obs-a"}, {"id": "obs-b"}]
        citations1 = [
            ("scripts/test.py", "obs-a", 10),
            ("scripts/check.py", "obs-b", 20),
        ]
        sha1 = "abc123def"

        out1 = tmp_path / "out1.md"
        out2 = tmp_path / "out2.md"

        _generate_report(
            hit_type1,
            denoms1,
            lessons1,
            citation_summary1,
            citations1,
            pool1,
            excluded1,
            failures1,
            sha1,
            out1,
        )
        _generate_report(
            hit_type1,
            denoms1,
            lessons1,
            citation_summary1,
            citations1,
            pool1,
            excluded1,
            failures1,
            sha1,
            out2,
        )

        content1 = out1.read_text()
        content2 = out2.read_text()

        def strip_date(line: str) -> str:
            if line.startswith("- **Date:**"):
                return ""
            return line

        lines1 = [strip_date(ln) for ln in content1.splitlines()]
        lines2 = [strip_date(ln) for ln in content2.splitlines()]

        assert lines1 == lines2

    def test_deterministic_ordering(self, tmp_path: Path):
        """Lessons in output are sorted deterministically."""
        hit_type = {"superficie": 1, "fase": 0, "union": 1}
        denoms = {"superficie": 2, "fase": 2, "union": 2}
        lessons = {
            "obs-z": {
                "superficie_hit": True,
                "fase_hit": False,
                "section": "",
                "has_superficie_query": True,
                "cit_indices": [0],
            },
            "obs-a": {
                "superficie_hit": False,
                "fase_hit": False,
                "section": "",
                "has_superficie_query": False,
                "cit_indices": [1],
            },
            "obs-m": {
                "superficie_hit": True,
                "fase_hit": False,
                "section": "",
                "has_superficie_query": True,
                "cit_indices": [2],
            },
        }
        citation_summary = {
            0: {
                "filename": "z.py",
                "obs_id": "obs-z",
                "line": 1,
                "section": "",
                "surface_hit": True,
                "fase_hit": False,
                "union_hit": True,
            },
            1: {
                "filename": "a.py",
                "obs_id": "obs-a",
                "line": 2,
                "section": "",
                "surface_hit": False,
                "fase_hit": False,
                "union_hit": False,
            },
            2: {
                "filename": "m.py",
                "obs_id": "obs-m",
                "line": 3,
                "section": "",
                "surface_hit": True,
                "fase_hit": False,
                "union_hit": True,
            },
        }
        out = tmp_path / "order_test.md"
        _generate_report(
            hit_type,
            denoms,
            lessons,
            citation_summary,
            [("z.py", "obs-z", 1), ("a.py", "obs-a", 2), ("m.py", "obs-m", 3)],
            list(lessons.keys()),
            0,
            [],
            "abc123",
            out,
        )

        content = out.read_text()
        # Extract citation rows from detail table (should be sorted by filename:line)
        row_order = []
        in_detail = False
        for line in content.splitlines():
            if "| Fichero:Linea |" in line:
                in_detail = True
                continue
            if in_detail and line.startswith("| "):
                fname = line.split("|")[1].strip()
                row_order.append(fname)
                if "Obs-id" in line or "Obt-id" in line:
                    continue

        # Should be sorted: a.py:2, m.py:3, z.py:1
        assert row_order == sorted(row_order), f"Expected sorted order, got {row_order}"


# ---------------------------------------------------------------------------
# (vi) Integration: real memory_context.py --recall --headlines against fixture
# ---------------------------------------------------------------------------


class TestIntegrationMiss:
    """Integration: real subprocess recall on empty archive -> MISS, not failure."""

    def test_real_subprocess_miss_via_measure_hits(self, tmp_path: Path):
        """Real _recall_run with empty archive is classified as MISS (not failure)."""
        archive_dir = tmp_path / ".agent" / "runtime" / "memory" / "archive"
        archive_dir.mkdir(parents=True)

        citations = [
            _make_fake_citation("scripts/test.py", "obs-integration-miss", 10),
        ]
        pool_by_id = {
            "obs-integration-miss": {"topic": "test", "signal": "test signal"}
        }

        queries = _build_queries_for_citations(citations, pool_by_id, MOTOR_ROOT)
        hits, denoms, results, failures, _cs = _measure_hits(
            queries, citations, pool_by_id, MOTOR_ROOT, tmp_path, 5, _recall_run
        )

        assert hits["superficie"] == 0
        assert denoms["superficie"] == 1
        assert len(failures) == 0
        assert results["obs-integration-miss"]["superficie_hit"] is False


class TestIntegration:
    """Integration test using the real memory_context.py --recall --headlines."""

    def test_real_recall_produces_expected_hit(self, tmp_path: Path):
        """Real subprocess of memory_context.py --recall --headlines against
        a fixture produces at least one expected hit."""
        archive_dir = tmp_path / ".agent" / "runtime" / "memory" / "archive"
        archive_dir.mkdir(parents=True)

        lesson = {
            "id": "obs-integration-test",
            "topic": "testing-integration",
            "signal": "REGLA: always test integration with real recall.",
            "timestamp": "2026-10-24T12:00:00",
            "source": "test",
            "signal_text": "REGLA: always test integration with real recall.",
        }
        (archive_dir / "2026-10.jsonl").write_text(
            json.dumps(lesson, ensure_ascii=False) + "\n", encoding="utf-8"
        )

        l1_dir = tmp_path / ".agent" / "runtime" / "memory"
        l1_file = l1_dir / "observations.jsonl"
        l1_file.write_text(
            json.dumps(lesson, ensure_ascii=False) + "\n", encoding="utf-8"
        )

        import os

        full_env = os.environ.copy()
        full_env["AGENT_PROJECT_ROOT"] = str(tmp_path)

        result = subprocess.run(
            [
                sys.executable,
                str(MOTOR_ROOT / "scripts" / "memory_context.py"),
                "--recall",
                "--headlines",
                "--limit",
                "5",
                "--query",
                "integration",
                "--caller",
                "test_integration",
            ],
            capture_output=True,
            text=True,
            env=full_env,
            cwd=str(MOTOR_ROOT),
            timeout=30,
        )

        assert result.returncode == 0, f"Recall failed: {result.stderr}"
        assert "obs-integration-test" in result.stdout, (
            f"Expected lesson not found. Output: {result.stdout}"
        )


# ---------------------------------------------------------------------------
# _build_queries_for_citations (tests)  # noqa: ERA001
# ---------------------------------------------------------------------------


class TestBuildQueries:
    """Tests for _build_queries_for_citations."""

    def test_single_citation_surface_and_phase(self):
        """One citation -> one surface query + phase queries."""
        citations = [
            _make_fake_citation("scripts/check_backlog.py", "obs-test-1"),
        ]
        pool_by_id = {"obs-test-1": {"topic": "test", "signal": "test"}}

        queries = _build_queries_for_citations(citations, pool_by_id, MOTOR_ROOT)

        surface_queries = [q for q in queries if q[1] == "superficie"]
        fase_queries = [q for q in queries if q[1] == "fase"]

        assert len(surface_queries) == 1
        assert surface_queries[0][2] == "check_backlog"
        assert len(fase_queries) == 8  # all 8 fase terms

    def test_excluded_citation_not_queried(self):
        """Citations with useless stem at root are excluded."""
        citations = [
            _make_fake_citation("AGENTS.md", "obs-test-1"),
        ]
        pool_by_id = {"obs-test-1": {"topic": "test", "signal": "test"}}

        queries = _build_queries_for_citations(citations, pool_by_id, MOTOR_ROOT)

        assert len(queries) == 0

    def test_section_drives_fase_terms(self):
        """Citation in a section with a fase term only queries that term."""
        citations = [
            _make_fake_citation("docs/CLAUDE.md", "obs-test-1", 20),
        ]
        pool_by_id = {"obs-test-1": {"topic": "test", "signal": "test"}}

        queries = _build_queries_for_citations(citations, pool_by_id, MOTOR_ROOT)

        surface_queries = [q for q in queries if q[1] == "superficie"]
        assert len(surface_queries) == 1
        assert surface_queries[0][2] == "docs"


# ---------------------------------------------------------------------------
# _filter_excluded_citations (tests)  # noqa: ERA001
# ---------------------------------------------------------------------------


class TestFilterExcluded:
    """Tests for _filter_excluded_citations."""

    def test_self_citation_excluded(self):
        """Citations to measure_recall_quality.py itself are excluded."""
        citations = [
            _make_fake_citation("scripts/measure_recall_quality.py", "obs-test-1"),
            _make_fake_citation("scripts/check_backlog.py", "obs-test-2"),
        ]

        filtered, _excluded = _filter_excluded_citations(
            citations, "measure_recall_quality"
        )

        assert len(filtered) == 1
        assert filtered[0][0] == "scripts/check_backlog.py"

    def test_other_scripts_preserved(self):
        """Citations to other scripts are preserved."""
        citations = [
            _make_fake_citation("scripts/check_backlog.py", "obs-test-1"),
            _make_fake_citation("scripts/ensemble_dispatch.py", "obs-test-2"),
        ]

        filtered, _excluded = _filter_excluded_citations(
            citations, "measure_recall_quality"
        )

        assert len(filtered) == 2


# ---------------------------------------------------------------------------
# _intersect_with_pool (tests)  # noqa: ERA001
# ---------------------------------------------------------------------------


class TestIntersectPool:
    """Tests for _intersect_with_pool."""

    def test_id_in_pool(self):
        """Citation id present in pool -> kept."""
        pool = [
            {"id": "obs-in-pool", "topic": "test"},
        ]
        citations = [
            _make_fake_citation("scripts/test.py", "obs-in-pool"),
            _make_fake_citation("scripts/test.py", "obs-not-in-pool"),
        ]

        result = _intersect_with_pool(citations, pool)

        assert len(result) == 1
        assert result[0][1] == "obs-in-pool"

    def test_empty_pool(self):
        """No pool entries -> no intersections."""
        pool: list[dict] = []
        citations = [
            _make_fake_citation("scripts/test.py", "obs-x"),
        ]

        result = _intersect_with_pool(citations, pool)

        assert len(result) == 0


# ---------------------------------------------------------------------------
# _CITE_PATTERN regex
# ---------------------------------------------------------------------------


class TestCitePattern:
    """Tests for the _CITE_PATTERN regex."""

    def test_matches_valid_obs_id(self):
        """Valid obs- IDs are matched."""
        matches = _CITE_PATTERN.findall("obs-test-lesson-1 and obs-another")
        assert "obs-test-lesson-1" in matches
        assert "obs-another" in matches

    def test_rejects_invalid_patterns(self):
        """Pattern requires at least one char after obs-."""
        matches = _CITE_PATTERN.findall("obs-test obs-X obs123")
        assert "obs-test" in matches
        assert "obs123" not in matches

    def test_multiple_matches_in_line(self):
        """Multiple IDs in one line all matched."""
        line = "refs: obs-a-1 obs-b-2 obs-c-3"
        matches = _CITE_PATTERN.findall(line)
        assert len(matches) == 3
        assert set(matches) == {"obs-a-1", "obs-b-2", "obs-c-3"}


# ---------------------------------------------------------------------------
# git grep failure abort
# ---------------------------------------------------------------------------


class TestGitGrepFailureAbort:
    """git grep rc >= 2 or exception -> RuntimeError raised."""

    def test_rc2_raises_runtime_error(self, tmp_path: Path):
        """git grep with rc 2 on any path causes RuntimeError."""

        def _mock_run_fail(*args, **kwargs):
            class _Result:
                returncode = 2
                stdout = ""
                stderr = "error"

            return _Result()

        subprocess.run = _mock_run_fail
        try:
            try:
                _git_grep_cites(tmp_path)
                raise AssertionError("Expected RuntimeError")
            except RuntimeError as e:
                assert "git grep failed" in str(e)
        finally:
            subprocess.run = _original_subprocess_run

    def test_rc1_and_rc2_mixed(self, tmp_path: Path):
        """rc 1 on one path is OK, rc 2 on another raises."""
        call_count = [0]

        def _mock_run_mixed(*args, **kwargs):
            call_count[0] += 1

            class _Result:
                returncode = 1 if call_count[0] == 1 else 2
                stdout = ""
                stderr = ""

            return _Result()

        subprocess.run = _mock_run_mixed
        try:
            try:
                _git_grep_cites(tmp_path)
                raise AssertionError("Expected RuntimeError")
            except RuntimeError as e:
                assert "git grep failed" in str(e)
                assert "returncode 2" in str(e)
        finally:
            subprocess.run = _original_subprocess_run

    def test_oserror_raises_runtime_error(self, tmp_path: Path):
        """OSError from git grep -> RuntimeError."""

        def _mock_run_oserror(*args, **kwargs):
            raise OSError("device not ready")

        subprocess.run = _mock_run_oserror
        try:
            try:
                _git_grep_cites(tmp_path)
                raise AssertionError("Expected RuntimeError")
            except RuntimeError as e:
                assert "git grep failed" in str(e)
                assert "device not ready" in str(e)
        finally:
            subprocess.run = _original_subprocess_run


class TestGitGrepSuccessWithMixedRc:
    """rc 1 on some paths, rc 0 on others -> continue, collect."""

    def test_rc1_then_rc0_collects(self, tmp_path: Path):
        """rc 1 on first paths, rc 0 on remaining -> collect only from rc 0 paths."""
        collected_paths = []

        def _mock_run_mixed(*args, **kwargs):
            path_arg = args[0] if args else kwargs.get("args", [])
            path_str = path_arg[-1] if path_arg else ""
            collected_paths.append(path_str)
            idx = len(collected_paths) - 1

            class _Result:
                returncode = 1 if idx < 4 else 0
                stdout = "" if idx < 4 else f"{path_str}:1:obs-test-1"

            return _Result()

        subprocess.run = _mock_run_mixed
        try:
            results = _git_grep_cites(tmp_path)
            assert len(results) == 5
            assert all(r[1] == "obs-test-1" for r in results)
            assert len(collected_paths) == len(_GIT_GREP_PATHS)
        finally:
            subprocess.run = _original_subprocess_run


# ---------------------------------------------------------------------------
# Non-markdown section, rc 1 miss, etc.
# ---------------------------------------------------------------------------


class TestNonMarkdownSection:
    """Non-markdown files must not use comments as sections."""

    def test_python_file_no_section(self, tmp_path: Path):
        """A .py file with a comment # 'heading' must NOT use it as section."""
        py_file = tmp_path / "test_file.py"
        py_file.write_text(
            "# commit fix\n# suite check\n# this is a comment\nx = 1\n",
            encoding="utf-8",
        )
        section = _extract_markdown_section("test_file.py", 1, MOTOR_ROOT)
        assert section == ""

    def test_md_file_gets_section(self, tmp_path: Path):
        """A .md file with a heading # should extract the section."""
        md_file = tmp_path / "test.md"
        md_file.write_text(
            "# My Section\nSome text\n## Subsection\nMore\n",
            encoding="utf-8",
        )
        section = _extract_markdown_section("test.md", 2, tmp_path)
        assert section == "My Section"
        section_h2 = _extract_markdown_section("test.md", 4, tmp_path)
        assert section_h2 == "Subsection"

    def test_header_any_level(self, tmp_path: Path):
        """Headers of any level (1-6) are recognised."""
        md_file = tmp_path / "levels.md"
        md_file.write_text(
            "# L1\n# L1 again\n## L2\n### L3\n#### L4\n##### L5\n###### L6\n",
            encoding="utf-8",
        )
        assert _extract_markdown_section("levels.md", 2, tmp_path) == "L1"
        assert _extract_markdown_section("levels.md", 4, tmp_path) == "L2"
        assert _extract_markdown_section("levels.md", 5, tmp_path) == "L3"
        assert _extract_markdown_section("levels.md", 6, tmp_path) == "L4"
        assert _extract_markdown_section("levels.md", 7, tmp_path) == "L5"
        assert _extract_markdown_section("levels.md", 8, tmp_path) == "L6"

    def test_header_not_in_code_fence(self, tmp_path: Path):
        """A header line inside a code fence does NOT count as a heading."""
        md_file = tmp_path / "fence.md"
        md_file.write_text(
            "# Real Header\nSome text\n```\n# Fake Header\n```\nAfter fence\n",
            encoding="utf-8",
        )
        section = _extract_markdown_section("fence.md", 6, tmp_path)
        assert section == "Real Header"

    def test_hashtag_no_space_is_not_header(self, tmp_path: Path):
        """#hashtag without space after # is not a header."""
        md_file = tmp_path / "hash.md"
        md_file.write_text(
            "#hashtag no space\n## also no space\n# Real Header\n",
            encoding="utf-8",
        )
        section = _extract_markdown_section("hash.md", 4, tmp_path)
        assert section == "Real Header"

    def test_non_md_extension_no_section(self):
        """A real .py file must return empty section."""
        section = _extract_markdown_section(
            "scripts/measure_recall_quality.py", 40, MOTOR_ROOT
        )
        assert section == ""

    def test_code_fence_before_heading_returns_heading_above_fence(
        self, tmp_path: Path
    ):
        """Heading above a code fence that contains # is returned."""
        md_file = tmp_path / "fence_heading.md"
        md_file.write_text(
            "## Sub\nSome text\n```\n# Fake Header\n```\nInside fence\n",
            encoding="utf-8",
        )
        section = _extract_markdown_section("fence_heading.md", 5, tmp_path)
        assert section == "Sub"


class TestRc1Miss:
    """rc 1 with 'No observations found' = MISS, not failure."""

    def test_rc1_no_observations_in_stderr_is_miss(self):
        """rc=1 with 'No observations found' in stderr -> MISS, not failure."""
        citations = [
            _make_fake_citation("scripts/test.py", "obs-test-1", 10),
        ]
        pool_by_id = {"obs-test-1": {"topic": "test", "signal": "test"}}

        def _rc1_no_obs(motor_root, query, destino_root, limit):
            return (1, "", "No observations found.")

        queries = _build_queries_for_citations(citations, pool_by_id, MOTOR_ROOT)
        hits, denoms, results, failures, _cs = _measure_hits(
            queries, citations, pool_by_id, MOTOR_ROOT, MOTOR_ROOT, 5, _rc1_no_obs
        )

        assert hits["superficie"] == 0
        assert denoms["superficie"] == 1
        assert results["obs-test-1"]["superficie_hit"] is False
        assert len(failures) == 0

    def test_rc1_no_observations_in_stdout_is_fail(self):
        """rc=1 with 'No observations found' in stdout (not stderr) -> FAIL."""
        citations = [
            _make_fake_citation("scripts/test.py", "obs-test-1", 10),
        ]
        pool_by_id = {"obs-test-1": {"topic": "test", "signal": "test"}}

        def _rc1_stdout(motor_root, query, destino_root, limit):
            return (1, "No observations found.", "")

        queries = _build_queries_for_citations(citations, pool_by_id, MOTOR_ROOT)
        _hits, _denoms, _lr, failures, _cs = _measure_hits(
            queries, citations, pool_by_id, MOTOR_ROOT, MOTOR_ROOT, 5, _rc1_stdout
        )

        # 1 superficie + 8 fase (sin seccion), todas FALLO y todas reportadas
        assert len(failures) == 9
        assert "obs-test-1:superficie:test:rc=1" in failures

    def test_rc1_with_different_message_is_failure(self):
        """rc=1 with a different stderr message -> FAIL, not miss."""
        citations = [
            _make_fake_citation("scripts/test.py", "obs-test-1", 10),
        ]
        pool_by_id = {"obs-test-1": {"topic": "test", "signal": "test"}}

        def _rc1_error(motor_root, query, destino_root, limit):
            return (1, "", "timeout exceeded")

        queries = _build_queries_for_citations(citations, pool_by_id, MOTOR_ROOT)
        hits, _denoms, _results, failures, _cs = _measure_hits(
            queries, citations, pool_by_id, MOTOR_ROOT, MOTOR_ROOT, 5, _rc1_error
        )

        assert hits["superficie"] == 0
        assert len(failures) == 9
        assert all("rc=1" in f for f in failures)

    def test_rc127_is_failure(self):
        """rc=127 (command not found) -> FAIL, not miss."""
        citations = [
            _make_fake_citation("scripts/test.py", "obs-test-1", 10),
        ]
        pool_by_id = {"obs-test-1": {"topic": "test", "signal": "test"}}

        def _rc127(motor_root, query, destino_root, limit):
            return (127, "", "exec format error")

        queries = _build_queries_for_citations(citations, pool_by_id, MOTOR_ROOT)
        hits, _denoms, _results, failures, _cs = _measure_hits(
            queries, citations, pool_by_id, MOTOR_ROOT, MOTOR_ROOT, 5, _rc127
        )

        assert hits["fase"] == 0
        assert len(failures) == 9
        assert all(f.endswith(":rc=127") for f in failures)


# ---------------------------------------------------------------------------
# Union calculation
# ---------------------------------------------------------------------------


class TestUnionCalculation:
    """Union must include fase hits (not just superficie)."""

    def test_union_counts_fase_only_hit(self):
        """Citation with fase hit but no surface hit -> union=1."""

        def _fase_recall(motor_root, query, destino_root, limit):
            if query == "suite":
                return (0, "- obs-test-lesson-1: test rule (test)\n", "")
            return (0, "", "")

        citations = [
            _make_fake_citation("scripts/check_backlog.py", "obs-test-lesson-1", 10),
        ]
        pool_by_id = {"obs-test-lesson-1": {"topic": "test", "signal": "test signal"}}

        queries = _build_queries_for_citations(citations, pool_by_id, MOTOR_ROOT)
        hits, denoms, results, _failures, _cs = _measure_hits(
            queries, citations, pool_by_id, MOTOR_ROOT, MOTOR_ROOT, 5, _fase_recall
        )

        assert hits["fase"] == 1
        assert hits["union"] == 1
        assert denoms["union"] == 1
        assert results["obs-test-lesson-1"]["fase_hit"] is True
        assert results["obs-test-lesson-1"]["superficie_hit"] is False

    def test_union_counts_either_hit(self):
        """Citation with both surface and fase hits -> union=1."""

        def _both_recall(motor_root, query, destino_root, limit):
            if query == "check_backlog":
                return (0, "- obs-test-lesson-1: test rule (test)\n", "")
            if query == "suite":
                return (0, "- obs-test-lesson-1: test rule (test)\n", "")
            return (0, "", "")

        citations = [
            _make_fake_citation("scripts/check_backlog.py", "obs-test-lesson-1", 10),
        ]
        pool_by_id = {"obs-test-lesson-1": {"topic": "test", "signal": "test signal"}}

        queries = _build_queries_for_citations(citations, pool_by_id, MOTOR_ROOT)
        hits, denoms, _lr, _failures, _cs = _measure_hits(
            queries, citations, pool_by_id, MOTOR_ROOT, MOTOR_ROOT, 5, _both_recall
        )

        assert hits["superficie"] == 1
        assert hits["fase"] == 1
        assert hits["union"] == 1
        assert denoms["union"] == 1

    def test_union_never_less_than_max(self):
        """Union >= max(superficie, fase) invariant."""

        def _multi_recall(motor_root, query, destino_root, limit):
            if query == "check":
                return (0, "- obs-a: test rule (test)\n", "")
            if query == "suite":
                return (0, "- obs-b: test rule (test)\n", "")
            if query == "check_backlog":
                return (0, "- obs-c: test rule (test)\n", "")
            return (0, "", "")

        citations = [
            _make_fake_citation("scripts/check.py", "obs-a", 1),
            _make_fake_citation("scripts/check.py", "obs-b", 2),
            _make_fake_citation("scripts/check_backlog.py", "obs-c", 3),
        ]
        pool_by_id = {
            "obs-a": {"topic": "test", "signal": "test"},
            "obs-b": {"topic": "test", "signal": "test"},
            "obs-c": {"topic": "test", "signal": "test"},
        }

        queries = _build_queries_for_citations(citations, pool_by_id, MOTOR_ROOT)
        hits, _denoms, _lr, _failures, _cs = _measure_hits(
            queries, citations, pool_by_id, MOTOR_ROOT, MOTOR_ROOT, 5, _multi_recall
        )

        assert hits["union"] >= max(hits["superficie"], hits["fase"])


# ---------------------------------------------------------------------------
# Superficie denominator
# ---------------------------------------------------------------------------


class TestSuperficieDenominator:
    """D2: superficie denominator only counts citations with superficie queries."""

    def test_citation_without_surface_query_not_in_denominator(self):
        """Citation with only phase queries does NOT count towards surface denominator."""

        def _fase_recall(motor_root, query, destino_root, limit):
            if query == "suite":
                return (0, "- obs-test-lesson-1: test rule (test)\n", "")
            return (0, "", "")

        citations = [
            _make_fake_citation("scripts/test.py", "obs-test-lesson-1", 10),
        ]
        pool_by_id = {"obs-test-lesson-1": {"topic": "test", "signal": "test signal"}}

        queries = _build_queries_for_citations(citations, pool_by_id, MOTOR_ROOT)
        _hits, denoms, _lr, _failures, _cs = _measure_hits(
            queries, citations, pool_by_id, MOTOR_ROOT, MOTOR_ROOT, 5, _fase_recall
        )

        # "test" stem IS a valid surface query for scripts/test.py
        # So superficie denom = 1 (has surface query, query is MISS not FALLO)
        assert denoms["superficie"] == 1
        assert denoms["fase"] == 1  # Phase hit from "suite"
        assert denoms["union"] == 1

    def test_phase_mix_of_miss_and_failure_stays_in_denominator(self):
        """Manager (ronda 6): una FALLO entre MISS de fase NO saca la cita del denominador."""

        def _mixed_recall(motor_root, query, destino_root, limit):
            if query == "commit":
                return (2, "", "boom")
            return (1, "", "No observations found.")

        citations = [_make_fake_citation("scripts/test.py", "obs-test-lesson-1", 10)]
        pool_by_id = {"obs-test-lesson-1": {"topic": "test", "signal": "test signal"}}

        queries = _build_queries_for_citations(citations, pool_by_id, MOTOR_ROOT)
        assert sum(1 for q in queries if q[1] == "fase") == 8  # sin seccion -> 8
        hits, denoms, _lr, failures, _cs = _measure_hits(
            queries, citations, pool_by_id, MOTOR_ROOT, MOTOR_ROOT, 5, _mixed_recall
        )

        assert denoms["fase"] == 1
        assert hits["fase"] == 0
        assert failures == ["obs-test-lesson-1:fase:commit:rc=2"]

    def test_phase_all_failed_leaves_denominator(self):
        """Manager (ronda 6): solo si TODAS las queries de fase fallan sale del denominador."""

        def _fase_fail_recall(motor_root, query, destino_root, limit):
            if query == "test":  # superficie
                return (1, "", "No observations found.")
            return (2, "", "boom")

        citations = [_make_fake_citation("scripts/test.py", "obs-test-lesson-1", 10)]
        pool_by_id = {"obs-test-lesson-1": {"topic": "test", "signal": "test signal"}}

        queries = _build_queries_for_citations(citations, pool_by_id, MOTOR_ROOT)
        _hits, denoms, _lr, failures, _cs = _measure_hits(
            queries, citations, pool_by_id, MOTOR_ROOT, MOTOR_ROOT, 5, _fase_fail_recall
        )

        assert denoms["fase"] == 0
        assert denoms["superficie"] == 1
        assert denoms["union"] == 1
        assert len(failures) == 8

    def test_detail_row_labels_fallo_not_miss(self, tmp_path: Path):
        """Manager (MINOR codex r5): el detalle por cita marca FALLO, no MISS."""

        def _all_fail(motor_root, query, destino_root, limit):
            return (2, "", "boom")

        citations = [_make_fake_citation("scripts/test.py", "obs-test-lesson-1", 10)]
        pool_by_id = {"obs-test-lesson-1": {"topic": "test", "signal": "test signal"}}
        queries = _build_queries_for_citations(citations, pool_by_id, MOTOR_ROOT)
        hits, denoms, lr, failures, cs = _measure_hits(
            queries, citations, pool_by_id, MOTOR_ROOT, MOTOR_ROOT, 5, _all_fail
        )
        out = tmp_path / "report.md"
        _generate_report(hits, denoms, lr, cs, citations, [], 0, failures, "sha", out)

        row = next(
            ln
            for ln in out.read_text(encoding="utf-8").splitlines()
            if ln.startswith("| scripts/test.py:10 |")
        )
        assert row.endswith("| FALLO | FALLO | FALLO |"), row

    def test_citation_with_surface_query_counts_denominator(self):
        """Citation with at least one superficie query counts towards surface denominator."""

        # Return hit ONLY for the specific surface query, miss for ALL phase queries
        def _surf_recall(motor_root, query, destino_root, limit):
            if query == "check_backlog_admission":
                return (0, "- obs-test-lesson-1: test rule (test)\n", "")
            return (0, "", "")

        citations = [
            _make_fake_citation(
                "scripts/check_backlog_admission.py", "obs-test-lesson-1", 10
            ),
        ]
        pool_by_id = {"obs-test-lesson-1": {"topic": "test", "signal": "test signal"}}

        queries = _build_queries_for_citations(citations, pool_by_id, MOTOR_ROOT)
        hits, denoms, _lr, _failures, _cs = _measure_hits(
            queries, citations, pool_by_id, MOTOR_ROOT, MOTOR_ROOT, 5, _surf_recall
        )

        # Surface: 1 hit, counted in superficie denom
        assert hits["superficie"] == 1
        assert denoms["superficie"] == 1
        # Fase: all phase queries are MISS (not FALLO) -> counted in fase denom
        assert denoms["fase"] == 1
        assert denoms["union"] == 1


# ---------------------------------------------------------------------------
# Manager (ronda 6): el recuento de excluidas se hace sobre G (citadas Y en el
# pool), no sobre todas las citas del grep (DoD b: "cita excluida y contada").
# ---------------------------------------------------------------------------


class TestExcludedCountedWithinG:
    """Excluded citations are counted inside G, after intersecting with the pool."""

    def test_excluded_count_ignores_ids_outside_pool(self, tmp_path: Path):
        repo = tmp_path / "motor"
        (repo / "docs").mkdir(parents=True)
        for args in (
            ["init"],
            ["config", "user.email", "t@t.t"],
            ["config", "user.name", "T"],
        ):
            subprocess.run(["git", *args], cwd=repo, capture_output=True, check=True)
        # AGENTS.md at root is a useless stem -> its citations are excluded.
        (repo / "AGENTS.md").write_text(
            "obs-in-pool-lesson y obs-not-in-pool-lesson\n", encoding="utf-8"
        )
        (repo / "docs" / "guia.md").write_text(
            "# Guia\n\nobs-in-pool-lesson\n", encoding="utf-8"
        )
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-q", "-m", "fixture"],
            cwd=repo,
            capture_output=True,
            check=True,
        )
        archive = tmp_path / "destino" / ".agent" / "runtime" / "memory" / "archive"
        archive.mkdir(parents=True)
        (archive / "observations.test.jsonl").write_text(
            json.dumps(
                {
                    "id": "obs-in-pool-lesson",
                    "topic": "testing",
                    "signal": "Una leccion de prueba lo bastante larga para el pool.",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        out = tmp_path / "report.md"

        result = subprocess.run(
            [
                sys.executable,
                str(MOTOR_ROOT / "scripts" / "measure_recall_quality.py"),
                "--motor-root",
                str(repo),
                "--destino-root",
                str(tmp_path / "destino"),
                "--out",
                str(out),
            ],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
        )

        assert result.returncode == 0, result.stderr
        report = out.read_text(encoding="utf-8")
        assert "**Citas de G (citadas y en el pool):** 2" in report
        assert "**Citas de G excluidas:** 1" in report
        assert "**Citas no excluidas (unidad):** 1" in report
        assert "**Lecciones distintas en las citas no excluidas:** 1" in report
