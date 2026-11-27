"""Tests for the canonical user-order authority guard.

Before: the temporary repository contains the minimum canonical surfaces.
During: each test mutates only its own temporary fixture when needed.
After: the guard result proves the named authority invariant.
"""

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "check_user_order_authority", ROOT / "scripts" / "check_user_order_authority.py"
)
guard = importlib.util.module_from_spec(SPEC)
if SPEC.loader is None:
    raise RuntimeError("guard module loader is unavailable")
SPEC.loader.exec_module(guard)

R1 = "Una orden posterior y explicita del usuario prevalece sobre una anterior."
R2 = (
    "Un bloqueo por orden del usuario exige antes comprobar los mensajes recientes "
    "del usuario en el hilo de la coordinadora."
)
MARK = "flight_supervision.md"
HOOK = "        stages: [pre-commit]"


def _clause():
    """Before: no files exist. During: return the canonical ASCII clause. After: clause is complete."""
    return """## 2. Autoridad

**Clausula canonica de autoridad de ordenes del usuario.**

- [USUARIO] R1: Una orden posterior y explicita del usuario prevalece sobre una anterior.
- [USUARIO] R2: Un bloqueo por orden del usuario exige antes comprobar los mensajes recientes del usuario en el hilo de la coordinadora. La forma es `PYTHONUTF8=1 PYTHONIOENCODING=utf-8 python scripts/flight/user_msgs.py <hilo con prefijo mcp:> <ISO UTC de inicio>`; exige rc 0 y la linea final `user msgs: N`.
- [DERIVADO, confirmado por el usuario, mensaje 661f5a8c-80a5-4274-a626-92ebc5696848] La orden posterior prevalece en la medida en que contradiga o revoque la anterior; si no es seguro que la contradiga o revoque, o su alcance, no se levanta el veto, se comprueba R2, si persiste se pregunta y quedan pendientes solo la accion no resuelta y sus dependientes, se continua el trabajo independiente. La falta de respuesta no es autorizacion.
- [DERIVADO, confirmado por el usuario, mensaje 661f5a8c-80a5-4274-a626-92ebc5696848] un mensaje generico como continua o sigue solo autoriza una accion irreversible o vetada antes si su contexto establece sin ambiguedad una orden explicita para esa accion y la revocacion del veto aplicable; si no, procedimiento de duda.
- [DERIVADO] Si rc != 0, hay timeout, salida vacia, SALIDA PARCIAL o herramienta ausente, el resultado es NO MEDIDO: la accion vetada no se ejecuta, se continua con lo no vetado, se reintenta y se escala AL USUARIO. El control positivo exige rc 0, `user msgs: N` y un mensaje conocido del hilo.
- [DERIVADO] El inicio es createdAt UTC de la orden aplicada; se registran intervalo, rc y sha12, sin usar "lo MAYOR" ni N.
- [DERIVADO] R2 alcanza el hilo de la coordinadora, el hilo emisor y la coordinadora anterior si hubo relevo en la ventana.
- [DERIVADO] Una duda o bloqueo de autoridad detiene solo la accion afectada y sus pasos dependientes; se registra la pregunta al usuario y se continua con el trabajo avanzable.
"""


def _fixture(tmp_path):
    """Before: tmp_path is empty. During: create the canonical repository surfaces. After: return its root."""
    (tmp_path / "docs/protocol").mkdir(parents=True)
    (tmp_path / "prompts/vuelo_pilares_templates").mkdir(parents=True)
    (tmp_path / "scripts").mkdir()
    (tmp_path / "tests/unit").mkdir(parents=True)
    (tmp_path / "docs/protocol/flight_supervision.md").write_text(
        _clause(), encoding="utf-8"
    )
    template = "1. Consulta docs/protocol/flight_supervision.md seccion 2 Autoridad.\n"
    (tmp_path / "prompts/vuelo_pilares_templates/LATIDO_PLANTILLA.md").write_text(
        template
        + "La supervisora comprueba la regla 2 antes de declarar cualquier bloqueo por orden del usuario.\n",
        encoding="utf-8",
    )
    (tmp_path / "prompts/vuelo_pilares_templates/ARRANQUE_PLANTILLA.md").write_text(
        template, encoding="utf-8"
    )
    (tmp_path / ".pre-commit-config.yaml").write_text(
        "- id: check-user-order-authority\n"
        "  name: check user order authority\n"
        "  entry: uv run python scripts/check_user_order_authority.py\n"
        "  language: system\n"
        "  pass_filenames: false\n"
        "  always_run: true\n"
        f"{HOOK}\n",
        encoding="utf-8",
    )
    (tmp_path / "scripts/guard_denominator_policy.yaml").write_text(
        "version: 1\nguards:\n"
        "  scripts/check_user_order_authority.py:\n"
        "    clase: fixed_denominator\n"
        "    skip_explicito: 'no'\n"
        "    nota: modo automatico pre-commit; --latido/--workspace-root verifica el latido vivo\n",
        encoding="utf-8",
    )
    return tmp_path


def _live_workspace(root, cited):
    """Before: root has a canonical repository. During: create a D-5 roster and heartbeat. After: return heartbeat."""
    flight = root / ".agent/runtime/flight/vuelo/"
    flight.mkdir(parents=True)
    (flight / "flight_roster.json").write_text(
        json.dumps(
            {
                "active_roles": {
                    "supervisor": {"session_code": "CO-111"},
                    "orquestador": {"session_code": "CO-112"},
                }
            }
        ),
        encoding="utf-8",
    )
    heartbeat = flight / "diseno/LATIDO_SUPERVISORA_CO-111_sobre_CO-112_20261112.md"
    heartbeat.parent.mkdir(parents=True)
    heartbeat.write_text(MARK if cited else "sin cita", encoding="utf-8")
    return heartbeat


def test_clausula_unica_en_protocolo():
    """Before: the real protocol is present. During: measure every clause literal. After: all counts match the contract."""
    text = (ROOT / "docs/protocol/flight_supervision.md").read_text(encoding="utf-8")
    assert text.count(R1) == 1
    assert text.count(R2) == 1
    assert text.count("PYTHONUTF8=1") >= 1
    assert text.count("contradiga o revoque") >= 1
    assert text.count("La falta de respuesta no es autorizacion.") == 1
    assert (
        text.count(
            "confirmado por el usuario, mensaje 661f5a8c-80a5-4274-a626-92ebc5696848"
        )
        >= 2
    )
    assert text.count("PENDIENTE DE CONFIRMACION") == 0
    assert text.count("una pregunta no es una orden") == 0


def test_matiz_b_en_clausula():
    """Before: the real protocol is present. During: measure approved A and B. After: both exact texts occur once."""
    text = (ROOT / "docs/protocol/flight_supervision.md").read_text(encoding="utf-8")
    assert text.count(guard.A) == 1
    assert text.count(guard.B) == 1


def test_duplicado_fuera_del_protocolo(tmp_path):
    """Before: literals exist only in the protocol. During: duplicate R1 under docs. After: the guard rejects it."""
    rc, _ = guard.check_repository(ROOT)
    assert rc == 0
    root = _fixture(tmp_path)
    (root / "docs/duplicate.md").write_text(R1, encoding="utf-8")
    rc, _ = guard.check_repository(root)
    assert rc == 1


def test_plantilla_latido_remision():
    """Before: the real heartbeat template is present. During: measure its citation and supervisor prerequisite. After: both are explicit."""
    text = (ROOT / "prompts/vuelo_pilares_templates/LATIDO_PLANTILLA.md").read_text(
        encoding="utf-8"
    )
    assert MARK in text
    assert (
        "la supervisora comprueba la regla 2 antes de declarar cualquier bloqueo por orden del usuario"
        in text
    )


def test_plantilla_arranque_remision():
    """Before: the real startup template is present. During: measure its authority citation. After: the citation is explicit."""
    text = (ROOT / "prompts/vuelo_pilares_templates/ARRANQUE_PLANTILLA.md").read_text(
        encoding="utf-8"
    )
    assert MARK in text


def test_latido_supervisora_sin_cita(tmp_path):
    """Before: a supplied heartbeat is readable. During: it omits the citation. After: the guard rejects it."""
    assert guard.REQUIRED_MARK == MARK
    root = _fixture(tmp_path)
    heartbeat = _live_workspace(root, cited=False)
    rc, _ = guard.check_repository(root, latido=heartbeat)
    assert rc == 1


def test_latido_supervisora_con_cita(tmp_path):
    """Before: a supplied heartbeat cites the protocol. During: run the explicit mode. After: it passes."""
    root = _fixture(tmp_path)
    heartbeat = _live_workspace(root, cited=True)
    rc, _ = guard.check_repository(root, latido=heartbeat)
    assert rc == 0


def test_cableado_precommit():
    """Before: the real pre-commit configuration is present. During: inspect the hook block. After: every wiring field matches."""
    text = (ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    start = text.index("- id: check-user-order-authority")
    end = text.find("\n      - id:", start + 1)
    block = text[start:] if end < 0 else text[start:end]
    for required in (
        "name: check user order authority",
        "entry: uv run python scripts/check_user_order_authority.py",
        "language: system",
        "pass_filenames: false",
        "always_run: true",
        "stages: [pre-commit]",
    ):
        assert required in block


def test_error_entorno_rc2(tmp_path):
    """Before: the repository is valid. During: point workspace discovery at a missing path. After: result is NO MEDIDO."""
    root = _fixture(tmp_path)
    rc, messages = guard.check_repository(root, workspace_root=root / "missing")
    assert rc == 2
    assert any("NO MEDIDO" in message for message in messages)


def test_workspace_descubierto_sin_cita(tmp_path):
    """Before: a workspace and live roster exist. During: its heartbeat omits the citation. After: the guard rejects it."""
    root = _fixture(tmp_path)
    _live_workspace(root, cited=False)
    rc, _ = guard.check_repository(root, workspace_root=root)
    assert rc == 1


def test_workspace_ausente_omision_explicita(tmp_path, monkeypatch):
    """Before: no workspace is configured. During: run default discovery. After: omission is explicit and green."""
    root = _fixture(tmp_path)
    monkeypatch.delenv("AGENT_PROJECT_ROOT", raising=False)
    rc, messages = guard.check_repository(root)
    assert rc == 0
    assert any(
        "OMISION EXPLICITA: latido vivo NO VERIFICADO sin workspace" in message
        for message in messages
    )


def test_workspace_roto_no_medido(tmp_path):
    """Before: workspace discovery is requested. During: roster is malformed. After: result is NO MEDIDO."""
    root = _fixture(tmp_path)
    flight = root / ".agent/runtime/flight/vuelo"
    flight.mkdir(parents=True)
    (flight / "flight_roster.json").write_text("{", encoding="utf-8")
    rc, messages = guard.check_repository(root, workspace_root=root)
    assert rc == 2
    assert any("NO MEDIDO" in message for message in messages)


def test_exclusion_self_files(tmp_path):
    """Before: the protocol is canonical. During: put literals in the guard and test paths. After: D-6 excludes both."""
    root = _fixture(tmp_path)
    (root / "scripts/check_user_order_authority.py").write_text(R1, encoding="utf-8")
    (root / "tests/unit/test_check_user_order_authority.py").write_text(
        R2, encoding="utf-8"
    )
    rc, _ = guard.check_repository(root)
    assert rc == 0


def test_scan_poda_directorios_antes_de_descender(tmp_path, monkeypatch):
    """Before: a fixture has all ignored directories. During: spy on os.walk. After: none is visited.

    Mutant: restore root.rglob in the guard; os.walk records no root and this test fails.
    """
    root = _fixture(tmp_path)
    for dirname in (".git", ".venv", "sandbox", "__pycache__"):
        ignored = root / dirname
        ignored.mkdir()
        (ignored / "literal.bin").write_bytes(guard.R1.encode("utf-8"))

    visited = []
    original_walk = guard.os.walk

    def spy_walk(top):
        for dirpath, dirnames, filenames in original_walk(top):
            visited.append(Path(dirpath))
            yield dirpath, dirnames, filenames

    monkeypatch.setattr(guard.os, "walk", spy_walk)
    rc, messages = guard.check_repository(root)

    assert rc == 0
    assert not any("barrido D-6" in message for message in messages)
    assert root in visited
    assert not any(
        path.name in {".git", ".venv", "sandbox", "__pycache__"} for path in visited
    )


def test_scan_ignora_literal_en_pycache(tmp_path):
    """Before: a valid fixture has a pyc containing R1. During: scan it. After: no duplicate is reported.

    Mutant: remove __pycache__ from the prune set; rc becomes 1 and names the pyc.
    """
    root = _fixture(tmp_path)
    cache = root / "__pycache__"
    cache.mkdir()
    (cache / "cached.pyc").write_bytes(guard.R1.encode("utf-8"))

    rc, messages = guard.check_repository(root)

    assert rc == 0
    assert not any("barrido D-6" in message for message in messages)


def test_scan_conserva_duplicado_real_y_protocolo(tmp_path):
    """Before: a fixture has the canonical protocol. During: test duplicate and control cases. After: only duplicate fails.

    Mutant: ignore all markdown files; the duplicate case returns rc 0 and this test fails.
    """
    duplicate_root = _fixture(tmp_path / "duplicate")
    duplicate = duplicate_root / "docs/duplicate.md"
    duplicate.write_text(guard.R1, encoding="utf-8")

    rc, messages = guard.check_repository(duplicate_root)

    assert rc == 1
    assert any(str(duplicate) in message for message in messages)

    valid_root = _fixture(tmp_path / "valid")
    rc, messages = guard.check_repository(valid_root)

    assert rc == 0
    assert not any("barrido D-6" in message for message in messages)
