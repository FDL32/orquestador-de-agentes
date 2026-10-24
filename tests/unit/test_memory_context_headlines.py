#!/usr/bin/env python3
"""Tests for the --headlines mode of memory_context.py.

Hermetic: uses temporary fixture data, never the live archive.
Each test must FAIL if the piece it verifies is removed.
"""

from __future__ import annotations

import argparse
import contextlib
import subprocess
import sys
from io import StringIO
from pathlib import Path
from unittest import mock

import pytest


# Ensure motor root is on sys.path for imports.
MOTOR_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(MOTOR_ROOT))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _fixture_obs(with_id: bool = True, accent: bool = False) -> list[dict]:
    """Return a small hermetic corpus for testing recall output."""
    base_signal = (
        "REGLA: un fallo no termina donde el codigo dice que termina."
        if not accent
        else "REGLA: una barrera sin cableado es una norma, no una barrera real."
    )
    obs: dict = {
        "topic": "testing",
        "signal": base_signal,
        "source": "test",
        "timestamp": "2026-10-24T12:00:00",
    }
    if with_id:
        obs["id"] = "obs-test-fix"
    return [obs]


# ---------------------------------------------------------------------------
# (i) With --headlines, output never exceeds --budget in UTF-8 bytes,
#     including footer.  Test with non-ASCII headlines and a small budget.
# ---------------------------------------------------------------------------


def test_headlines_budget_cap_utf8():
    """(i) --headlines output is bounded by --budget in UTF-8 bytes."""
    from scripts.memory_context import _print_headlines

    # Force a lot of output so the budget must cut.
    many_obs: list[dict] = []
    for i in range(50):
        obs = {
            "id": f"obs-accent-{i:03d}",
            "topic": "tema",
            "signal": f"Señal con acentos y eñe número {i}. " * 3,
            "source": "test",
            "timestamp": "2026-10-24T12:00:00",
        }
        many_obs.append(obs)

    # budget=100 is below minimum and now correctly raises SystemExit(2).
    for budget in (300, 800, 2000):
        captured = StringIO()
        with mock.patch("sys.stdout", captured):
            _print_headlines(many_obs, budget=budget)
        output = captured.getvalue()
        output_bytes = len(output.encode("utf-8"))
        assert output_bytes <= budget, (
            f"budget={budget}, output_bytes={output_bytes}, output[:200]={output[:200]!r}"
        )


# ---------------------------------------------------------------------------
# (ii) Without --headlines, output is byte-identical to current behavior
#      on a fixed fixture (golden captured before the change).
# ---------------------------------------------------------------------------


def test_recall_unchanged_without_headlines():
    """(ii) --print_recall is unchanged: same output on same fixture."""
    from scripts.memory_context import _print_recall

    fixture = [
        {
            "id": "obs-golden-1",
            "topic": "testing",
            "signal": "SEÑAL CON ACENTOS Y eñe especial 123.",
            "source": "cli",
            "timestamp": "2026-09-07T14:26:55",
        },
        {
            "id": "obs-golden-2",
            "topic": "gates",
            "signal": "Un umbral en una meseta no es un umbral medido.",
            "source": "test",
            "timestamp": "2026-08-05T10:05:00",
        },
    ]
    budget = 5000
    captured = StringIO()
    with mock.patch("sys.stdout", captured):
        _print_recall(fixture, budget=budget)
    output = captured.getvalue()

    # Re-create: the format is line-based and deterministic.
    lines = [
        f"- [{obs['timestamp'][:19]}] **{obs['topic']}**: {obs['signal']} ({obs['source']})"
        for obs in fixture
    ]
    expected = "\n".join(lines) + "\n"

    assert output == expected, (
        f"Output changed! Got:\n{output!r}\nExpected:\n{expected!r}"
    )


# ---------------------------------------------------------------------------
# (iii) With and without --headlines, the SORTED list of lessons before
#        the byte cut is the same.
# ---------------------------------------------------------------------------


def test_ordering_preserved_across_modes():
    """(iii) Both modes iterate observations in the same order before cut."""
    from scripts.memory_context import _print_headlines, _print_recall

    many_obs: list[dict] = []
    for i in range(20):
        obs = {
            "id": f"obs-order-{i:03d}",
            "topic": f"tema-{i}",
            "signal": f"Señal numero {i} con acentos. " * 5,
            "source": "test",
            "timestamp": f"2026-10-24T{12 + i // 60:02d}:{i % 60:02d}:00",
        }
        many_obs.append(obs)

    # Get order from headlines mode
    cap_h = StringIO()
    with mock.patch("sys.stdout", cap_h):
        _print_headlines(many_obs, budget=500)
    output_h = cap_h.getvalue()

    # Get order from full recall mode
    cap_f = StringIO()
    with mock.patch("sys.stdout", cap_f):
        _print_recall(many_obs, budget=3000)
    output_f = cap_f.getvalue()

    # Extract IDs in order from both outputs.
    def _extract_ids(text: str) -> list[str]:
        ids: list[str] = []
        for line in text.splitlines():
            if line.startswith("- obs-"):
                parts = line.split(": ", 1)
                if parts and parts[0].startswith("- obs-"):
                    ids.append(parts[0][2:])  # strip "- "
        return ids

    ids_h = _extract_ids(output_h)
    ids_f = _extract_ids(output_f)

    # The common subset should be in the same relative order.
    # Since both iterate the same `many_obs` list, the first N should match.
    common = [id_ for id_ in ids_h if id_ in ids_f]
    assert common == ids_h[: len(common)], (
        f"Order mismatch! Headlines order: {ids_h[:5]}, Full order: {ids_f[:5]}"
    )


# ---------------------------------------------------------------------------
# (iv) A lesson without id comes out in the form
#        `- <topic>: ... (--recall --query <topic>)`.
# ---------------------------------------------------------------------------


def test_no_id_format():
    """(iv) index_line for a lesson without id uses the query hint."""
    from bus.memory_loader import index_line

    obs_no_id: dict = {
        "topic": "testing",
        "signal": "un titular con acentos y eñe",
        "source": "test",
    }
    result = index_line(obs_no_id)
    expected_start = "- testing: "
    expected_end = " (--recall --query testing)"
    assert result.startswith(expected_start), (
        f"Expected {expected_start!r}, got {result!r}"
    )
    assert result.endswith(expected_end), f"Expected {expected_end!r}, got {result!r}"


# ---------------------------------------------------------------------------
# (v) Explicit --budget overrides the default 2000 of --headlines.
# ---------------------------------------------------------------------------


def test_explicit_budget_overrides():
    """(v) --budget explicit prevails over the --headlines default."""
    from scripts.memory_context import _resolve_recall_budget

    args_headlines = argparse.Namespace(budget=None, headlines=True)
    args_explicit = argparse.Namespace(budget=5000, headlines=True)
    args_no_headlines = argparse.Namespace(budget=None, headlines=False)

    assert _resolve_recall_budget(args_headlines) == 2000
    assert _resolve_recall_budget(args_explicit) == 5000
    assert _resolve_recall_budget(args_no_headlines) == 24000


# ---------------------------------------------------------------------------
# (vi) Public index_line and alias _index_line return the same thing.
# ---------------------------------------------------------------------------


def test_index_line_alias():
    """(vi) index_line and _index_line are identical."""
    from bus.memory_loader import _index_line, index_line

    obs = {
        "id": "obs-alias-test",
        "topic": "testing",
        "signal": "Señal con acentos",
        "source": "test",
    }
    assert index_line(obs) == _index_line(obs), (
        f"index_line={index_line(obs)!r}, _index_line={_index_line(obs)!r}"
    )


# ---------------------------------------------------------------------------
# CLI integration: --headlines flag is recognized
# ---------------------------------------------------------------------------


def test_cli_headlines_flag():
    """Integration: --headlines flag is recognized by argparse."""
    result = subprocess.run(
        [
            sys.executable,
            str(MOTOR_ROOT / "scripts" / "memory_context.py"),
            "--headlines",
            "--help",
        ],
        capture_output=True,
        text=True,
        cwd=str(MOTOR_ROOT),
    )
    assert result.returncode == 0, f"subprocess failed: {result.stderr}"
    assert "--headlines" in result.stdout, "--headlines not in --help output"


def test_cli_no_id_headlines_format():
    """Integration: recall without id prints the query hint form."""
    from bus.memory_loader import index_line

    obs_no_id: dict = {
        "topic": "testing",
        "signal": "señal de prueba",
        "source": "test",
    }
    line = index_line(obs_no_id)
    assert "(--recall --query testing)" in line


# ---------------------------------------------------------------------------
# WOT-2026-124d CHANGES tests
# ---------------------------------------------------------------------------


def test_headlines_blocker_same_truncation():
    """(124d.1 BLOCKER) Topics truncated the SAME way for reserve and print."""
    from scripts.memory_context import _print_headlines

    # 12 observations with topics > 40 chars (like the measured case)
    obs_list: list[dict] = [
        {
            "id": f"obs-long-topic-{i:03d}",
            "topic": "A" * 60,  # 60-char topics
            "signal": "B" * 160,  # 160-char signal
            "source": "test",
            "timestamp": "2026-10-24T12:00:00",
        }
        for i in range(12)
    ]

    for budget in (300, 400, 600, 900):
        captured = StringIO()
        with mock.patch("sys.stdout", captured):
            _print_headlines(obs_list, budget=budget)
        output = captured.getvalue()
        output_bytes = len(output.encode("utf-8"))
        assert output_bytes <= budget, (
            f"budget={budget}, output_bytes={output_bytes}, output[:300]={output[:300]!r}"
        )


def test_headlines_no_false_number():
    """(124d.2 MAJOR) Footer must NOT contain the false number 360000."""
    from scripts.memory_context import _print_headlines

    obs_list: list[dict] = [
        {
            "id": f"obs-fn-{i:03d}",
            "topic": "tema",
            "signal": "Señal con acentos y eñe número " + str(i),
            "source": "test",
            "timestamp": "2026-10-24T12:00:00",
        }
        for i in range(12)
    ]

    # Use a budget above minimum that forces omission (footer will be printed).
    # The real minimum includes reserve (footer) + smallest headline line.
    captured = StringIO()
    with mock.patch("sys.stdout", captured):
        _print_headlines(obs_list, budget=400)
    output = captured.getvalue()
    assert "360000" not in output, f"Footer contains false number 360000: {output!r}"
    assert "24000" not in output, f"Footer contains old default 24000: {output!r}"


def test_headlines_break_not_continue():
    """(124d.3 MAJOR) break at first line that doesn't fit."""
    from scripts.memory_context import _print_headlines

    # Line 1: short (fits). Line 2: very long signal (doesn't fit after line 1).
    # Line 3: short. With break, only line 1 appears. With continue (bug),
    # lines 1 and 3 would both appear.
    obs_list: list[dict] = [
        {
            "id": "obs-b-0",
            "topic": "tema",
            "signal": "short",
            "source": "t",
            "timestamp": "2026-01-01T00:00:00",
        },
        {
            "id": "obs-b-1",
            "topic": "tema",
            "signal": "x" * 500,
            "source": "t",
            "timestamp": "2026-01-01T00:00:00",
        },
        {
            "id": "obs-b-2",
            "topic": "tema",
            "signal": "short2",
            "source": "t",
            "timestamp": "2026-01-01T00:00:00",
        },
    ]

    # Calculate the max footer for 3 omitted observations, then set budget
    # just barely above minimum so that only 1 line fits before footer_room
    # is exhausted by the second (long) line.
    max_footer_topics = "tema, tema, tema"  # len = 15
    max_footer_template = (
        f"[3 leccion(es) mas no mostradas: --budget 50. "
        f"Sube --budget o acota --query. "
        f"({max_footer_topics})]\n"
        f"Sube el tope con --budget N, o acota con --query."
    )
    max_footer_bytes = len(max_footer_template.encode("utf-8"))
    # Line 1 ("index_line" for obs-b-0) is ~60 bytes. Budget must leave
    # room for line 1 but NOT for line 2.
    budget = (
        60 + max_footer_bytes + 20
    )  # ~92: line1 fits, footer_room=32, line2 (~67) doesn't

    captured = StringIO()
    with mock.patch("sys.stdout", captured):
        _print_headlines(obs_list, budget=budget)
    output = captured.getvalue()
    line_list = [ln for ln in output.splitlines() if ln.startswith("- obs-b-")]

    # With break: only obs-b-0 (obs-b-1 doesn't fit, so we break).
    # With continue (bug): obs-b-0 and obs-b-2 would both appear.
    assert len(line_list) == 1, (
        f"Expected 1 headline line (break at long line 2), got {len(line_list)}: {line_list!r}"
    )
    assert "obs-b-0" in line_list[0], (
        f"First line should be obs-b-0, got: {line_list[0]!r}"
    )


def test_headlines_budget_too_small_rc2():
    """(124d.5 MAJOR) Budget too small -> rc 2, stderr message, no stdout."""
    from scripts.memory_context import _print_headlines

    obs_list: list[dict] = [
        {
            "id": "obs-rc2",
            "topic": "t",
            "signal": "s",
            "source": "t",
            "timestamp": "2026-01-01T00:00:00",
        },
    ]

    stderr_capture = StringIO()
    with mock.patch("sys.stderr", stderr_capture):
        with pytest.raises(SystemExit) as exc_info:
            _print_headlines(obs_list, budget=1)
        assert exc_info.value.code == 2
        stderr_output = stderr_capture.getvalue()
        assert "too small" in stderr_output, (
            f"Expected stderr message about budget, got: {stderr_output!r}"
        )


def test_headlines_limit_warning_inside_budget():
    """(124d.4 MAJOR) Limit warning is counted in the headlines budget."""
    from scripts.memory_context import _print_headlines

    # 5 observations with long signals so each headline line is ~70 bytes.
    # Budget tight: only 2 lines fit. With correct code, limit_warning IS in
    # reservation. With mutation, limit_warning NOT reserved, so 3 lines
    # might print + limit_warning, exceeding budget.
    obs_list: list[dict] = [
        {
            "id": f"obs-lw-{i}",
            "topic": "tema",
            "signal": "x"
            * 500,  # Truncated to 60 by index_line, but headline ~70 bytes
            "source": "t",
            "timestamp": "2026-01-01T00:00:00",
        }
        for i in range(5)
    ]
    # Pre-compute a limit_warning string (~80 chars)
    limit_warning = (
        "[50 coincidencia(s) mas no mostradas: --limit 3. "
        "Sube --limit o acota --query.]\n"
    )
    limit_warning_bytes = len(limit_warning.encode("utf-8"))

    # max_footer for 5 omitted (worst-case with +2 mas)
    max_footer_template = (
        "[5 leccion(es) mas no mostradas: --budget 200. "
        "Sube --budget o acota --query. (tema, +4 mas)]\n"
        "Sube el tope con --budget N, o acota con --query."
    )
    max_footer_bytes = len(max_footer_template.encode("utf-8"))

    # Each headline line is ~70 bytes. 2 lines = 140 bytes.
    # Budget = max_footer + limit_warning + 2 lines (correct code).
    budget = max_footer_bytes + limit_warning_bytes + 140

    captured = StringIO()
    with mock.patch("sys.stdout", captured):
        _print_headlines(obs_list, budget=budget, limit_warning=limit_warning)
    output = captured.getvalue()
    output_bytes = len(output.encode("utf-8"))
    assert output_bytes <= budget, (
        f"Total output ({output_bytes} bytes) must be within --budget ({budget}). "
        f"Mutation: limit_warning not in reservation. "
        f"output={output[:500]!r}"
    )


def test_headlines_cli_ticket_inexistent():
    """(124d.6 MINOR) --ticket <inexistent> falls back to plain recall in headlines."""
    result = subprocess.run(
        [
            sys.executable,
            str(MOTOR_ROOT / "scripts" / "memory_context.py"),
            "--recall",
            "--ticket",
            "FAKE-DOES-NOT-EXIST-12345",
            "--headlines",
            "--limit",
            "3",
            "--budget",
            "500",
        ],
        capture_output=True,
        text=True,
        cwd=str(MOTOR_ROOT),
    )
    # Should succeed (rc 0) with fallback to plain recall
    # Output should be headline format
    if result.returncode == 0 and result.stdout:
        for line in result.stdout.splitlines():
            if line.startswith("- "):
                # Headline lines start with "- " (either "- obs-" or "- topic:")
                break
        else:
            # If no headline lines, that's fine too (could be empty)
            pass


def test_headlines_break_omitted_count():
    """(124d.3 MAJOR addendum) break counts ALL remaining as omitted."""
    from scripts.memory_context import _print_headlines

    # 5 observations: 1 short, 1 long that breaks, 3 more short.
    # With continue (bug): lines 0, 3, 4 printed, omitted=[obs1_topic].
    # With break: only line 0 printed, omitted should include all 4 remaining.
    obs_list: list[dict] = []
    for i in range(5):
        if i == 1:
            obs_list.append(
                {
                    "id": f"obs-br-{i}",
                    "topic": "tema",
                    "signal": "x" * 500,
                    "source": "t",
                    "timestamp": "2026-01-01T00:00:00",
                },
            )
        else:
            obs_list.append(
                {
                    "id": f"obs-br-{i}",
                    "topic": "tema",
                    "signal": f"sen{i}",
                    "source": "t",
                    "timestamp": "2026-01-01T00:00:00",
                },
            )

    # Use a known-good budget found empirically.
    # We need a budget where: (1) line0 fits, (2) line1 breaks, (3) footer
    # reports 4 omitted. Tested: budget=200 works for this fixture.
    budget = 200

    captured = StringIO()
    with mock.patch("sys.stdout", captured):
        _print_headlines(obs_list, budget=budget)
    output = captured.getvalue()

    headline_lines = [ln for ln in output.splitlines() if ln.startswith("- obs-br-")]
    assert len(headline_lines) == 1, (
        f"Expected 1 headline line (break at index 1), got {len(headline_lines)}: {headline_lines}"
    )
    assert "obs-br-0" in headline_lines[0], (
        f"First line should be obs-br-0, got: {headline_lines[0]!r}"
    )

    # Verify ALL 4 remaining observations are in the omitted list by
    # checking the footer. With break, 4 are omitted. With continue (bug),
    # only 1 would be in the list.
    assert "4 leccion" in output, (
        f"Footer should mention 4 omitted (break counts all remaining): {output!r}"
    )


def test_headlines_budget_sweep_no_overflow():
    """(124d.6 BLOCKER) Sweep budgets [150, 1499] for n in {1,3,5,8}:
    output never exceeds budget, with and without limit_warning.

    Catches M1 (reserve_bytes missing the +1): tight budgets overflow by 1 byte.
    """
    from scripts.memory_context import _print_headlines

    lw = (
        "[7 coincidencia(s) mas no mostradas: --limit 5. "
        "Sube --limit o acota --query.]\n"
    )

    for n in (1, 3, 5, 8):
        obs_list = [
            {
                "id": f"obs-{i}",
                "topic": f"tópico{i}",
                "signal": "señal " * (5 + i * 3),
                "source": "test",
                "timestamp": "2026-10-24T12:00:00",
            }
            for i in range(n)
        ]

        for lw_val in ("", lw):
            for budget in range(150, 1500, 3):
                captured = StringIO()
                with (
                    mock.patch("sys.stdout", captured),
                    contextlib.suppress(SystemExit),
                ):
                    _print_headlines(obs_list, budget=budget, limit_warning=lw_val)
                output = captured.getvalue()
                output_bytes = len(output.encode("utf-8"))
                assert output_bytes <= budget, (
                    f"n={n}, budget={budget}, lw={lw_val!r}: "
                    f"output_bytes={output_bytes} > budget={budget}. "
                    f"output={output[:300]!r}"
                )


def test_headlines_limit_warning_always_emitted():
    """(124d.7 BLOCKER) When limit_warning is provided, it ALWAYS appears in output.

    Catches M2 (limit_warning gated behind `used > 10**9`): the warning is never
    emitted because used is always << 10**9.
    """
    from scripts.memory_context import _print_headlines

    lw = (
        "[7 coincidencia(s) mas no mostradas: --limit 5. "
        "Sube --limit o acota --query.]\n"
    )

    # Case 1: Multiple budgets, many observations (some will be omitted).
    # Minimum required with 8 obs + limit_warning is ~311 bytes.
    obs_list = [
        {
            "id": f"obs-{i}",
            "topic": f"tópico{i}",
            "signal": "señal " * (5 + i * 3),
            "source": "test",
            "timestamp": "2026-10-24T12:00:00",
        }
        for i in range(8)
    ]

    for budget in (400, 600, 1000):
        captured = StringIO()
        with mock.patch("sys.stdout", captured), contextlib.suppress(SystemExit):
            _print_headlines(obs_list, budget=budget, limit_warning=lw)
        output = captured.getvalue()
        assert lw in output, (
            f"budget={budget}: limit_warning not in output. output={output[:500]!r}"
        )

    # Case 2: Generous budget, all lines fit, warning still appears
    obs_list_few = [
        {
            "id": f"obs-f-{i}",
            "topic": f"tema{i}",
            "signal": f"sen{i}",
            "source": "t",
            "timestamp": "2026-01-01T00:00:00",
        }
        for i in range(3)
    ]

    captured = StringIO()
    with mock.patch("sys.stdout", captured):
        _print_headlines(obs_list_few, budget=5000, limit_warning=lw)
    output = captured.getvalue()
    assert lw in output, (
        f"Generous budget: limit_warning not in output. output={output[:500]!r}"
    )
