"""WOT-2026-055q: `run_loop_execution_check` MUERDE cuando hay targets sin gobierno.

La barrera nacio `is_blocking=False` (WOT-2026-040b) porque ningun vuelo emitia
receipts con nonce todavia, y su propio docstring fijaba el criterio de salida:
"el endurecimiento a bloqueante va con el primer vuelo que emita". Ese vuelo ya
emitio (20260812b: nonces, receipts y `loop_execution_targets.txt` con 3 commits),
asi que la rama de FALLO pasa a bloqueante y el cierre aborta.

Estos tests invocan `run_loop_execution_check` REAL sobre fixtures REALES en disco
-- scorecard y emitted_nonces con la forma exacta que escribe `_record_round` /
`emit_nonce`. No se mockea `audit`: un test que reimplementa el criterio pasa
aunque el codigo bajo prueba este roto (patron medido 2026-08-12, 5 veces).

Cobertura del DoD BINARIO del ticket:
  (a) targets presentes + commit sin acreditar -> passed=False, is_blocking=True
  (b) sin targets / targets vacios -> SKIP nombrado, passed=True, no bloqueante
  (c) MUTACION: revertir el flag a False -> cae (a) y SOLO (a)
  (d) CONTROL NEGATIVO: targets con todos los commits acreditados -> pasa
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from prepush_check import run_loop_execution_check  # noqa: E402


COMMIT = "a" * 40
# `code` exige 4 backend_key DISTINTOS (DEFAULT_MIN_DISTINCT_BACKENDS["code"]).
ACCREDITED_BACKENDS = ("BA10", "BA11", "BA12", "BA13")
ISSUER = "BA01"
NONCE = "N-055q"
TS_EMIT = "2026-08-12T10:00:00+00:00"
TS_ROUND = "2026-08-12T10:05:00+00:00"


def _emitted_row(commit: str = COMMIT) -> dict:
    """Fila con la forma que escribe `emit_nonce`."""
    return {
        "ts": TS_EMIT,
        "issuer_role": "orchestrator",
        "issuer_backend_key": ISSUER,
        "issued_before_ts": TS_EMIT,
        "commit_sha": commit,
        "loop_id": "L900",
        "challenge_nonce": NONCE,
    }


def _round_row(backend: str, commit: str = COMMIT) -> dict:
    """Fila con la forma que escribe `_record_round`, sustantiva (output_chars>0)."""
    return {
        "event": "ronda",
        "commit_sha": commit,
        "backend_key": backend,
        "challenge_nonce": NONCE,
        "ts": TS_ROUND,
        "output_chars": 2134,
        "evidencia": "veredicto de la lente",
    }


def _build_destination(
    root: Path,
    *,
    targets: str | None,
    rounds: list[dict],
    emitted: list[dict],
) -> Path:
    """Destino-rol en disco: ensemble/ + collaboration/. `targets=None` -> sin fichero."""
    ensemble = root / ".agent" / "runtime" / "ensemble"
    ensemble.mkdir(parents=True, exist_ok=True)
    (ensemble / "scorecard.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rounds), encoding="utf-8"
    )
    (ensemble / "emitted_nonces.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in emitted), encoding="utf-8"
    )
    collaboration = root / ".agent" / "collaboration"
    collaboration.mkdir(parents=True, exist_ok=True)
    if targets is not None:
        (collaboration / "loop_execution_targets.txt").write_text(
            targets, encoding="utf-8"
        )
    return root


# ------------------------------------------------------------------ (a) MUERDE
def test_targets_with_ungoverned_commit_blocks_the_closeout(tmp_path):
    """(a) DoD: targets presentes + commit sin fan-out -> BLOQUEA el cierre.

    Este es el caso que WOT-2026-055q declara evadible: el vuelo 20260812b
    recorrio TODO el pipeline sin un solo bucle 1->9->2 y nada mecanico lo
    impidio. Con la barrera endurecida, `is_blocking=True` hace que
    `_print_results` marque `blocking_failed` (prepush_check.py:2008).

    MUTACION QUE LO MATA: revertir esa rama a `is_blocking=False`.
    """
    root = _build_destination(
        tmp_path, targets=f"{COMMIT} code\n", rounds=[], emitted=[]
    )
    result = run_loop_execution_check(root)

    assert result.passed is False, result.output
    assert result.is_blocking is True, (
        "un commit declarado en targets y SIN fan-out acreditado debe ABORTAR el "
        f"cierre, no avisar: {result.output}"
    )
    assert result.skipped is False, "esto es un FALLO medido, no un salto"
    assert COMMIT in result.output


def test_partial_fanout_below_minimum_also_blocks(tmp_path):
    """(a-bis) El bucle DEGRADADO tambien muerde: 3 lentes distintas < N=4 para code.

    El vector que muerde de verdad no es "cero rondas" sino el fan-out degradado.
    """
    root = _build_destination(
        tmp_path,
        targets=f"{COMMIT} code\n",
        rounds=[_round_row(bk) for bk in ACCREDITED_BACKENDS[:3]],
        emitted=[_emitted_row()],
    )
    result = run_loop_execution_check(root)

    assert result.passed is False, result.output
    assert result.is_blocking is True, result.output


# ------------------------------------------------- (b) SKIP sigue no-bloqueante
def test_no_targets_file_skips_without_blocking(tmp_path):
    """(b) DoD: sin fichero de targets, SKIP NOMBRADO y NO bloqueante.

    Backward-compat deliberada: un vuelo de solo-docs que no declara targets no
    puede heredar un falso-rojo. El SKIP lleva `skipped=True` para que el informe
    de cierre lo distinga de un gate cumplido -- un `[OK]` a secas los hacia
    identicos (docstring de `CheckResult`).
    """
    root = _build_destination(tmp_path, targets=None, rounds=[], emitted=[])
    result = run_loop_execution_check(root)

    assert result.passed is True
    assert result.is_blocking is False
    assert result.skipped is True, (
        "un SKIP que no se declara `skipped` se imprime como gate cumplido"
    )
    assert "SKIP" in result.output


def test_empty_targets_file_skips_without_blocking(tmp_path):
    """(b-bis) Fichero presente pero sin commits declarados: mismo trato."""
    root = _build_destination(
        tmp_path, targets="# solo un comentario\n\n", rounds=[], emitted=[]
    )
    result = run_loop_execution_check(root)

    assert result.passed is True
    assert result.is_blocking is False
    assert result.skipped is True
    assert "SKIP" in result.output


# --------------------------------------------------------- (d) CONTROL NEGATIVO
def test_fully_accredited_flight_passes_without_aborting(tmp_path):
    """(d) DoD: targets con TODOS los commits acreditados pasa sin abortar.

    Sin este control, endurecer el flag seria indistinguible de romper la rama
    verde: un check que bloquea SIEMPRE tambien satisface (a).
    """
    root = _build_destination(
        tmp_path,
        targets=f"{COMMIT} code\n",
        rounds=[_round_row(bk) for bk in ACCREDITED_BACKENDS],
        emitted=[_emitted_row()],
    )
    result = run_loop_execution_check(root)

    assert result.passed is True, result.output
    assert result.skipped is False, "se ejecuto y acredito: no es un salto"
    assert "1 commit(s)" in result.output


# ------------------------------------------------ WOT-2026-059b (fail-closed x repo)
def _make_motor_repo(root: Path) -> str:
    """Crea un repo git en `root` y devuelve el SHA REAL de HEAD (barrera resuelta
    contra un repo, no contra una cadena)."""
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(
        ["git", "-C", str(root), "config", "user.email", "test@localhost"], check=True
    )
    subprocess.run(["git", "-C", str(root), "config", "user.name", "test"], check=True)
    (root / "seed.txt").write_text("seed", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "seed.txt"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "commit", "-qm", "seed"], check=True, cwd=str(root)
    )
    out = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip()


def _link_motor(dest: Path, motor: Path) -> Path:
    """Escribe el motor_destination_link.json que `resolve_motor_root` lee."""
    cfg = dest / ".agent" / "config"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "motor_destination_link.json").write_text(
        json.dumps({"motor_root": str(motor)}), encoding="utf-8"
    )
    return dest


def test_targets_citing_unresolvable_sha_fail_closed(tmp_path):
    """WOT-2026-059b (a/c): un target cuyo SHA no resuelve en el MOTOR -> FALLA cerrado.

    Medido 2026-08-25: `3128e85` existia en el DESTINO (rc=0) pero no en el MOTOR
    (rc=128), y la barrera lo contaba como acreditado. Sin esta rama, un vuelo hereda
    la acreditacion de commits ajenos, incluso inexistentes en el repo contra el que la
    barrera se resuelve.

    MUTACION QUE LA MATA: retirar el bloque de validacion contra el motor -> este
    test cae (el sha inexistente pasa y acredita).
    """
    motor = tmp_path / "motor"
    _make_motor_repo(motor)
    dest = _link_motor(tmp_path / "dest", motor)
    ghost = "f" * 40
    _build_destination(dest, targets=f"{ghost} code\n", rounds=[], emitted=[])

    result = run_loop_execution_check(dest)

    assert result.passed is False, result.output
    assert result.is_blocking is True, (
        "un target que no resuelve a ningun commit del motor debe ABORTAR el cierre, "
        f"no acreditar por herencia: {result.output}"
    )
    assert ghost in result.output, "debe NOMBRAR el sha no resoluble"
    assert "059b" in result.output


def test_real_flight_commit_passes_with_motor_link(tmp_path):
    """WOT-2026-059b (d): control negativo -- con motor link y un sha REAL + acreditado
    pasa igual que sin el link. Sin esto, endurecer la barrera seria indistinguible de
    romper la rama verde."""
    motor = tmp_path / "motor"
    real_sha = _make_motor_repo(motor)
    dest = _link_motor(tmp_path / "dest", motor)
    _build_destination(
        dest,
        targets=f"{real_sha} code\n",
        rounds=[_round_row(bk, commit=real_sha) for bk in ACCREDITED_BACKENDS],
        emitted=[_emitted_row(commit=real_sha)],
    )

    result = run_loop_execution_check(dest)

    assert result.passed is True, result.output
    assert result.skipped is False, "se ejecuto y acredito: no es un salto"
    assert "1 commit(s)" in result.output
    assert "059b" not in result.output or "no resuelve" not in result.output


# ---------------------------------------------------------------------------
# WOT-2026-059b (follow-up del bucle L970): un fallo de INFRAESTRUCTURA al
# ejecutar git (OSError, timeout) colapsaba en la MISMA rama que "el sha no
# existe", y el mensaje afirmaba "target(s) cuyo SHA no resuelve a un commit del
# MOTOR". Un sha REAL bloqueaba un cierre legitimo con una causa FALSA.
#
# Es la misma doctrina que el propio 059b implanta para el motor no resoluble
# ("None es desconocido, no invalido", `if motor_root is None: return []`):
# un DESCONOCIDO no puede reportarse como INVALIDO.
# ---------------------------------------------------------------------------


def test_059b_git_failure_is_not_reported_as_unresolvable_sha(tmp_path, monkeypatch):
    """ROJO sin el fix: con git roto, un sha REAL sale como no-resoluble.

    Degradar a "no se pudo comprobar" es correcto; afirmar que el sha no existe
    cuando no se llego a mirarlo es un falso-rojo con causa mal nombrada.
    """
    import scripts.prepush_check as pc

    real_sha = "0826b521a1e115e77d6c06d12be7819f4de93156"
    # El motor DEBE resolver, o el early-return `motor_root is None -> []` daria
    # un verde por la razon equivocada (medido: el test pasaba sin el fix).
    import runtime.motor_link as ml

    monkeypatch.setattr(ml, "resolve_motor_root", lambda _p: tmp_path)

    def _boom(*_a, **_k):
        raise OSError("git no disponible (simulado)")

    monkeypatch.setattr(pc.subprocess, "run", _boom)

    out = pc._unresolvable_target_shas(tmp_path, [real_sha])

    assert out == [], (
        "un fallo de INFRAESTRUCTURA (git no ejecutable) NO puede clasificarse "
        f"como 'el sha no resuelve': degrada a desconocido. Salio: {out}"
    )
