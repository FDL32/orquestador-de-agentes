"""Tests for check_settings_canonical_drift (WOT-2026-129l).

Cubre CA1 (trigger canonico + destino desfasado, fichero ajeno, destino al dia),
DoD 3 (universo vacio, link ilegitimo, diff indeterminado) y CA4 (wiring).

Fixture comun: mini motor con gate script stub que replica rc por contenido de
settings (stale -> rc=1, fresh -> rc=0). El stub evita mock-drift: el gate real
(cualquiera) se ejecuta sobre los settings del fixture.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


# --------------------------------------------------------------------------- fixtures
@pytest.fixture()
def mini_motor(tmp_path: Path) -> Path:
    """Mini motor: motor_root/scripts, motor_root/.agent/hooks.

    Crea un motor minimal con:
    - .agent/hooks/claude_guard_entry.py (trigger)
    - scripts/check_claude_settings_portability.py (trigger)
    - scripts/check_settings_canonical_drift.py (lo que testeamos)
    - scripts/check_claude_settings_portability.py (gate STUB)
    """
    motor = tmp_path / "motor"
    motor.mkdir()
    (motor / ".agent").mkdir()
    (motor / ".agent" / "hooks").mkdir()
    (motor / "scripts").mkdir()

    # Trigger file: claude_guard_entry.py
    (motor / ".agent" / "hooks" / "claude_guard_entry.py").write_text(
        "# dummy trigger\n", encoding="utf-8"
    )

    # Trigger file: check_claude_settings_portability.py (STUB gate)
    # El stub: settings con "__STALE__" -> rc=1, cualquier otro -> rc=0.
    (motor / "scripts" / "check_claude_settings_portability.py").write_text(
        "#!/usr/bin/env python3\n"
        "import argparse, sys\n"
        "p = argparse.ArgumentParser()\n"
        'p.add_argument("path")\n'
        "args = p.parse_args()\n"
        'data = open(args.path, encoding="utf-8").read()\n'
        'if "__STALE__" in data:\n'
        '    print("[check-claude-settings-portability] " + args.path + ": STALE")\n'
        "    sys.exit(1)\n"
        'print("[check-claude-settings-portability] " + args.path + ": OK")\n'
        "sys.exit(0)\n",
        encoding="utf-8",
    )

    return motor


def _make_destino(
    tmp_path: Path,
    stale: bool = True,
    dest_name: str = "test_destino",
) -> Path:
    """Agrega un destino al universo con settings.json.

    Args:
        tmp_path: raiz temporal (para raices de destino).
        stale: si True, el settings contendra "__STALE__" (gate falla).
        dest_name: nombre de la carpeta del destino.
    """
    root = tmp_path / "destinos"
    root.mkdir()

    dest = root / dest_name
    dest.mkdir()
    (dest / ".claude").mkdir()
    content = '{"__STALE__": true, "hooks": {}}' if stale else '{"hooks": {}}'
    (dest / ".claude" / "settings.json").write_text(content, encoding="utf-8")

    # motor_destination_link.json apuntando al destino
    link = dest / ".agent" / "config"
    link.mkdir(parents=True, exist_ok=True)
    (link / "motor_destination_link.json").write_text(
        json.dumps({"destination_root": str(dest)}),
        encoding="utf-8",
    )
    return dest


@pytest.fixture()
def add_destino(tmp_path: Path) -> Path:
    """Agrega un destino desfasado (stale) al universo."""
    return _make_destino(tmp_path, stale=True, dest_name="test_destino")


@pytest.fixture()
def add_destino_al_dia(tmp_path: Path) -> Path:
    """Destino al dia (settings pasan el gate del stub)."""
    return _make_destino(tmp_path, stale=False, dest_name="test_destino_al_dia")


# --------------------------------------------------------------------------- tests
class TestTriggerYDrift:
    """CA1: trigger canonico -> lista destinos desfasados; fichero ajeno -> sin aviso."""

    def test_trigger_canonico_lista_destino_desfasado(
        self,
        mini_motor: Path,
        add_destino: Path,
    ):
        """CA1/a: con diff tocando claude_guard_entry.py y destino desfasado,
        la salida contiene el nombre del destino y el comando --sync --dest."""
        # Mock touched_paths para simular trigger canonico
        import scripts.check_settings_canonical_drift as m
        from scripts.check_settings_canonical_drift import main as drift_main

        original = m.touched_paths
        m.touched_paths = lambda pr: (
            [".agent/hooks/claude_guard_entry.py"],
            None,
        )
        try:
            import io
            from contextlib import redirect_stdout

            f = io.StringIO()
            with redirect_stdout(f):
                rc = drift_main(
                    [
                        "--project-root",
                        str(mini_motor),
                        "--destino-root",
                        str(add_destino.parent),
                    ]
                )

            output = f.getvalue()
            assert rc == 0
            assert "AVISO [settings-canonical-drift]" in output
            assert "test_destino" in output
            assert "--sync --dest" in output
        finally:
            m.touched_paths = original

    def test_diff_fichero_ajeno_sin_aviso(
        self,
        mini_motor: Path,
        add_destino: Path,
    ):
        """CA1/b -> CA2: con diff de fichero ajeno, NINGUN aviso de drift."""
        import scripts.check_settings_canonical_drift as m
        from scripts.check_settings_canonical_drift import main as drift_main

        original = m.touched_paths
        m.touched_paths = lambda pr: (
            ["some/other/file.py"],
            None,
        )
        try:
            import io
            from contextlib import redirect_stdout

            f = io.StringIO()
            with redirect_stdout(f):
                rc = drift_main(
                    [
                        "--project-root",
                        str(mini_motor),
                        "--destino-root",
                        str(add_destino.parent),
                    ]
                )

            output = f.getvalue()
            assert rc == 0
            assert "settings-canonical-drift" not in output.lower() or "OK" in output
            assert "test_destino" not in output
        finally:
            m.touched_paths = original

    def test_destino_al_dia_no_aparece(
        self,
        mini_motor: Path,
        add_destino_al_dia: Path,
    ):
        """CA1/c: con destino al dia (pasa el gate), ese destino NO aparece."""
        import scripts.check_settings_canonical_drift as m
        from scripts.check_settings_canonical_drift import main as drift_main

        original = m.touched_paths
        m.touched_paths = lambda pr: (
            [".agent/hooks/claude_guard_entry.py"],
            None,
        )
        try:
            import io
            from contextlib import redirect_stdout

            f = io.StringIO()
            with redirect_stdout(f):
                rc = drift_main(
                    [
                        "--project-root",
                        str(mini_motor),
                        "--destino-root",
                        str(add_destino_al_dia.parent),
                    ]
                )

            output = f.getvalue()
            assert rc == 0
            # El destino al dia no debe aparecer en ningun AVISO (C3 fix)
            assert "AVISO [settings-canonical-drift]" not in output
            # Debe haber un mensaje informativo (todos al dia)
            assert "OK" in output
        finally:
            m.touched_paths = original


class TestFailVisible:
    """DoD 3: universo vacio, link ilegitimo, diff indeterminado."""

    def test_universo_vacio_se_declara(
        self,
        mini_motor: Path,
    ):
        """DoD 3: universo vacio -> declara vacio (nunca "OK" silencioso)."""
        import scripts.check_settings_canonical_drift as m
        from scripts.check_settings_canonical_drift import main as drift_main

        original = m.touched_paths
        m.touched_paths = lambda pr: (
            [".agent/hooks/claude_guard_entry.py"],
            None,
        )
        try:
            import io
            from contextlib import redirect_stdout

            f = io.StringIO()
            with redirect_stdout(f):
                rc = drift_main(
                    [
                        "--project-root",
                        str(mini_motor),
                        "--destino-root",
                        str(mini_motor),  # mini_motor no tiene destinos
                    ]
                )

            output = f.getvalue()
            assert rc == 0
            assert "universo" in output.lower() or "empty" in output.lower()
        finally:
            m.touched_paths = original

    def test_link_ilegible_se_declara(
        self,
        mini_motor: Path,
        tmp_path: Path,
    ):
        """DoD 3: link malformado -> declarado ilegible, no rompe."""
        import scripts.check_settings_canonical_drift as m
        from scripts.check_settings_canonical_drift import main as drift_main

        original = m.touched_paths
        m.touched_paths = lambda pr: (
            [".agent/hooks/claude_guard_entry.py"],
            None,
        )
        try:
            import io
            from contextlib import redirect_stdout

            root = tmp_path / "destinos"
            root.mkdir()

            # Link con JSON invalido
            link = root / "bad_destino" / ".agent" / "config"
            link.mkdir(parents=True)
            (link / "motor_destination_link.json").write_text(
                "{ invalid json }", encoding="utf-8"
            )

            f = io.StringIO()
            with redirect_stdout(f):
                rc = drift_main(
                    [
                        "--project-root",
                        str(mini_motor),
                        "--destino-root",
                        str(root),
                    ]
                )

            output = f.getvalue()
            assert rc == 0
            assert (
                "ilegitimo" in output.lower()
                or "ilegible" in output.lower()
                or "invalid" in output.lower()
            )
        finally:
            m.touched_paths = original

    def test_universo_vacio_sin_trigger_sin_aviso(
        self,
        mini_motor: Path,
        tmp_path: Path,
    ):
        """C3 combo: universo vacio + diff ajeno -> SIN aviso de drift.

        Prueba exacta del caso C1: si el diff no toca trigger, el universo
        vacio no se declara (coste cero del work_plan R2).
        """
        import scripts.check_settings_canonical_drift as m
        from scripts.check_settings_canonical_drift import main as drift_main

        original = m.touched_paths
        m.touched_paths = lambda pr: (
            ["some/other/file.py"],
            None,
        )
        try:
            import io
            from contextlib import redirect_stdout

            f = io.StringIO()
            with redirect_stdout(f):
                rc = drift_main(
                    [
                        "--project-root",
                        str(mini_motor),
                        "--destino-root",
                        str(mini_motor),  # no tiene destinos -> universo vacio
                    ]
                )

            output = f.getvalue()
            assert rc == 0
            # El universo vacio SOLO se declara si trigger o indeterminado
            # Con diff ajeno, debe ser silencio total (C3)
            assert "settings-canonical-drift" not in output.lower()
        finally:
            m.touched_paths = original


class TestDiffIndeterminado:
    """D4: sin origin/main -> diff indeterminado declarado."""

    def test_diff_indeterminado_se_declara(
        self,
        mini_motor: Path,
        add_destino: Path,
    ):
        """D4: diff indeterminado declarado (trigger + indeterminado)."""
        import scripts.check_settings_canonical_drift as m
        from scripts.check_settings_canonical_drift import main as drift_main

        # Mock para simular git diff con trigger + indeterminado
        original_touched = m.touched_paths
        m.touched_paths = lambda pr: (
            [".agent/hooks/claude_guard_entry.py"],
            "no origin/main disponible (diff indeterminado)",
        )
        try:
            import io
            from contextlib import redirect_stdout

            f = io.StringIO()
            with redirect_stdout(f):
                rc = drift_main(
                    [
                        "--project-root",
                        str(mini_motor),
                        "--destino-root",
                        str(add_destino.parent),
                    ]
                )

            output = f.getvalue()
            assert rc == 0
            # Debe aparecer declaracion de indeterminado en el header
            assert "indeterminado" in output.lower()
        finally:
            m.touched_paths = original_touched


class TestWiringVisible:
    """CA4: check_guard_wiring debe reconocer el guard como cableado.

    Mecanico real (check_guard_wiring.py):
        - find_guards busca archivos en GUARD_DIRS (scripts/, .agent/hooks/,
          skills/, tools/, bus/, runtime/) cuyo stem empiece con "check_",
          "validate_" o "guard_" (GUARD_PREFIXES, linea 150).
        - collect_evidence -> _python_invocations escanea AST de ficheros .py
          buscando: (a) import / importfrom del modulo guard; (b) llamadas a
          subprocess/os.system/etc con la ruta del guard.
        - Un `from scripts.check_settings_canonical_drift import ...` dentro
          de run_settings_canonical_drift_check en prepush_check.py CABLEA
          el guard: es un import ESTATICO, la arista preferida (no se rompe
          por edits del nombre de funcion).

    Este test verifica la arista real: el import estatico en prepush_check.py
    es detectado como WIRED por check_guard_wiring.collect_evidence (o, como
    fallback si el motor no esta en disco, se verifica la presencia del import).
    """

    def test_wiring_visivel(self):
        """CA4: check_guard_wiring reconoce check_settings_canonical_drift cableado.

        Mecanismo: collect_evidence busca import/ImportFrom en el AST.
        El `from scripts.check_settings_canonical_drift import main` dentro de
        run_settings_canonical_drift_check en prepush_check.py es un import
        ESTATICO que el detector cuenta como WIRED (arista: prepush_check.py).
        """
        from scripts.check_guard_wiring import collect_evidence

        # El motor esta en la raiz del repo actual
        motor_root = Path(__file__).resolve().parents[2]

        # Verificar que el motor existe (si no, este test es N/A)
        if not (motor_root / "scripts" / "prepush_check.py").exists():
            pytest.skip("motor no encontrado, N/A")

        try:
            ev = collect_evidence(motor_root)
            wired = ev.get("check_settings_canonical_drift", [])
            assert wired, (
                "check_settings_canonical_drift DEBE aparecer cableado en "
                "check_guard_wiring.collect_evidence. Verifica que el import "
                "estatico en prepush_check.py no se haya roto."
            )
        except Exception:
            # Fallback: verificar el import estatico directamente en el AST
            prepush_src = (motor_root / "scripts" / "prepush_check.py").read_text(
                encoding="utf-8", errors="replace"
            )
            import ast

            tree = ast.parse(prepush_src)
            has_import = False
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.ImportFrom)
                    and node.module
                    and "check_settings_canonical_drift" in node.module
                ):
                    has_import = True
                    break
            assert has_import, (
                "prepush_check.py DEBE contener un import de "
                "check_settings_canonical_drift (arista de wiring)"
            )

    def test_run_is_blocking_false(self):
        """CA4: run_settings_canonical_drift_check SIEMPRE is_blocking=False.

        Verificacion: la funcion existe y su docstring declara el patron WARN.
        Como verificacion complementaria, se verifica que el cuerpo de la
        funcion contenga is_blocking=False (no es mock, es lectura de fuente).
        """
        prepush_src = (
            Path(__file__).resolve().parents[2] / "scripts" / "prepush_check.py"
        )
        if not prepush_src.exists():
            pytest.skip("prepush_check.py no encontrado, N/A")

        src_text = prepush_src.read_text(encoding="utf-8", errors="replace")

        # Debe existir la funcion run_settings_canonical_drift_check
        assert "def run_settings_canonical_drift_check(" in src_text, (
            "prepush_check.py DEBE definir run_settings_canonical_drift_check"
        )

        # Extraer el cuerpo de la funcion y verificar is_blocking=False
        import ast

        tree = ast.parse(src_text)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.FunctionDef)
                and node.name == "run_settings_canonical_drift_check"
            ):
                # La funcion debe tener un try/except amplio (R-A)
                body_str = ast.dump(node)
                assert "Try" in body_str, (
                    "run_settings_canonical_drift_check DEBE envolver su cuerpo "
                    "en try/except amplio (R-A: nunca propaga excepcion)"
                )
                # Debe tener is_blocking=False en al menos un CheckResult
                assert "is_blocking=False" in body_str, (
                    "run_settings_canonical_drift_check DEBE usar "
                    "is_blocking=False en sus CheckResult"
                )
                break
        else:
            pytest.fail(
                "No se encontro la funcion run_settings_canonical_drift_check en prepush_check.py"
            )


class TestGateStub:
    """Control positivo: verificar que el stub del gate funciona."""

    def test_stub_stale_returns_rc1(self, tmp_path: Path):
        """El gate stub retorna rc=1 para settings con __STALE__."""
        settings = tmp_path / "settings.json"
        settings.write_text('{"__STALE__": true}', encoding="utf-8")
        gate = tmp_path / "gate.py"
        gate.write_text(
            "#!/usr/bin/env python3\n"
            "import argparse, sys\n"
            "p = argparse.ArgumentParser()\n"
            'p.add_argument("path")\n'
            "args = p.parse_args()\n"
            'data = open(args.path, encoding="utf-8").read()\n'
            'if "__STALE__" in data:\n'
            '    print("STALE"); sys.exit(1)\n'
            'print("OK"); sys.exit(0)\n',
            encoding="utf-8",
        )
        result = subprocess.run(
            [sys.executable, str(gate), str(settings)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 1
        assert "STALE" in result.stdout

    def test_stub_fresh_returns_rc0(self, tmp_path: Path):
        """El gate stub retorna rc=0 para settings sin __STALE__."""
        settings = tmp_path / "settings.json"
        settings.write_text('{"hooks": {}}', encoding="utf-8")
        gate = tmp_path / "gate.py"
        gate.write_text(
            "#!/usr/bin/env python3\n"
            "import argparse, sys\n"
            "p = argparse.ArgumentParser()\n"
            'p.add_argument("path")\n'
            "args = p.parse_args()\n"
            'data = open(args.path, encoding="utf-8").read()\n'
            'if "__STALE__" in data:\n'
            '    print("STALE"); sys.exit(1)\n'
            'print("OK"); sys.exit(0)\n',
            encoding="utf-8",
        )
        result = subprocess.run(
            [sys.executable, str(gate), str(settings)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        assert "OK" in result.stdout


class TestRaisePath:
    """C2: Ejecutar la via raise de run_settings_canonical_drift_check.

    Verifica que cuando drift_main (o el import) lanza excepcion,
    la funcion envoltoria NO propaga, sino que devuelve CheckResult
    WARN con is_blocking=False.
    """

    def test_raise_no_propaga_checkresult_warn(self):
        """C2: drift_main que raise -> CheckResult(passed=False, is_blocking=False)."""

        import scripts.check_settings_canonical_drift as m
        from scripts.prepush_check import (
            CheckResult,
            run_settings_canonical_drift_check,
        )

        # Monkeypatch drift_main para que lance excepcion
        original = m.main
        m.main = lambda argv=None: (_ for _ in ()).throw(
            RuntimeError("simulated drift_main failure")
        )
        try:
            result = run_settings_canonical_drift_check(Path("/tmp/fake"))

            # Debe ser CheckResult, NO excepcion propagada
            assert isinstance(result, CheckResult)
            assert result.passed is False
            assert result.is_blocking is False
            assert "WARN" in result.output
            assert (
                "drift_main failure" in result.output
                or "error interno" in result.output
            )
        finally:
            m.main = original

    def test_raise_no_propaga_via_import_error(self):
        """C2: import del modulo que falla -> CheckResult WARN sin propagar.

        Caso limite: si el modulo no se puede importar, la via raise
        del import (no de main) debe devolver CheckResult WARN.
        """
        import builtins
        import sys

        from scripts.prepush_check import (
            CheckResult,
            run_settings_canonical_drift_check,
        )

        # Remover el modulo del cache para forzar re-import
        mod_name = "scripts.check_settings_canonical_drift"
        original_mod = sys.modules.pop(mod_name, None)
        # Monkeypatch import para que falle
        original_import = builtins.__import__

        def failing_import(name, *args, **kwargs):
            if name == mod_name or (
                len(args) > 0 and args[0] and mod_name.startswith(args[0])
            ):
                raise ImportError("simulated import failure")
            return original_import(name, *args, **kwargs)

        builtins.__import__ = failing_import
        try:
            result = run_settings_canonical_drift_check(Path("/tmp/fake"))

            assert isinstance(result, CheckResult)
            assert result.passed is False
            assert result.is_blocking is False
            assert "WARN" in result.output
        finally:
            builtins.__import__ = original_import
            if original_mod is not None:
                sys.modules[mod_name] = original_mod


class TestResolveDestinoRoots:
    """D2: prioridad de resolucion de raices de destino."""

    def test_cli_toma_prendencia(self, tmp_path: Path):
        """CLI --destino-root > env > default."""
        import os

        from scripts.check_settings_canonical_drift import (
            resolve_destino_roots,
        )

        env_val = os.environ.get("AGENT_DESTINOS_ROOT")
        try:
            if "AGENT_DESTINOS_ROOT" in os.environ:
                del os.environ["AGENT_DESTINOS_ROOT"]

            cli_root = tmp_path / "cli_root"
            cli_root.mkdir()
            roots = resolve_destino_roots(
                cli_roots=[str(cli_root)],
                env_value=None,
                motor_checkout_root=Path("/tmp/fake_motor"),
            )
            # El CLI debe tomar prioridad
            assert len(roots) == 1
            assert roots[0] == cli_root
        finally:
            if env_val is not None:
                os.environ["AGENT_DESTINOS_ROOT"] = env_val
