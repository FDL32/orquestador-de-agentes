"""Barrera: `_sync_state_after_session_close` NO puede ser un no-op silencioso.

Defecto medido 2026-07-21 (cierre del vuelo FP-20260721d): la funcion regexeaba
SOLO `Estado actual:`, pero el `STATE.md` vivo usa `ACTIVE_TICKET:`/`STATUS:`. El
sub nunca casaba, `updated == state_content`, y no se escribia NADA. El cierre
salia exit 0 creyendo haber sincronizado, y `STATE.md` arrastraba el ticket de una
sesion anterior indefinidamente -- medido: tras cerrar el vuelo de 026v/026r,
`STATE.md` seguia declarando `ACTIVE_TICKET: WOT-2026-022i`. Esa suciedad es la
que hace que `--session-close` resuelva el ticket por FALLBACK del work_plan
stale. Es el mecanismo concreto detras del sintoma de WOT-2026-037c(c).

Un `exit 0` no distingue "sincronice" de "no hice nada": la barrera tiene que
afirmar sobre el CONTENIDO escrito, no sobre el codigo de salida.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "agent_controller_state_sync", _ROOT / ".agent" / "agent_controller.py"
)
ac = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ac)


def _run_sync(monkeypatch, content: str) -> str | None:
    """Ejecuta el sync sobre `content` y devuelve lo ESCRITO (None si no escribio)."""
    written: dict = {}
    state_path = ac.STATE_FILE.resolve()
    monkeypatch.setattr(
        ac, "read_file", lambda p: content if Path(p).resolve() == state_path else ""
    )
    monkeypatch.setattr(
        ac, "write_file", lambda p, c: written.__setitem__("content", c)
    )
    ac._sync_state_after_session_close()
    return written.get("content")


def test_live_format_releases_the_ticket_and_marks_completed(monkeypatch):
    """Formato VIVO: el ticket se libera y el estado queda COMPLETED.

    Mutation: restaurar el regex que solo miraba `Estado actual:` -> no se escribe
    nada y este test cae (que es exactamente el bug que cierra).
    """
    out = _run_sync(monkeypatch, "ACTIVE_TICKET: WOT-2026-022i\nSTATUS: IN_PROGRESS\n")

    assert out is not None, (
        "el sync DEBE escribir sobre el formato vivo; no escribir es el no-op "
        "silencioso que arrastra el ticket a la sesion siguiente"
    )
    assert "ACTIVE_TICKET: -" in out, (
        "tras cerrar la sesion NO hay ticket activo: dejarlo apuntando al cerrado "
        "es lo que contamina el arranque siguiente (fallback del work_plan stale)"
    )
    assert "STATUS: COMPLETED" in out
    assert "WOT-2026-022i" not in out, "el ticket cerrado no puede sobrevivir al sync"


def test_legacy_format_still_supported(monkeypatch):
    """Retrocompat: el formato `Estado actual:` (backups antiguos) sigue funcionando.

    El fix AMPLIA la cobertura, no la sustituye: romper el legacy seria cambiar un
    no-op por una regresion.
    """
    out = _run_sync(monkeypatch, "# State\nEstado actual: IN_PROGRESS\n")

    assert out is not None
    assert "Estado actual: COMPLETED" in out


def test_crlf_content_is_handled(monkeypatch):
    """El STATE.md real de esta maquina tiene CRLF: el regex no puede comerse el \\r.

    Medido: `cat -A` sobre el fichero vivo muestra `ACTIVE_TICKET: ...^M$`. Un
    patron `.+` glotón dejaria el \\r dentro del valor sustituido.
    """
    out = _run_sync(
        monkeypatch, "ACTIVE_TICKET: WOT-2026-022i\r\nSTATUS: COMPLETED\r\n"
    )

    assert out is not None
    assert "ACTIVE_TICKET: -" in out
    assert "WOT-2026-022i" not in out


@pytest.mark.parametrize("content", ["", None])
def test_empty_state_is_a_noop_without_crashing(monkeypatch, content):
    """Sin STATE.md legible no se inventa contenido: se sale sin escribir."""
    monkeypatch.setattr(ac, "read_file", lambda p: content)
    written: dict = {}
    monkeypatch.setattr(
        ac, "write_file", lambda p, c: written.__setitem__("content", c)
    )
    ac._sync_state_after_session_close()
    assert "content" not in written
