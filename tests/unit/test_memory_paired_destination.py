"""WOT-2026-127d: tests para bus/paired_destination.py y ruta productiva.

Cubre:
- resolvedor: par valido -> destino; link a OTRO motor -> None; candidato
  inexistente -> None; link con BOM -> resuelve; motor_workspace.txt -> gana.
- resolvedor negativos: nombre con ':' -> None; nombre absoluto -> None;
  motor_workspace.txt con '..' -> None; link JSON [] -> None; link JSON string
  -> None; candidato sin .agent/ -> None.
- ruta PRODUCTIVA: get_session_index con motor + destino pareado sintetico
  -> desglose incluye destino, NO hay aviso; mutacion "sin destino" -> aviso.
- hook y CLI anclan al mismo destino (dogfooding_workspace y anchor_memory_root).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


# Resuelve el path absoluto al motor (worktree raiz). Esto es necesario porque
# pytest sandbox cambia el cwd: Path(__file__) sigue siendo correcto (relativo
# al archivo, no al cwd), pero se necesitan subir 3 niveles desde el test file
# hasta el motor (test -> unit -> tests -> worktree root).
_TEST_FILE = Path(__file__).resolve()
_PROJECT_DIR = _TEST_FILE.parent.parent.parent  # worktree raiz
_MOTOR_ABS = _PROJECT_DIR
_HOOK_ABS = _MOTOR_ABS / ".agent" / "hooks" / "session_start_hook.py"

if str(_MOTOR_ABS) not in sys.path:
    sys.path.insert(0, str(_MOTOR_ABS))


# =============================================================================
# Helpers de sintesis
# =============================================================================


def _make_archive_month(root: Path, year: int, month: int, entries: list[dict]) -> None:
    """Crear un fichero de archive observations.{year}-{month}.jsonl."""
    archive_dir = root / ".agent" / "runtime" / "memory" / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    file_path = archive_dir / f"observations.{year:04d}-{month:02d}.jsonl"
    lines_data = "\n".join(json.dumps(e, ensure_ascii=False) for e in entries)
    file_path.write_text(lines_data + "\n", encoding="utf-8")


def _make_motor(tmp_path: Path, name: str = "motor") -> Path:
    """Crear un motor sintetico con su archive y bus/memory_loader.py.

    G7: El motor se coloca bajo `tmp_path / "worktrees" / <repo> / <name>`
    para que el pareado topologico (motor.parent.parent / ..._workspace / name)
    sea tambien hijo de tmp_path y pytest lo limpie automaticamente.
    """
    repo = tmp_path / "worktrees" / "orquestador_de_agentes"
    repo.mkdir(parents=True, exist_ok=True)
    motor = repo / name
    (motor / "bus").mkdir(parents=True, exist_ok=True)
    (motor / "bus" / "memory_loader.py").write_text("# mock", encoding="utf-8")
    (motor / ".agent" / "runtime" / "memory" / "archive").mkdir(
        parents=True, exist_ok=True
    )
    return motor


def _make_destino(
    tmp_path: Path,
    motor: Path,
    name: str = "destino",
    workspace_suffix: str | None = None,
    with_motor_workspace_txt: bool = False,
) -> Path:
    """Crear un destino pareado con motor_destination_link.json.

    G7: Reproduce el layout topologico T3 donde motor y su pareado son
    hermanos bajo `tmp_path / "worktrees" / <repo>`. El resolvedor calcula
    `motor.parent.parent / (motor.parent.name + "_workspace") / motor.name`
    que, con G7, queda dentro de tmp_path.
    """
    raw_candidate = (
        motor.parent.parent / (motor.parent.name + "_workspace") / motor.name
    )
    raw_candidate.mkdir(parents=True, exist_ok=True)
    ws_root = raw_candidate

    (ws_root / ".claude").mkdir(parents=True, exist_ok=True)
    (ws_root / ".agent" / "config").mkdir(parents=True, exist_ok=True)
    (ws_root / ".agent" / "runtime" / "memory" / "archive").mkdir(
        parents=True, exist_ok=True
    )
    (ws_root / ".agent" / "config" / "motor_destination_link.json").write_text(
        json.dumps(
            {
                "motor_root": str(motor),
                "destination_root": str(ws_root),
                "destination_id": motor.name,
            }
        ),
        encoding="utf-8",
    )
    if with_motor_workspace_txt:
        (motor / ".agent" / "config").mkdir(parents=True, exist_ok=True)
        (motor / ".agent" / "config" / "motor_workspace.txt").write_text(
            motor.name + "\n", encoding="utf-8"
        )
    return ws_root


# =============================================================================
# Tests del resolvedor (resolve_paired_destination)
# =============================================================================


class TestResolvePairedDestination:
    def test_par_valido_resuelve(self, tmp_path: Path) -> None:
        """Un motor con su pareado topologico valido devuelve el destino."""
        motor = _make_motor(tmp_path)
        destino = _make_destino(tmp_path, motor)
        from bus.paired_destination import resolve_paired_destination

        expected_candidate = (
            motor.parent.parent / (motor.parent.name + "_workspace") / motor.name
        )
        assert expected_candidate == destino
        assert expected_candidate.is_dir()
        result = resolve_paired_destination(motor)
        assert result is not None, (
            f"resolvedor fallo para motor={motor}, candidate={expected_candidate}"
        )
        assert (result / ".agent" / "config" / "motor_destination_link.json").is_file()

    def test_candidato_inexistente(self, tmp_path: Path) -> None:
        """Motor sin pareado topologico -> None."""
        motor = _make_motor(tmp_path)
        from bus.paired_destination import resolve_paired_destination

        result = resolve_paired_destination(motor)
        assert result is None

    def test_link_a_otro_motor(self, tmp_path: Path) -> None:
        """Link con motor_root que NO es el root actual -> None."""
        motor_a = _make_motor(tmp_path)
        motor_b = tmp_path / "worktrees" / "other_repo" / "motor_b"
        _make_motor(tmp_path, "motor_b")
        ws_root = (
            motor_a.parent.parent / (motor_a.parent.name + "_workspace") / motor_a.name
        )
        (ws_root / ".claude").mkdir(parents=True, exist_ok=True)
        (ws_root / ".agent" / "config").mkdir(parents=True, exist_ok=True)
        (ws_root / ".agent" / "runtime" / "memory" / "archive").mkdir(
            parents=True, exist_ok=True
        )
        (ws_root / ".agent" / "config" / "motor_destination_link.json").write_text(
            json.dumps({"motor_root": str(motor_b), "destination_root": str(ws_root)})
            + "\n",
            encoding="utf-8",
        )
        from bus.paired_destination import resolve_paired_destination

        result = resolve_paired_destination(motor_a)
        assert result is None

    def test_link_with_bom(self, tmp_path: Path) -> None:
        """Link con BOM de PowerShell 5.1 se lee correctamente."""
        motor = _make_motor(tmp_path)
        ws = _make_destino(tmp_path, motor)
        link = ws / ".agent" / "config" / "motor_destination_link.json"
        data = json.dumps(
            {"motor_root": str(motor), "destination_root": str(ws)},
            ensure_ascii=False,
        )
        link.write_text("\ufeff" + data, encoding="utf-8")
        from bus.paired_destination import resolve_paired_destination

        result = resolve_paired_destination(motor)
        assert result is not None, "BOM en link deberia resolverse igual"
        assert result == ws

    def test_motor_workspace_txt_gana(self, tmp_path: Path) -> None:
        """motor_workspace.txt existe -> se usa antes del candidato topologico."""
        motor = _make_motor(tmp_path)
        # ws_explicit debe estar en motor.parent / "explicit_ws" porque
        # el resolvedor resuelve el nombre contra root.parent (motor.parent).
        ws_explicit = motor.parent / "explicit_ws"
        (ws_explicit).mkdir(parents=True, exist_ok=True)
        (ws_explicit / ".agent").mkdir(parents=True, exist_ok=True)
        (motor / ".agent" / "config").mkdir(parents=True, exist_ok=True)
        (motor / ".agent" / "config" / "motor_workspace.txt").write_text(
            "explicit_ws\n", encoding="utf-8"
        )
        ws_topo = _make_destino(tmp_path, motor)
        assert ws_topo != ws_explicit
        from bus.paired_destination import resolve_paired_destination

        result = resolve_paired_destination(motor)
        assert result == ws_explicit

    # --- Negativos (M1, G1, G6) ---

    def test_workspace_name_with_colon(self, tmp_path: Path) -> None:
        """motor_workspace.txt con ':' en el nombre -> None (M1, G6).

        pathlib.Path() / "C:x" colapsa la ruta bajo la raiz (drive-relative
        ignored), sin .agent -> None. Se restaura ':' al filtro de nombres
        prohibidos para paridad con la semantica previa.
        """
        motor = _make_motor(tmp_path)
        (motor / ".agent" / "config").mkdir(parents=True, exist_ok=True)
        name = f"{tmp_path.drive or 'C:'}rev127d_probe"
        decoy = motor.parent / name
        (decoy / ".agent").mkdir(parents=True)
        (motor / ".agent" / "config" / "motor_workspace.txt").write_text(
            name + "\n", encoding="utf-8"
        )
        from bus.paired_destination import resolve_paired_destination

        result = resolve_paired_destination(motor)
        assert result is None, (
            "nombre con ':' debe ser rechazado para evitar path traversal"
        )

    def test_workspace_name_absolute_path(self, tmp_path: Path) -> None:
        """motor_workspace.txt con ruta absoluta -> None."""
        motor = _make_motor(tmp_path)
        (motor / ".agent" / "config").mkdir(parents=True, exist_ok=True)
        (motor / ".agent" / "config" / "motor_workspace.txt").write_text(
            "/etc/passwd\n", encoding="utf-8"
        )
        from bus.paired_destination import resolve_paired_destination

        result = resolve_paired_destination(motor)
        assert result is None

    def test_workspace_name_dotdot(self, tmp_path: Path) -> None:
        """motor_workspace.txt con '..' -> None."""
        motor = _make_motor(tmp_path)
        (motor / ".agent" / "config").mkdir(parents=True, exist_ok=True)
        (motor / ".agent" / "config" / "motor_workspace.txt").write_text(
            "../..\n", encoding="utf-8"
        )
        from bus.paired_destination import resolve_paired_destination

        result = resolve_paired_destination(motor)
        assert result is None

    def test_workspace_name_dot(self, tmp_path: Path) -> None:
        """motor_workspace.txt con '.' -> None."""
        motor = _make_motor(tmp_path)
        (motor / ".agent" / "config").mkdir(parents=True, exist_ok=True)
        (motor / ".agent" / "config" / "motor_workspace.txt").write_text(
            ".\n", encoding="utf-8"
        )
        from bus.paired_destination import resolve_paired_destination

        result = resolve_paired_destination(motor)
        assert result is None

    def test_workspace_name_no_agent_dir(self, tmp_path: Path) -> None:
        """motor_workspace.txt con nombre valido pero sin .agent/ -> None."""
        motor = _make_motor(tmp_path)
        (motor / ".agent" / "config").mkdir(parents=True, exist_ok=True)
        fake_ws = tmp_path / "worktrees" / "fake_ws"
        (fake_ws).mkdir(parents=True, exist_ok=True)
        (motor / ".agent" / "config" / "motor_workspace.txt").write_text(
            "fake_ws\n", encoding="utf-8"
        )
        from bus.paired_destination import resolve_paired_destination

        result = resolve_paired_destination(motor)
        assert result is None

    def test_link_json_array(self, tmp_path: Path) -> None:
        """Link JSON valido pero no objeto (lista) -> None (G1).

        Sin isinstance(data, dict), json.loads("[]") devuelve [] y [].get()
        lanza AttributeError que NO esta en la tupla except (OSError, ValueError,
        KeyError, TypeError).
        """
        motor = _make_motor(tmp_path)
        ws_root = motor.parent.parent / (motor.parent.name + "_workspace") / motor.name
        ws_root.mkdir(parents=True, exist_ok=True)
        (ws_root / ".agent" / "config").mkdir(parents=True, exist_ok=True)
        (ws_root / ".agent" / "config" / "motor_destination_link.json").write_text(
            "[]\n", encoding="utf-8"
        )
        from bus.paired_destination import resolve_paired_destination

        result = resolve_paired_destination(motor)
        assert result is None, "JSON array debe devolver None, no lanzar"

    def test_link_json_string(self, tmp_path: Path) -> None:
        """Link JSON valido pero no objeto (string) -> None (G1)."""
        motor = _make_motor(tmp_path)
        ws_root = motor.parent.parent / (motor.parent.name + "_workspace") / motor.name
        ws_root.mkdir(parents=True, exist_ok=True)
        (ws_root / ".agent" / "config").mkdir(parents=True, exist_ok=True)
        (ws_root / ".agent" / "config" / "motor_destination_link.json").write_text(
            '"hola"\n', encoding="utf-8"
        )
        from bus.paired_destination import resolve_paired_destination

        result = resolve_paired_destination(motor)
        assert result is None, "JSON string debe devolver None, no lanzar"

    def test_link_json_integer(self, tmp_path: Path) -> None:
        """Link JSON valido pero no objeto (entero) -> None (G1)."""
        motor = _make_motor(tmp_path)
        ws_root = motor.parent.parent / (motor.parent.name + "_workspace") / motor.name
        ws_root.mkdir(parents=True, exist_ok=True)
        (ws_root / ".agent" / "config").mkdir(parents=True, exist_ok=True)
        (ws_root / ".agent" / "config" / "motor_destination_link.json").write_text(
            "42\n", encoding="utf-8"
        )
        from bus.paired_destination import resolve_paired_destination

        result = resolve_paired_destination(motor)
        assert result is None, "JSON integer debe devolver None, no lanzar"

    def test_recursion_error_nested_json(self, tmp_path: Path) -> None:
        """Link con JSON patologicamente anidado no lanza (N1, "nunca lanza" literal).

        `json.loads` lanza `RecursionError` con `[`*20000 + `]`*20000; el
        `except Exception` del resolvedor lo captura -> None (contrato "nunca
        lanza").
        """
        motor = _make_motor(tmp_path)
        ws_root = motor.parent.parent / (motor.parent.name + "_workspace") / motor.name
        ws_root.mkdir(parents=True)
        (ws_root / ".agent" / "config").mkdir(parents=True)
        deeply_nested = "[" * 20000 + "]" * 20000
        (ws_root / ".agent" / "config" / "motor_destination_link.json").write_text(
            deeply_nested,
            encoding="utf-8",
        )
        from bus.paired_destination import resolve_paired_destination

        result = resolve_paired_destination(motor)
        assert result is None, (
            "JSON patologicamente anidado debe devolver None, no lanzar RecursionError"
        )


# =============================================================================
# Tests de ruta productiva (get_session_index + aviso)
# =============================================================================


class TestProductivePath:
    def test_destino_pareado_sin_aviso(self, tmp_path: Path) -> None:
        """Motor + destino pareado: el desglose incluye destino, NO hay aviso."""
        import bus.memory_loader as ml

        motor = _make_motor(tmp_path)
        destino = _make_destino(tmp_path, motor)
        _make_archive_month(
            motor,
            2026,
            8,
            [
                {
                    "id": "obs-motor1",
                    "topic": "motor-topic",
                    "source_ticket": "W-001a",
                    "signal": "motor lesson",
                    "timestamp": "2026-08-01T10:00:00Z",
                    "domain": "testing",
                },
            ],
        )
        _make_archive_month(
            destino,
            2026,
            8,
            [
                {
                    "id": "obs-destino1",
                    "topic": "destino-topic",
                    "source_ticket": "W-002a",
                    "signal": "destino lesson",
                    "timestamp": "2026-08-02T10:00:00Z",
                    "domain": "testing",
                },
            ],
        )

        with (
            pytest.MonkeyPatch().context() as mp,
        ):
            mp.setenv("AGENT_PROJECT_ROOT", str(destino))
            mp.setattr(ml, "_get_repo_root", lambda: destino)
            mp.setattr(ml, "_resolve_motor_root", lambda: motor)
            index = ml.get_session_index(budget=5000)

        assert "destino lesson" in index, f"falta destino en index: {index[:500]}"
        assert "motor lesson" in index, f"falta motor en index: {index[:500]}"
        assert "AVISO" not in index, "no deberia haber aviso con destino pareado"

    def test_sin_destino_muestra_aviso(self, tmp_path: Path) -> None:
        """Motor sin destino pareado -> aviso presente."""
        import bus.memory_loader as ml

        motor = _make_motor(tmp_path)
        _make_archive_month(
            motor,
            2026,
            8,
            [
                {
                    "id": "obs-motor1",
                    "topic": "motor-topic",
                    "source_ticket": "W-001a",
                    "signal": "motor lesson",
                    "timestamp": "2026-08-01T10:00:00Z",
                    "domain": "testing",
                },
            ],
        )

        with (
            pytest.MonkeyPatch().context() as mp,
        ):
            mp.setenv("AGENT_PROJECT_ROOT", str(motor))
            mp.setattr(ml, "_get_repo_root", lambda: motor)
            mp.setattr(ml, "_resolve_motor_root", lambda: None)
            index = ml.get_session_index(budget=5000)

        assert "AVISO" in index, f"falta aviso en index: {index[:500]}"
        assert "NO esta cargada" in index, f"texto aviso incompleto: {index[:500]}"


# =============================================================================
# Tests de hook y CLI anclando al mismo destino
# =============================================================================


def _hook_module():
    """Cargar el hook como modulo importable."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("ssh_hook", _HOOK_ABS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestHookAndCliUseSameDestination:
    def test_hook_anchors_to_paired_destination(self, tmp_path: Path) -> None:
        """_dogfooding_workspace del hook ancla al mismo destino pareado.

        _motor_root solo pone `bus/` en sys.path; el resolvedor recibe root.
        """
        motor = _make_motor(tmp_path)
        destino = _make_destino(tmp_path, motor)

        hook = _hook_module()
        assert hook._dogfooding_workspace(motor) == destino

    def test_cli_anchor_to_paired_destination(self, tmp_path: Path) -> None:
        """_anchor_memory_root del CLI ancla al mismo destino pareado.

        G3: Asercion estricta (no floor assertion). Se despega AGENT_PROJECT_ROOT
        con monkeypatch para evitar casos vacuos donde prev_env != None.
        """
        motor = _make_motor(tmp_path)
        destino = _make_destino(tmp_path, motor)

        with pytest.MonkeyPatch().context() as mp:
            mp.delenv("AGENT_PROJECT_ROOT", raising=False)
            import scripts.memory_context as mc

            original_root = mc._MOTOR_ROOT
            try:
                mc._MOTOR_ROOT = motor
                result = mc._anchor_memory_root()
                assert result == destino
            finally:
                mc._MOTOR_ROOT = original_root

    def test_cli_anchor_returns_none_when_env_set(self, tmp_path: Path) -> None:
        """_anchor_memory_root devuelve None si AGENT_PROJECT_ROOT ya esta puesta."""
        with pytest.MonkeyPatch().context() as mp:
            mp.setenv("AGENT_PROJECT_ROOT", "/tmp/fake")
            import scripts.memory_context as mc

            original_root = mc._MOTOR_ROOT
            try:
                mc._MOTOR_ROOT = _MOTOR_ABS
                result = mc._anchor_memory_root()
                assert result is None, (
                    "con AGENT_PROJECT_ROOT puesta, _anchor_memory_root debe ser None"
                )
            finally:
                mc._MOTOR_ROOT = original_root
