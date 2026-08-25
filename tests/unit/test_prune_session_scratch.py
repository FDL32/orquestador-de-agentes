"""Barreras de `scripts/prune_session_scratch.py` (poda del scratch del harness).

El script BORRA de forma irreversible, asi que sus tres propiedades de seguridad
se prueban aqui y cada una tiene su mutacion:

1. `--dry-run` es el DEFECTO: sin `--apply` no desaparece nada.
2. Una sesion tocada dentro de la ventana NO se poda -- es lo que protege a la
   sesion VIVA que ejecuta el cierre, sin tener que conocer su id.
3. Frontera dura: nada fuera de `<root>` se borra jamas.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.prune_session_scratch import (
    _guard_inside_root,
    is_stale,
    main,
    session_dirs,
)


def _mk_session(root: Path, project: str, sid: str, *, age_days: float) -> Path:
    """Crea `<root>/<project>/<sid>/scratchpad` y le pone una edad concreta."""
    sess = root / project / sid
    (sess / "scratchpad").mkdir(parents=True)
    (sess / "scratchpad" / "f.txt").write_text("x", encoding="utf-8")
    old = time.time() - age_days * 86400
    for p in (sess / "scratchpad" / "f.txt", sess / "scratchpad", sess):
        os.utime(p, (old, old))
    return sess


def test_dry_run_is_the_default_and_deletes_nothing(tmp_path, capsys):
    """BARRERA 1: sin `--apply` no se borra nada, por viejo que sea."""
    root = tmp_path / "claude"
    sess = _mk_session(root, "proj", "vieja", age_days=90)

    rc = main(["--root", str(root), "--days", "14"])
    out = capsys.readouterr().out

    assert rc == 0
    assert sess.is_dir(), "el dry-run NO puede borrar: la sesion debe seguir ahi"
    assert "DRY-RUN" in out, out
    assert "candidatas(>14d)=1" in out, out


def test_apply_removes_only_the_stale_ones(tmp_path, capsys):
    """BARRERA 2: `--apply` borra la vieja y CONSERVA la reciente.

    Este es el control que protege a la sesion viva del cierre: no se la excluye
    por id, se la excluye por mtime.
    """
    root = tmp_path / "claude"
    vieja = _mk_session(root, "proj", "vieja", age_days=90)
    viva = _mk_session(root, "proj", "viva", age_days=0)

    rc = main(["--root", str(root), "--days", "14", "--apply"])
    out = capsys.readouterr().out

    assert rc == 0
    assert not vieja.exists(), "la sesion vieja debia podarse"
    assert viva.is_dir(), "la sesion RECIENTE no puede podarse jamas"
    assert "borradas=1" in out, out


def test_recent_child_keeps_the_session_alive(tmp_path):
    """BARRERA 2.bis: un hijo tocado AHORA salva un directorio padre viejo.

    Sin mirar los hijos, una sesion viva cuyo directorio raiz conserva mtime
    antiguo se auto-podaria mientras la escribe su propio cierre.
    """
    root = tmp_path / "claude"
    sess = _mk_session(root, "proj", "padre-viejo", age_days=90)
    # El hijo se toca AHORA; el padre sigue con mtime de hace 90 dias.
    (sess / "scratchpad" / "reciente.txt").write_text("y", encoding="utf-8")

    assert is_stale(sess, time.time() - 14 * 86400) is False, (
        "un hijo reciente mantiene VIVA la sesion aunque el padre sea viejo"
    )


def test_path_outside_root_aborts(tmp_path):
    """BARRERA 3: la frontera dura no se negocia."""
    root = tmp_path / "claude"
    root.mkdir()
    with pytest.raises(SystemExit) as exc:
        _guard_inside_root(tmp_path / "otro-sitio", root)
    assert "FUERA" in str(exc.value)


def test_unreadable_session_is_kept_not_pruned(tmp_path, monkeypatch):
    """Un DESCONOCIDO no es basura: si no se puede leer el mtime, se CONSERVA."""
    root = tmp_path / "claude"
    sess = _mk_session(root, "proj", "ilegible", age_days=90)

    def _boom(self):
        raise OSError("permiso denegado (simulado)")

    monkeypatch.setattr(Path, "iterdir", _boom)
    assert is_stale(sess, time.time()) is False


def test_session_dirs_only_walks_depth_two(tmp_path):
    """Solo `<root>/<proyecto>/<uuid>`: ni mas arriba ni mas abajo."""
    root = tmp_path / "claude"
    _mk_session(root, "proj", "s1", age_days=1)
    (root / "proj" / "s1" / "scratchpad" / "hondo").mkdir(parents=True, exist_ok=True)
    (root / "suelto.txt").write_text("no soy un proyecto", encoding="utf-8")

    found = session_dirs(root)
    assert [p.name for p in found] == ["s1"], found


def test_missing_root_is_not_an_error(tmp_path, capsys):
    """No encontrar basura NO es un fallo: exit 0 y lo dice."""
    rc = main(["--root", str(tmp_path / "no-existe")])
    assert rc == 0
    assert "nada que podar" in capsys.readouterr().out


def test_days_zero_is_refused(tmp_path, capsys):
    """`--days 0` podaria lo vivo: se rechaza con rc=2, no se ejecuta."""
    root = tmp_path / "claude"
    _mk_session(root, "proj", "viva", age_days=0)
    rc = main(["--root", str(root), "--days", "0", "--apply"])
    assert rc == 2, "una ventana de 0 dias debe rechazarse ANTES de borrar"
    assert "debe ser >= 1" in capsys.readouterr().err


def test_non_empty_candidates_are_named_not_hidden(tmp_path, capsys):
    """El dry-run NOMBRA las candidatas con contenido; no las esconde en un agregado.

    Lo levanto el gate del bucle L990 y el censo le dio la razon: un conteo
    agregado (`candidatas=1502`) hacia INVISIBLE que 4 de ellas tenian ficheros,
    una de ellas un documento de trabajo real. Para un borrado irreversible, ver
    el agregado no basta: el operador tiene que ver QUE va a borrar.
    """
    root = tmp_path / "claude"
    vacia = _mk_session(root, "proj", "vacia", age_days=90)
    (vacia / "scratchpad" / "f.txt").unlink()

    con_datos = _mk_session(root, "proj", "con-datos", age_days=90)
    (con_datos / "scratchpad" / "importante.md").write_text("dato", encoding="utf-8")
    old = time.time() - 90 * 86400
    for p in con_datos.rglob("*"):
        os.utime(p, (old, old))
    os.utime(con_datos, (old, old))

    main(["--root", str(root), "--days", "14"])
    out = capsys.readouterr().out

    assert "NO estan vacias" in out, out
    assert "con-datos" in out, "la candidata con contenido debe NOMBRARSE: " + out
    assert "Revisalas ANTES de --apply" in out, out


def test_all_empty_says_so_explicitly(tmp_path, capsys):
    """Si todas estan vacias, se DICE: el silencio no distingue 'ninguna' de 'no mire'."""
    root = tmp_path / "claude"
    sess = _mk_session(root, "proj", "vacia", age_days=90)
    (sess / "scratchpad" / "f.txt").unlink()

    main(["--root", str(root), "--days", "14"])
    out = capsys.readouterr().out

    assert "todas las candidatas estan vacias" in out, out
