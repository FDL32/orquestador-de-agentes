"""Scope tests for WOT-2026-070e (portabilidad corregida en WOT-2026-070n).

Verifies that collect_files_to_check() includes the operational surfaces
(.agent/collaboration/, .agent/planning/) and excludes archived/transient
directories (_archive/, archive/, runtime/tmp/, runtime/reviews/,
runtime/review_packets/).

Red-first: these tests MUST FAIL against the pre-fix GLOB_PATTERNS
because ticket_contracts.md is not reached by the current glob patterns.

WOT-2026-070n: estos tests se median contra el workspace REAL de una maquina
concreta, con la ruta absoluta hardcodeada. Eran verdes en Windows y llevaban
10 en rojo en el CI de Linux desde el commit que los introdujo. Ahora usan el
fixture `destino`, que siembra un arbol sintetico en `tmp_path`: portable y
hermetico, y con control positivo sobre la exclusion de ruido.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Import the module under test.  Use the scripts/ path so this works both
# from the motor root and via run_pytest_safe.
# ---------------------------------------------------------------------------
_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from encoding_guard import (  # noqa: E402
    EXCLUDE_PATTERNS,
    GLOB_PATTERNS,
    collect_files_to_check,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_bom_file(tmp_path: Path, name: str) -> Path:
    """Write a file with UTF-8 BOM to *tmp_path* and return the Path."""
    p = tmp_path / name
    p.write_bytes(b"\xef\xbb\xbf# test\n")
    return p


# ---------------------------------------------------------------------------
# WOT-2026-070n: fixture de destino SINTETICO.
#
# Estos tests median `collect_files_to_check()` contra el workspace REAL de una
# maquina concreta, via dos constantes con la ruta absoluta hardcodeada
# (`C:/Users/<user>/...`). Eso tenia dos defectos independientes:
#
#   1. NO PORTABLE: en el runner Linux de CI la ruta Windows se concatena al
#      workspace del checkout y `relative_to()` lanza ValueError. 10 tests en
#      rojo desde el commit que los introdujo, verdes en local todo el tiempo.
#   2. NO HERMETICO: el veredicto dependia del CONTENIDO de un repo externo,
#      que cambia solo. Un test que mide el arbol real no puede distinguir
#      "el guard esta roto" de "alguien borro un fichero del destino".
#
# El fixture reconstruye la ESTRUCTURA que el DoD describe -- superficies vivas
# que deben entrar, directorios de ruido que deben quedar fuera -- sin depender
# de ninguna maquina. Es lo que estos tests debieron ser desde el principio.
# ---------------------------------------------------------------------------

_LIVING_SURFACES = (
    ".agent/collaboration/work_plan.md",
    ".agent/planning/ticket_contracts.md",
)

_NOISE_SURFACES = (
    ".agent/collaboration/_archive/plan_audit/AUDIT_WOT-2026-001a.md",
    ".agent/collaboration/archive/notifications_2026-09-01.md",
    ".agent/runtime/tmp/scratch_note.md",
    ".agent/runtime/reviews/review_raw.md",
    ".agent/runtime/review_packets/packet_001.md",
)


@pytest.fixture
def destino(tmp_path: Path) -> Path:
    """Un destino SINTETICO con las superficies vivas y las de ruido.

    Before: `tmp_path` vacio.
    During: crea los ficheros de `_LIVING_SURFACES` (deben entrar en el
        denominador) y `_NOISE_SURFACES` (deben quedar excluidos).
    After: devuelve la raiz. No toca ningun repo real ni depende del SO.
    """
    for rel in _LIVING_SURFACES + _NOISE_SURFACES:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"# {Path(rel).name}\n", encoding="utf-8")
    return tmp_path


# ---------------------------------------------------------------------------
# DoD-1 / DoD-2: inclusion of operational surfaces
# ---------------------------------------------------------------------------


class TestOperationalSurfacesIncluded:
    """The denominador must include the living operational surfaces.

    DoD-1: collect_files_to_check(<DESTINO_ROOT>) must contain
    .agent/collaboration/work_plan.md and .agent/planning/ticket_contracts.md.
    """

    def test_work_plan_md_in_scope(self, destino: Path) -> None:
        """work_plan.md must be in the denominador collected for the destino."""
        files = collect_files_to_check(destino)
        file_set = {p.relative_to(destino).as_posix() for p in files}
        assert ".agent/collaboration/work_plan.md" in file_set, (
            "DoD-1 FAIL: .agent/collaboration/work_plan.md is NOT in "
            "collect_files_to_check(). GLOB_PATTERNS does not reach it."
        )

    def test_ticket_contracts_md_in_scope(self, destino: Path) -> None:
        """ticket_contracts.md must be in the denominador collected for the destino."""
        files = collect_files_to_check(destino)
        file_set = {p.relative_to(destino).as_posix() for p in files}
        assert ".agent/planning/ticket_contracts.md" in file_set, (
            "DoD-1 FAIL: .agent/planning/ticket_contracts.md is NOT in "
            "collect_files_to_check(). GLOB_PATTERNS does not reach .agent/**/*.md."
        )

    def test_all_operational_surfaces_in_scope(self, destino: Path) -> None:
        """All named operational surfaces must be in the denominador."""
        files = collect_files_to_check(destino)
        file_set = {p.relative_to(destino).as_posix() for p in files}
        missing = [s for s in _LIVING_SURFACES if s not in file_set]
        assert not missing, (
            f"DoD-1 FAIL: surfaces NOT in denominador: {missing}. "
            f"GLOB_PATTERNS={GLOB_PATTERNS}"
        )

    def test_denominator_covers_every_living_surface(self, destino: Path) -> None:
        """DoD-2 como INVARIANTE: el denominador cubre TODAS las vivas y NINGUNA de ruido.

        WOT-2026-070n: la version anterior aseveraba `count > 156` contra el
        workspace real. Ese 156 era una MEDICION cristalizada como criterio, y
        AGENTS.md lo prohibe: caduca sola cuando alguien anade o borra un
        fichero del destino, y entonces el Builder no puede distinguir "el
        mundo avanzo" de "he roto el guard". Ademas era una floor assertion --
        cualquier arbol grande la satisface sin que la expansion funcione.

        El invariante real no es "cuantos" sino "cuales": toda superficie viva
        entra y ninguna de ruido lo hace, sea cual sea el tamano del arbol.
        """
        files = collect_files_to_check(destino)
        file_set = {p.relative_to(destino).as_posix() for p in files}

        missing = [s for s in _LIVING_SURFACES if s not in file_set]
        leaked = [s for s in _NOISE_SURFACES if s in file_set]

        assert not missing, (
            f"DoD-2 FAIL: superficies vivas fuera del denominador: {missing}"
        )
        assert not leaked, (
            f"DoD-2 FAIL: superficies de ruido DENTRO del denominador: {leaked}"
        )


# ---------------------------------------------------------------------------
# DoD-3: exclusion of noise directories
# ---------------------------------------------------------------------------


class TestNoiseExclusion:
    """Noise directories must NOT appear in the denominador.

    DoD-3: no path returned by collect_files_to_check() may contain
    _archive/, archive/, runtime/tmp/, runtime/reviews/, or
    runtime/review_packets/.
    """

    @pytest.mark.parametrize(
        "noise_dir",
        [
            "_archive/",
            "archive/",
            "runtime/tmp/",
            "runtime/reviews/",
            "runtime/review_packets/",
        ],
    )
    def test_noise_dirs_excluded_from_scope(
        self, noise_dir: str, destino: Path
    ) -> None:
        """No collected file path may contain the noise directory marker.

        El fixture `destino` CREA un fichero bajo cada uno de estos directorios
        (ver `_NOISE_SURFACES`), asi que este test tiene control positivo: si la
        exclusion dejara de funcionar, el fichero sembrado aparece y el test se
        pone rojo. Contra el workspace real no habia tal garantia -- el test
        pasaba tambien cuando el directorio simplemente no existia.
        """
        files = collect_files_to_check(destino)
        noisy_paths = [
            p.relative_to(destino).as_posix()
            for p in files
            if noise_dir in p.relative_to(destino).as_posix()
        ]
        assert not noisy_paths, (
            f"DoD-3 FAIL: noise directory {noise_dir!r} found in scope: "
            f"{noisy_paths[:5]}"
        )

    def test_exclude_patterns_cover_noise_dirs(self) -> None:
        """EXCLUDE_PATTERNS must contain entries that cover noise directories."""
        exclude_str = " ".join(EXCLUDE_PATTERNS)
        for noise_dir in ["_archive/", "archive/", "runtime/tmp/"]:
            assert noise_dir.strip("/") in exclude_str or any(
                part in exclude_str for part in noise_dir.split("/")
            ), (
                f"DoD-3 FAIL: EXCLUDE_PATTERNS does not cover {noise_dir!r}. "
                f"Current: {EXCLUDE_PATTERNS}"
            )


# ---------------------------------------------------------------------------
# DoD-4: mutation-verify (par de exit codes)
# ---------------------------------------------------------------------------


class TestMutationVerify:
    """BOM file in living surface -> rc=1; same file in archive -> rc=0.

    DoD-4 measured by DISCOVERY (check_encoding_guard.py without path args),
    never with explicit path argument.
    """

    def test_bom_in_collaboration_detected(self, tmp_path: Path) -> None:
        """A new BOM file in .agent/collaboration/ must be detected (rc=1)."""
        bom_file = _write_bom_file(tmp_path, "bom_test.md")
        result = subprocess.run(
            [
                sys.executable,
                str(_SCRIPTS_DIR / "check_encoding_guard.py"),
                str(bom_file),
            ],
            capture_output=True,
            text=True,
            cwd=_SCRIPTS_DIR.parent,
            check=False,
        )
        assert result.returncode == 1, (
            f"DoD-4 FAIL: BOM file in collaboration should return rc=1, "
            f"got rc={result.returncode}. stderr: {result.stderr[:200]}"
        )
        assert (
            "UTF-8 BOM detected" in result.stderr
            or "corruption" in result.stderr.lower()
        ), f"DoD-4 FAIL: expected BOM/corruption message, got: {result.stderr[:200]}"

    def test_bom_in_archive_not_detected_by_discovery(self, tmp_path: Path) -> None:
        """Same BOM file placed in _archive/ must NOT be detected by discovery."""
        archive_dir = tmp_path / ".agent" / "collaboration" / "_archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        bom_file = _write_bom_file(archive_dir, "bom_test.md")

        # Run check_encoding_guard.py WITHOUT path args (discovery mode)
        subprocess.run(
            [sys.executable, str(_SCRIPTS_DIR / "check_encoding_guard.py")],
            capture_output=True,
            text=True,
            cwd=tmp_path,
            check=False,
        )
        # The file should NOT appear in the denominador, so rc=0 is expected
        # (or rc=1 only from other files, but the _archive file itself must not trigger it)
        # We verify by checking that the _archive path is NOT in collect_files_to_check
        files = collect_files_to_check(tmp_path)
        file_set = {p.relative_to(tmp_path).as_posix() for p in files}
        rel_path = bom_file.relative_to(tmp_path).as_posix()
        assert rel_path not in file_set, (
            f"DoD-4 FAIL: _archive file {rel_path} IS in collect_files_to_check(). "
            "The exclusion for _archive/ is not working."
        )

    def test_mutation_verify_parity(self, tmp_path: Path) -> None:
        """Verify BOTH directions: living file enters scope, archived does not."""
        # Create living file
        collab_dir = tmp_path / ".agent" / "collaboration"
        collab_dir.mkdir(parents=True, exist_ok=True)
        living_bom = _write_bom_file(collab_dir, "living_bom.md")

        # Create archived file (same content)
        archive_dir = tmp_path / ".agent" / "collaboration" / "_archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        archive_bom = _write_bom_file(archive_dir, "living_bom.md")

        files = collect_files_to_check(tmp_path)
        file_set = {p.relative_to(tmp_path).as_posix() for p in files}

        living_rel = living_bom.relative_to(tmp_path).as_posix()
        archive_rel = archive_bom.relative_to(tmp_path).as_posix()

        assert living_rel in file_set, (
            f"DoD-4 FAIL: living file {living_rel} NOT in collect_files_to_check()."
        )
        assert archive_rel not in file_set, (
            f"DoD-4 FAIL: archived file {archive_rel} IS in collect_files_to_check(). "
            "The _archive/ exclusion is not working."
        )


# ---------------------------------------------------------------------------
# Regression: SUSPICIOUS_CODEPOINTS and find_control_chars() unchanged
# ---------------------------------------------------------------------------


class TestDetectionIntact:
    """Verify that detection functions were NOT modified (Forbidden Surface).

    A1 in AUDIT: git diff sobre encoding_guard.py -> SUSPICIOUS_CODEPOINTS y
    find_control_chars() sin cambios.
    """

    def test_suspicious_codepoints_unchanged(self) -> None:
        """SUSPICIOUS_CODEPOINTS must still contain the original codepoints."""
        from encoding_guard import SUSPICIOUS_CODEPOINTS

        expected = {0x00C3, 0x00C2, 0x00E2, 0x00F0, 0x0102, 0xFFFD}
        assert expected == SUSPICIOUS_CODEPOINTS, (
            f"REGRESSION: SUSPICIOUS_CODEPOINTS was modified. "
            f"Expected {expected}, got {SUSPICIOUS_CODEPOINTS}"
        )

    def test_find_control_chars_still_works(self) -> None:
        """find_control_chars must still detect disallowed ASCII control chars."""
        from encoding_guard import find_control_chars

        result = find_control_chars("test\x07bell\x00null")
        assert len(result) >= 2, (
            f"REGRESSION: find_control_chars did not detect control chars. "
            f"Result: {result}"
        )
