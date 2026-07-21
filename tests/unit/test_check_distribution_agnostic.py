"""Tests for scripts/check_distribution_agnostic.py (WOT-2026-025e).

El punto del guard es su DENOMINADOR: MANIFEST.distribute lleva 51 entradas de
fichero + 1 de DIRECTORIO (skills/, que expande a 92 tracked). Un guard que audita
solo las entradas-fichero salta 92 en silencio (defecto de familia 024c). Estos
tests montan un motor FALSO en el temp REAL del sistema (con git init + MANIFEST
propio + un dir tracked) y ejercen cada rama por separado, con la aguja aislada.

I/O BINARIO: .gitattributes del repo real fuerza eol=lf en *.md/*.py/*.yaml; los
ficheros del motor falso se escriben con write_bytes/newline='' para no depender del
newline de la plataforma ni ensuciar nada.

Cobertura (una idea por test):
  T-DENOM-EXPANDE    : un dir tracked cuenta sus ficheros, no 1; el untracked no viaja.
  T-DENOM-PUBLICA    : la salida trae 'N entradas -> M ficheros'.
  T-AGUJA-*          : cada aguja detecta SU fuga -> exit 1.
  T-FAILCLOSED-*     : git ausente / denominador vacio -> exit 1, jamas 0.
  T-ALLOWLIST-EXIME  : (file,match,needle) exacto exime; T-ALLOWLIST-STALE: no-hit -> 1.
                       El ancla es el TEXTO de la linea, no su ordinal (WOT-2026-026r):
                       sobrevive a lineas insertadas aguas arriba, y MUERE (STALE) si la
                       linea eximida se borra o se edita -- esa mitad no se puede perder.
  T-USERNAME-SKIP    : usuario generico -> SKIPPED; T-USERNAME-ACTIVA via env -> caza.
  T-NO-UTF8          : bytes invalidos se auditan (decode replace), no se saltan.
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

from tests.conftest import REAL_SYSTEM_TEMP


_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "check_distribution_agnostic",
    _ROOT / "scripts" / "check_distribution_agnostic.py",
)
cda = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(cda)


# --------------------------------------------------------------------- helpers
def _wb(path: Path, text: str) -> None:
    """Write text as LF bytes (never let the platform CRLF-ify a fixture)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.replace("\r\n", "\n").encode("utf-8"))


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(root), capture_output=True, text=True, timeout=30
    )


@pytest.fixture
def fake_motor(request: pytest.FixtureRequest):
    """A git-init'd fake motor under the REAL system temp (short path so git init
    never dies with 'Filename too long'). Returns its root; cleaned up after."""
    base = REAL_SYSTEM_TEMP / f"cda_{abs(hash(request.node.name)) % 10**8}"
    if base.exists():
        _rmtree_ro(base)
    base.mkdir(parents=True)
    _git(base, "init", "-q")
    _git(base, "config", "user.email", "t@t.t")
    _git(base, "config", "user.name", "t")
    yield base

    def _rm():
        _rmtree_ro(base)

    request.addfinalizer(_rm)


def _rmtree_ro(path: Path) -> None:
    import shutil
    import stat

    def _onerror(func, p, _exc):
        Path(p).chmod(stat.S_IWRITE)
        func(p)

    shutil.rmtree(path, onerror=_onerror)


def _commit_all(root: Path) -> None:
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "x")


def _policy(needles: dict, allowlist: list | None = None) -> dict:
    return {"needles": needles, "allowlist": allowlist or []}


# ---------------------------------------------------------------- T-DENOM-EXPANDE
def test_denominator_expands_directory_and_skips_untracked(fake_motor: Path):
    """A directory entry counts its tracked files (3), not 1; an untracked file in
    that dir does NOT enter the denominator (it never travels)."""
    _wb(fake_motor / "MANIFEST.distribute", "# c\nAGENTS.md\npkg/\n")
    _wb(fake_motor / "AGENTS.md", "hello\n")
    _wb(fake_motor / "pkg" / "a.py", "a\n")
    _wb(fake_motor / "pkg" / "b.py", "b\n")
    _wb(fake_motor / "pkg" / "c.py", "c\n")
    _commit_all(fake_motor)
    # untracked file inside the dir, AFTER commit -> must not be counted
    _wb(fake_motor / "pkg" / "untracked.py", "u\n")

    n_entries, files, err = cda.build_denominator(fake_motor)
    assert err is None
    assert n_entries == 2  # AGENTS.md + pkg/
    assert set(files) == {"AGENTS.md", "pkg/a.py", "pkg/b.py", "pkg/c.py"}
    assert "pkg/untracked.py" not in files  # untracked never travels


# ---------------------------------------------------------------- T-DENOM-PUBLICA
def test_publishes_the_count(fake_motor: Path):
    _wb(fake_motor / "MANIFEST.distribute", "AGENTS.md\npkg/\n")
    _wb(fake_motor / "AGENTS.md", "hi\n")
    _wb(fake_motor / "pkg" / "a.py", "a\n")
    _wb(fake_motor / "pkg" / "b.py", "b\n")
    _commit_all(fake_motor)
    code, lines = cda.audit(fake_motor, _policy({}))
    assert code == 0
    assert any("2 entradas -> 3 ficheros" in ln for ln in lines), lines


# ---------------------------------------------------------------- T-AGUJA-*
@pytest.mark.parametrize(
    "needle_name,pattern,leak",
    [
        (
            "workspace_motor",
            "orquestador_de_agentes_workspace",
            "x orquestador_de_agentes_workspace y",
        ),
        ("worktree_dev", "orquestador_de_agentes_dev", "cd orquestador_de_agentes_dev"),
        ("user_profile_root", r"C:[\\/]Users", r"path C:\Users\bob"),
    ],
)
def test_each_needle_catches_its_leak(fake_motor: Path, needle_name, pattern, leak):
    _wb(fake_motor / "MANIFEST.distribute", "AGENTS.md\n")
    _wb(fake_motor / "AGENTS.md", f"line ok\n{leak}\n")
    _commit_all(fake_motor)
    code, lines = cda.audit(fake_motor, _policy({needle_name: {"pattern": pattern}}))
    assert code == 1
    assert any(f"aguja {needle_name}: 1 hits" in ln for ln in lines), lines


# ---------------------------------------------------------------- T-FAILCLOSED-*
def test_fail_closed_no_git(monkeypatch, tmp_path: Path):
    """git ls-files can't run (not a repo) -> exit 1, never 0."""
    _wb(tmp_path / "MANIFEST.distribute", "AGENTS.md\n")
    _wb(tmp_path / "AGENTS.md", "hi\n")
    # tmp_path is NOT a git repo -> ls-files returns rc!=0
    code, lines = cda.audit(tmp_path, _policy({}))
    assert code == 1
    assert any("0 ficheros versionados auditados" in ln for ln in lines), lines


def test_fail_closed_empty_denominator(fake_motor: Path):
    """MANIFEST names something tracked-nowhere -> empty denominator -> exit 1."""
    _wb(fake_motor / "MANIFEST.distribute", "does_not_exist_anywhere\n")
    _commit_all(fake_motor)
    code, lines = cda.audit(fake_motor, _policy({}))
    assert code == 1
    assert any("0 ficheros versionados auditados" in ln for ln in lines), lines


def test_fail_closed_missing_manifest(fake_motor: Path):
    code, _lines = cda.audit(fake_motor, _policy({}))
    assert code == 1


# ---------------------------------------------------------------- T-ALLOWLIST
def test_allowlist_exempts_exact_hit(fake_motor: Path):
    _wb(fake_motor / "MANIFEST.distribute", "AGENTS.md\n")
    _wb(fake_motor / "AGENTS.md", "ok\npath C:\\Users\\bob\n")
    _commit_all(fake_motor)
    pol = _policy(
        {"user_profile_root": {"pattern": r"C:[\\/]Users"}},
        [
            {
                "file": "AGENTS.md",
                "match": "path C:\\Users\\bob",
                "needle": "user_profile_root",
            }
        ],
    )
    code, lines = cda.audit(fake_motor, pol)
    assert code == 0, lines
    assert any("1 eximidos" in ln for ln in lines), lines


def test_allowlist_survives_lines_inserted_above(fake_motor: Path):
    """WOT-2026-026r: el ancla es el TEXTO, no el ordinal.

    El incidente que cierra este ticket: anadir lineas AGUAS ARRIBA desplazaba la
    linea eximida, la entrada quedaba STALE y la suite se ponia ROJA por un cambio
    que NO tocaba la fuga. Con el ancla estable la exencion se mueve CON su linea.
    """
    _wb(fake_motor / "MANIFEST.distribute", "AGENTS.md\n")
    _wb(fake_motor / "AGENTS.md", "relleno\n" * 12 + "path C:\\Users\\bob\n")
    _commit_all(fake_motor)
    pol = _policy(
        {"user_profile_root": {"pattern": r"C:[\\/]Users"}},
        [
            {
                "file": "AGENTS.md",
                "match": "path C:\\Users\\bob",
                "needle": "user_profile_root",
            }
        ],
    )
    code, lines = cda.audit(fake_motor, pol)
    assert code == 0, lines
    assert any("0 hits (1 eximidos)" in ln for ln in lines), lines


def test_allowlist_stale_when_no_hit(fake_motor: Path):
    """An allowlist entry that never matches a hit -> STALE -> exit 1."""
    _wb(fake_motor / "MANIFEST.distribute", "AGENTS.md\n")
    _wb(fake_motor / "AGENTS.md", "no leak here at all\n")
    _commit_all(fake_motor)
    pol = _policy(
        {"user_profile_root": {"pattern": r"C:[\\/]Users"}},
        [
            {
                "file": "AGENTS.md",
                "match": "path C:\\Users\\bob",
                "needle": "user_profile_root",
            }
        ],
    )
    code, lines = cda.audit(fake_motor, pol)
    assert code == 1
    assert any("STALE" in ln for ln in lines), lines


def test_allowlist_stale_when_exempted_line_is_deleted(fake_motor: Path):
    """LA MITAD QUE NO SE PUEDE PERDER (NON-GOAL explicito de WOT-2026-026r).

    Cambiar el ancla NO debe relajar el guard: si la linea que justificaba la
    exencion se BORRA, la entrada deja de disparar -> STALE -> exit 1. Sin esta
    mitad, mover el ancla habria convertido la allowlist en un cementerio que
    pre-bendice cualquier futura fuga en ese fichero.
    """
    _wb(fake_motor / "MANIFEST.distribute", "AGENTS.md\n")
    _wb(fake_motor / "AGENTS.md", "la linea eximida ya no esta\n")
    _commit_all(fake_motor)
    pol = _policy(
        {"user_profile_root": {"pattern": r"C:[\\/]Users"}},
        [
            {
                "file": "AGENTS.md",
                "match": "path C:\\Users\\bob",
                "needle": "user_profile_root",
            }
        ],
    )
    code, lines = cda.audit(fake_motor, pol)
    assert code == 1, lines
    assert any("STALE" in ln for ln in lines), lines


def test_allowlist_stale_when_exempted_line_is_edited(fake_motor: Path):
    """Editar el TEXTO eximido tambien mata la exencion: el ancla es exacto.

    Es lo que impide que una exencion escrita para una meta-mencion sobreviva a
    que esa linea se convierta en una fuga REAL con otro contenido.
    """
    _wb(fake_motor / "MANIFEST.distribute", "AGENTS.md\n")
    _wb(fake_motor / "AGENTS.md", "path C:\\Users\\OTRO_VALOR\n")
    _commit_all(fake_motor)
    pol = _policy(
        {"user_profile_root": {"pattern": r"C:[\\/]Users"}},
        [
            {
                "file": "AGENTS.md",
                "match": "path C:\\Users\\bob",
                "needle": "user_profile_root",
            }
        ],
    )
    code, lines = cda.audit(fake_motor, pol)
    assert code == 1, lines
    assert any("STALE" in ln for ln in lines), lines
    # y ademas la linea editada se reporta como fuga NO eximida
    assert any("1 hits (0 eximidos)" in ln for ln in lines), lines


def test_allowlist_does_not_exempt_other_line(fake_motor: Path):
    """Una fuga con OTRO texto en el mismo fichero -> exit 1.

    La exencion cubre una LINEA concreta (identificada por su texto), no el
    fichero entero: es lo que impide que declarar una meta-mencion legitima
    convierta ese fichero en zona franca para fugas reales.
    """
    _wb(fake_motor / "MANIFEST.distribute", "AGENTS.md\n")
    # una linea eximida y otra fuga distinta que NO lo esta
    _wb(fake_motor / "AGENTS.md", "ok\nC:\\Users\\bob\nC:\\Users\\eve\n")
    _commit_all(fake_motor)
    pol = _policy(
        {"user_profile_root": {"pattern": r"C:[\\/]Users"}},
        [
            {
                "file": "AGENTS.md",
                "match": "C:\\Users\\bob",
                "needle": "user_profile_root",
            }
        ],
    )
    code, lines = cda.audit(fake_motor, pol)
    assert code == 1
    assert any("aguja user_profile_root: 1 hits (1 eximidos)" in ln for ln in lines), (
        lines
    )


def test_allowlist_is_scoped_to_its_file(fake_motor: Path):
    """El mismo TEXTO en OTRO fichero no queda eximido: el par (file,match) manda.

    Con el ancla de texto este limite es MAS necesario que con el ordinal: un
    texto identico puede aparecer en varios ficheros, y la exencion solo vale
    donde se justifico.
    """
    _wb(fake_motor / "MANIFEST.distribute", "AGENTS.md\nOTRO.md\n")
    _wb(fake_motor / "AGENTS.md", "path C:\\Users\\bob\n")
    _wb(fake_motor / "OTRO.md", "path C:\\Users\\bob\n")
    _commit_all(fake_motor)
    pol = _policy(
        {"user_profile_root": {"pattern": r"C:[\\/]Users"}},
        [
            {
                "file": "AGENTS.md",
                "match": "path C:\\Users\\bob",
                "needle": "user_profile_root",
            }
        ],
    )
    code, lines = cda.audit(fake_motor, pol)
    assert code == 1, lines
    assert any("1 hits (1 eximidos)" in ln for ln in lines), lines


# ---------------------------------------------------------------- T-USERNAME
def test_username_skip_generic(monkeypatch):
    monkeypatch.setattr(cda.getpass, "getuser", lambda: "ci")
    monkeypatch.delenv("AGNOSTIC_EXTRA_USERNAMES", raising=False)
    rx, msg = cda.resolve_username_needle()
    assert rx is None
    assert "SKIPPED" in msg


def test_username_active_via_env_catches(fake_motor: Path, monkeypatch):
    """The ACTIVE username branch must be REACHABLE (an unreachable branch is half a
    dead barrier). We inject a synthetic username via env -- never the real one to
    disk (that would be the PII regression WOT-2026-025a)."""
    monkeypatch.setattr(cda.getpass, "getuser", lambda: "ci")  # generic base
    monkeypatch.setenv("AGNOSTIC_EXTRA_USERNAMES", "zzztestuser")
    _wb(fake_motor / "MANIFEST.distribute", "AGENTS.md\n")
    _wb(fake_motor / "AGENTS.md", "hello zzztestuser here\n")
    _commit_all(fake_motor)
    code, lines = cda.audit(fake_motor, _policy({}))
    assert code == 1
    assert any("aguja username: 1 hits" in ln for ln in lines), lines


def test_username_word_boundary(fake_motor: Path, monkeypatch):
    """\\b...\\b: the username as a substring of a bigger word must NOT match."""
    monkeypatch.setattr(cda.getpass, "getuser", lambda: "ci")
    monkeypatch.setenv("AGNOSTIC_EXTRA_USERNAMES", "zzztestuser")
    _wb(fake_motor / "MANIFEST.distribute", "AGENTS.md\n")
    _wb(fake_motor / "AGENTS.md", "the zzztestuserXYZ token is bigger\n")
    _commit_all(fake_motor)
    code, lines = cda.audit(fake_motor, _policy({}))
    assert code == 0, lines


# ---------------------------------------------------------------- T-NO-UTF8
def test_non_utf8_file_is_audited_not_skipped(fake_motor: Path):
    """A file with invalid utf-8 bytes must be scanned (decode replace), not skipped
    in silence -- and a leak inside its decodable text must still be caught."""
    _wb(fake_motor / "MANIFEST.distribute", "bin.txt\n")
    # invalid utf-8 (0xff 0xfe) followed by a real leak in ascii
    (fake_motor / "bin.txt").write_bytes(
        b"\xff\xfe garbage\ncd orquestador_de_agentes_dev\n"
    )
    _commit_all(fake_motor)
    code, lines = cda.audit(
        fake_motor, _policy({"worktree_dev": {"pattern": "orquestador_de_agentes_dev"}})
    )
    assert code == 1
    assert any("aguja worktree_dev: 1 hits" in ln for ln in lines), lines


# T-REAL: contrato vivo sobre el arbol real del motor.
def test_real_repo_is_green():
    """LIVE contract: after Part 2 the real repo must audit clean (143 files, 0
    unexempted). The point IS the real tree -- a synthetic-only suite is blind to the
    boundary (WOT-2026-020q)."""
    code, lines = cda.audit(_ROOT)
    joined = "\n".join(lines)
    assert "143 ficheros versionados auditados" in joined, joined
    assert code == 0, joined
