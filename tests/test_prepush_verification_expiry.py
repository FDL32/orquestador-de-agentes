"""WOT-2026-044x: el centinela del modo verificacion CADUCA en lectura.

La sesion muerta (crash, Ctrl-C, ventana cerrada) dejaba el centinela encendido
para siempre: la siguiente sesion heredaba la barrera con un baseline git viejo
y cualquier commit posterior contaba como mutacion. `activated_at` ya se
escribia (turn_on); nadie lo leia para decidir caducidad.

DoD bajo test:
(a) centinela cuyo activated_at supera SENTINEL_MAX_AGE_S -> el hook NO bloquea
    y deja diagnostico visible (etiqueta literal EXPIRADO);
(b) umbral constante nombrada y justificada (ver native_stop_hook.py);
(c) MUTATION: neutralizar la comprobacion => el test de expiracion CAE
    (el fixture incluye mutacion real del repo + mensaje sin marcador, asi que
    sin el chequeo el hook bloquearia);
(d) control negativo: centinela fresco con mutacion real SIGUE bloqueando;
(e) activated_at ausente o ilegible -> fail-open (no bloquea), etiqueta literal
    SIN-FECHA-LEGIBLE, coherente con el hook (nunca bloquea ante ambiguedad);
    fecha futura deja el centinela ARMADO (aritmetica conservadora).
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / ".agent" / "hooks" / "native_stop_hook.py"
CLI = ROOT / "scripts" / "verification_mode.py"
SENTINEL_RELPATH = Path(".agent") / "runtime" / "verification_mode.json"


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return proc.stdout


def _hook_env() -> dict:
    """Sin escotillas de entorno: el veredicto debe depender SOLO del fixture."""
    env = dict(os.environ)
    env.pop("AGENT_VERIFICATION_MODE", None)
    env.pop("AGENT_DISABLE_VERIFICATION_STOP_HOOK", None)
    return env


def _make_repo_with_sentinel(tmp_path: Path, activated_at: str) -> Path:
    sys.path.insert(0, str(ROOT / ".agent" / "hooks"))
    from native_stop_hook import status_hash

    repo = tmp_path / "repo"
    repo.mkdir()
    # find_repo_root ancla en `.claude/` (replica la resolucion de
    # settings.json), no en `.git`: sin este directorio el walk-up sube fuera
    # del repo y el centinela queda invisible para el hook.
    (repo / ".claude").mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", "seed.txt")
    _git(repo, "commit", "-m", "seed")

    head = _git(repo, "rev-parse", "HEAD")
    status = _git(repo, "status", "--porcelain")
    payload = {
        "baseline_head": head.strip(),
        "baseline_status_hash": status_hash(status),
        "activated_at": activated_at,
    }
    sentinel = repo / SENTINEL_RELPATH
    sentinel.parent.mkdir(parents=True, exist_ok=True)
    sentinel.write_text(json.dumps(payload), encoding="utf-8")
    return repo


def _mutate(repo: Path) -> None:
    (repo / "work.txt").write_text("trabajo real\n", encoding="utf-8")


def _run_hook(repo: Path, message: str = "cierre final sin marcador"):
    payload = {
        "stop_hook_active": False,
        "last_assistant_message": message,
        "cwd": str(repo),
    }
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=repo,
        env=_hook_env(),
        check=False,
    )


def _iso(offset: timedelta) -> str:
    return (datetime.now(timezone.utc) + offset).isoformat()


# ---------------------------------------------------------------------------
# (a) + (c): centinela expirado NO bloquea, con diagnostico visible
# ---------------------------------------------------------------------------


def test_expired_sentinel_does_not_block(tmp_path):
    repo = _make_repo_with_sentinel(tmp_path, _iso(timedelta(hours=-48)))
    _mutate(repo)

    proc = _run_hook(repo)

    assert proc.returncode == 0, proc.stderr
    verdict = json.loads(proc.stdout)
    assert verdict.get("continue") is True, verdict
    assert "decision" not in verdict, verdict
    assert "EXPIRADO" in proc.stderr
    assert "INACTIVO" in proc.stderr


def test_missing_activated_at_fails_open(tmp_path):
    repo = _make_repo_with_sentinel(tmp_path, _iso(timedelta(hours=1)))
    sentinel = repo / SENTINEL_RELPATH
    data = json.loads(sentinel.read_text(encoding="utf-8"))
    del data["activated_at"]
    sentinel.write_text(json.dumps(data), encoding="utf-8")
    _mutate(repo)

    proc = _run_hook(repo)

    assert proc.returncode == 0, proc.stderr
    verdict = json.loads(proc.stdout)
    assert verdict.get("continue") is True, verdict
    assert "SIN-FECHA-LEGIBLE" in proc.stderr


def test_illegal_activated_at_fails_open(tmp_path):
    repo = _make_repo_with_sentinel(tmp_path, "not-a-timestamp")
    _mutate(repo)

    proc = _run_hook(repo)

    assert proc.returncode == 0, proc.stderr
    verdict = json.loads(proc.stdout)
    assert verdict.get("continue") is True, verdict
    assert "SIN-FECHA-LEGIBLE" in proc.stderr


# ---------------------------------------------------------------------------
# (d) control negativo: fresco y futuro siguen ARMADOS ante mutacion real
# ---------------------------------------------------------------------------


def test_fresh_sentinel_with_real_mutation_still_blocks(tmp_path):
    repo = _make_repo_with_sentinel(tmp_path, _iso(timedelta(minutes=1)))
    _mutate(repo)

    proc = _run_hook(repo)

    assert proc.returncode == 0, proc.stderr
    verdict = json.loads(proc.stdout)
    assert verdict.get("decision") == "block", verdict


def test_future_activated_at_stays_armed(tmp_path):
    """Aritmetica conservadora: fecha futura nunca produce falso relieve."""
    repo = _make_repo_with_sentinel(tmp_path, _iso(timedelta(hours=1)))
    _mutate(repo)

    proc = _run_hook(repo)

    assert proc.returncode == 0, proc.stderr
    verdict = json.loads(proc.stdout)
    assert verdict.get("decision") == "block", verdict


def test_fresh_sentinel_without_mutation_does_not_block(tmp_path):
    """Sin prueba de mutacion, el hook no exige recibo (puerta de mutacion)."""
    repo = _make_repo_with_sentinel(tmp_path, _iso(timedelta(minutes=1)))

    proc = _run_hook(repo)

    assert proc.returncode == 0, proc.stderr
    verdict = json.loads(proc.stdout)
    assert verdict.get("continue") is True, verdict


# ---------------------------------------------------------------------------
# Diagnostico para el operador: status CLI comparte terminologia
# ---------------------------------------------------------------------------


def test_status_cli_annotates_expired(tmp_path):
    repo = _make_repo_with_sentinel(tmp_path, _iso(timedelta(hours=-48)))

    proc = subprocess.run(
        [sys.executable, str(CLI), "status", "--root", str(repo)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    assert "ON pero INACTIVO" in proc.stdout
    assert "EXPIRADO" in proc.stdout


def test_status_cli_fresh_has_no_expiry_annotation(tmp_path):
    repo = _make_repo_with_sentinel(tmp_path, _iso(timedelta(minutes=1)))

    proc = subprocess.run(
        [sys.executable, str(CLI), "status", "--root", str(repo)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.startswith("verification_mode: ON\n")
    assert "INACTIVO" not in proc.stdout
