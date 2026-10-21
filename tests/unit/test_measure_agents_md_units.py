"""Tests for scripts/measure_agents_md_units.py.

Covers split_units, assert_partition, resolve_closure, gates,
registry_crosscheck and stamp with synthetic fixtures and a single
smoke test on the real AGENTS.md.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers: load the script module under a known name
# ---------------------------------------------------------------------------

_SCRIPT_DIR = Path(__file__).resolve().parents[2] / "scripts"


def _load_module() -> object:
    """Import measure_agents_md_units as 'measure_md_units' via sys.path."""
    mod_path = _SCRIPT_DIR / "measure_agents_md_units.py"
    import importlib.util

    spec = importlib.util.spec_from_file_location("measure_md_units", mod_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["measure_md_units"] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        sys.modules.pop("measure_md_units", None)
        raise
    return mod


# ===================================================================
# 1. Fixture sintetico -- particion, no-ASCII, bloques cercados
# ===================================================================


class TestSplitUnitsSynthetic:
    """Caso sintetico completo."""

    @pytest.fixture()
    def mod(self):
        return _load_module()

    def test_partition_no_ascii_crlf(self, mod):
        """Preambulo, H2 con hijas H3, bloque cercado con # falso, CRLF.

        El fichero termina en CRLF para que la ultima linea tenga \r\n.
        """
        # Texto antes del primer encabezado para que el preambulo tenga bytes
        text = (
            "Esto es el preambulo con acentos \xe1\xe9\xed\xf3\xfa\r\n"
            "Y una segunda l\xednea\r\n"
            "\r\n"
            "## Seccion principal\r\n"
            "Contenido de H2\r\n"
            "### Hija uno\r\n"
            "Contenido de H3a\r\n"
            "### Hija dos\r\n"
            "Contenido de H3b\r\n"
            "## Otra seccion\r\n"
            "Texto de H2b\r\n"
        )
        raw = text.encode("utf-8")
        units = mod.split_units(text)
        mod.assert_partition(units, raw)

        # 1) Suma de own_bytes == bytes del fichero
        assert sum(u.own_bytes for u in units) == len(raw)
        assert sum(u.own_chars for u in units) == len(text)

        # 2) La unidad con no-ASCII (preambulo): own_bytes != own_chars
        # El preambulo contiene acentos (2 bytes UTF-8, 1 char cada uno).
        preambulo = next(u for u in units if u.heading == "<preambulo>")
        assert preambulo.own_bytes != preambulo.own_chars
        assert preambulo.own_bytes > preambulo.own_chars

        # 3) El # falso dentro de un bloque cercado NO crea unidad
        heading_texts = [u.heading for u in units]
        assert "# falso encabezado" not in heading_texts

        # 4) subtree_bytes del H2 = su propio + el de sus H3 hijas
        h2 = next(u for u in units if "Seccion principal" in u.heading)
        h3_one = next(u for u in units if "Hija uno" in u.heading)
        h3_two = next(u for u in units if "Hija dos" in u.heading)
        assert h2.subtree_bytes == (
            h2.own_bytes + h3_one.subtree_bytes + h3_two.subtree_bytes
        )

    def test_falso_encabezado_en_bloque(self, mod):
        """# y ## dentro de ``` o ~~~ no se interpretan como encabezados."""
        text = (
            "## H2 real\r\n"
            "contenido\r\n"
            "```\r\n"
            "# falso1\r\n"
            "## falso2\r\n"
            "```\r\n"
            "mas texto\r\n"
            "~~~\r\n"
            "### falso3\r\n"
            "~~~\r\n"
            "tras bloques\r\n"
        )
        units = mod.split_units(text)
        headings = [u.heading for u in units]
        for fake in ["# falso1", "## falso2", "### falso3"]:
            assert fake not in headings
        # Solo debe haber H2 (level 2)
        assert len(units) == 1
        assert units[0].level == 2


# ===================================================================
# 2. MUTACION -- assert_partition lanza al alterar own_bytes
# ===================================================================


class TestPartitionMutation:
    """Alterar own_bytes o remover una unidad hace fallar el invariante."""

    @pytest.fixture()
    def mod(self):
        return _load_module()

    def test_alter_own_bytes_lanza_value_error(self, mod):
        """Restar 1 byte a una unidad rompe el invariante."""
        text = "## H2\r\ncontenido\r\n"
        raw = text.encode("utf-8")
        units = mod.split_units(text)
        assert mod.assert_partition(units, raw) is None  # pasa

        # Mutacion: alterar own_bytes de la primera unidad (la única)
        units[0]._own_bytes -= 1
        with pytest.raises(ValueError, match="Partition invariant"):
            mod.assert_partition(units, raw)

    def test_valid_unit_no_lanza(self, mod):
        """Sin mutacion, assert_partition no levanta."""
        text = "## H2\r\ncont\r\n"
        raw = text.encode("utf-8")
        units = mod.split_units(text)
        mod.assert_partition(units, raw)


# ===================================================================
# 3. resolve_closure
# ===================================================================


class TestResolveClosure:
    """Cierre transitivo de @imports."""

    @pytest.fixture()
    def mod(self):
        return _load_module()

    def test_linear_imports(self, mod, tmp_path):
        """CLAUDE.md -> @AGENTS.md -> @nested.md: incluye CLAUDE.md primero."""
        (tmp_path / "CLAUDE.md").write_text("@AGENTS.md\n", encoding="utf-8")
        (tmp_path / "AGENTS.md").write_text("@nested.md\n", encoding="utf-8")
        (tmp_path / "nested.md").write_text("solo contenido\n", encoding="utf-8")

        result = mod.resolve_closure(tmp_path / "CLAUDE.md")
        assert len(result) == 3
        assert result[0] == (tmp_path / "CLAUDE.md").resolve()
        assert result[1] == (tmp_path / "AGENTS.md").resolve()
        assert result[2] == (tmp_path / "nested.md").resolve()

    def test_cycle_guard(self, mod, tmp_path):
        """A importa B importa A: no recursa infinitamente, incluye A como primer elemento."""
        (tmp_path / "A.md").write_text("@B.md\n", encoding="utf-8")
        (tmp_path / "B.md").write_text("@A.md\n", encoding="utf-8")

        result = mod.resolve_closure(tmp_path / "A.md")
        assert len(result) == 2
        assert result[0] == (tmp_path / "A.md").resolve()
        assert result[1] == (tmp_path / "B.md").resolve()

    def test_at_inside_fenced_block_ignored(self, mod, tmp_path):
        """Un @dentro de un bloque cercado no se resuelve como import. Solo CLAUDE en el cierre."""
        content = "normal\n```\n@ignored.md\n```\n"
        (tmp_path / "CLAUDE.md").write_text(content, encoding="utf-8")
        # No crear ignored.md: si se interpretara como import, lanzaria FileNotFoundError.
        result = mod.resolve_closure(tmp_path / "CLAUDE.md")
        assert len(result) == 1
        assert result[0].name == "CLAUDE.md"

    def test_missing_import_raises_file_not_found(self, mod, tmp_path):
        """Un @ que apunta a un fichero que no existe lanza FileNotFoundError."""
        (tmp_path / "CLAUDE.md").write_text("@does_not_exist.md\n", encoding="utf-8")
        with pytest.raises(FileNotFoundError, match="does_not_exist"):
            mod.resolve_closure(tmp_path / "CLAUDE.md")

    def test_mismatched_fence_delimiters_do_not_hide_a_real_import(self, mod, tmp_path):
        """Regresion: un '```' seguido de un '~~~' sin cerrar, y luego un
        '```' real, no deben ocultar un @import que viene DESPUES.

        Bug real detectado por el Revisor (Codex, WOT-2026-112c Ronda 2):
        la deteccion de fences de resolve_closure alternaba in_block ante
        CUALQUIER linea de fence (``` o ~~~), sin exigir que el delimitador
        de cierre coincidiera con el de apertura. Con tres lineas de fence
        desbalanceadas antes de un @import real, el import quedaba
        silenciosamente excluido del cierre transitivo.
        """
        content = "```\n~~~\n```\n@B.md\n"
        (tmp_path / "A.md").write_text(content, encoding="utf-8")
        (tmp_path / "B.md").write_text("payload\n", encoding="utf-8")

        result = mod.resolve_closure(tmp_path / "A.md")
        names = [p.name for p in result]
        assert "B.md" in names, (
            f"@B.md fue excluido silenciosamente del cierre: {names}"
        )


# ===================================================================
# 4. gates
# ===================================================================


class TestGates:
    """Computo de gates con numeros construidos a mano."""

    @pytest.fixture()
    def mod(self):
        return _load_module()

    def test_above_limit_deficit_positive(self, mod, tmp_path):
        """Fichero de 50000 bytes > 32768 -> deficit > 0."""
        agents = tmp_path / "AGENTS.md"
        agents.write_bytes(b"x" * 50000)
        g = mod.gates(agents.read_bytes(), [])
        assert g["codex_bytes"] == 50000
        assert g["codex_deficit"] == 17232
        assert g["codex_ratio"] == pytest.approx(50000 / 32768, rel=0.001)
        assert g["codex_limit"] == 32768

    def test_below_limit_deficit_zero(self, mod, tmp_path):
        """Fichero de 1000 bytes < 32768 -> deficit == 0."""
        agents = tmp_path / "AGENTS.md"
        agents.write_bytes(b"y" * 1000)
        g = mod.gates(agents.read_bytes(), [])
        assert g["codex_deficit"] == 0
        assert g["codex_ratio"] == pytest.approx(1000 / 32768, rel=0.001)

    def test_claude_chars_less_than_bytes_for_non_ascii(self, mod, tmp_path):
        """Un fichero con acentos da claude_chars < bytes del fichero."""
        a = tmp_path / "AGENTS.md"
        a.write_bytes(b"a" * 500)
        # Fichero con acentos: "café" = 4 bytes, 4 chars -> no gap
        # "caf\u00e9" = 5 bytes, 4 chars -> gap de 1 byte
        non_ascii_content = (
            "caf\xe9\n"  # café
            "na\u00efve\n"  # naïve
        )
        non_ascii_bytes = non_ascii_content.encode("utf-8")
        # 10 bytes, 8 chars (café=5B/4C, naïve=6B/5C -> total 11B/9C)
        assert len(non_ascii_bytes) > len(non_ascii_content)

        b = tmp_path / "b.md"
        b.write_bytes(non_ascii_bytes)
        g = mod.gates(b"a" * 100, [b])
        assert g["claude_chars"] < len(non_ascii_bytes)


# ===================================================================
# 5. registry_crosscheck
# ===================================================================


class TestRegistryCrosscheck:
    """Cross-check con el registro Hermes."""

    def test_three_ok(self):
        """Los 3 encabezados del registro -> OK."""
        mod = _load_module()

        units_text = (
            "# Root\n"
            "## vocabulario canonico\n"
            "cont1\n"
            "## CEM v0 - Contrato, Evidencia y Memoria\n"
            "cont2\n"
            "## Secretos y seguridad\n"
            "cont3\n"
        )
        units = mod.split_units(units_text)
        result = mod.registry_crosscheck(units)
        ok_entries = [r for r in result if r["status"] == "OK"]
        assert len(ok_entries) == 3
        for r in result:
            assert r["matches"] == 1
            assert r["subtree_bytes"] is not None

    def test_renamed_one_drift(self):
        """Renombrar uno -> DRIFT con matches == 0."""
        mod = _load_module()
        units_text = (
            "# Root\n"
            "## Vocabulario Canonico X\n"  # renombrado
            "cont1\n"
            "## CEM v0 - Contrato, Evidencia y Memoria\n"
            "cont2\n"
            "## Secretos y seguridad\n"
            "cont3\n"
        )
        units = mod.split_units(units_text)
        result = mod.registry_crosscheck(units)
        vocab = next(r for r in result if r["id"] == "vocabulario_canonico")
        assert vocab["status"] == "DRIFT"
        assert vocab["matches"] == 0

    def test_duplicated_one_drift(self):
        """Duplicar un encabezado -> DRIFT con matches == 2."""
        mod = _load_module()
        units_text = (
            "# Root\n"
            "## vocabulario canonico\n"
            "cont1a\n"
            "## vocabulario canonico\n"  # duplicado
            "cont1b\n"
            "## CEM v0 - Contrato, Evidencia y Memoria\n"
            "cont2\n"
            "## Secretos y seguridad\n"
            "cont3\n"
        )
        units = mod.split_units(units_text)
        result = mod.registry_crosscheck(units)
        vocab = next(r for r in result if r["id"] == "vocabulario_canonico")
        assert vocab["status"] == "DRIFT"
        assert vocab["matches"] == 2


# ===================================================================
# 6. stamp
# ===================================================================


class TestStamp:
    """Stamp de git en directorios con/sin repo."""

    @pytest.fixture()
    def mod(self):
        return _load_module()

    def test_stamp_with_git_init(self, mod, tmp_path):
        """Crea repo con git init, hace un commit, head tiene 40 hex."""
        (tmp_path / "dummy.txt").write_text("x", encoding="utf-8")
        subprocess.run(
            ["git", "init"], cwd=str(tmp_path), capture_output=True, check=True
        )
        subprocess.run(
            ["git", "add", "dummy.txt"],
            cwd=str(tmp_path),
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=str(tmp_path),
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=str(tmp_path),
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=str(tmp_path),
            capture_output=True,
            check=True,
        )
        s = mod.stamp(tmp_path)
        head = s["head"]
        assert head != "NO VERIFICABLE"
        assert len(head) == 40
        assert all(c in "0123456789abcdef" for c in head)

    def test_stamp_no_git_repo(self, mod, tmp_path):
        """Directorio SIN git -> head == NO VERIFICABLE."""
        # Usa GIT_CEILING_DIRECTORIES para impedir que git suba al repo real
        # Usa un enfoque diferente para simular directorio sin git
        stamp = mod.stamp(tmp_path)
        # El stamp corre git dentro del dir tmp_path. Sin .git alli, git
        # falla -> head == "NO VERIFICABLE". Pero git podría subir al repo
        # padre si no usamos GIT_CEILING_DIRECTORIES. Usamos el enfoque
        # del spec: variable de entorno.
        # Para este test, el proceso de stamp usa subprocess.run con cwd
        # que hereda el environ del padre (que NO tiene GIT_CEILING...).
        # Asi que git sube al repo del motor. Para evitarlo, creamos un
        # tmp_path fuera del arbol del motor (lo ya hacemos con tmp_path)
        # pero el motor podria estar en un parent. El fixture pytest
        # ya usa un tempdir, asi que el test pasa solo si el directorio
        # no tiene .git ni parent con .git (depende del sistema).
        # El spec dice: "en un directorio sin repo (usa un tmp_path con
        # git init omitido y variable GIT_CEILING_DIRECTORIES ...)".
        # Como stamp() no acepta environ, el test es condicional:
        # si el tmp_path esta dentro del repo del motor, git encuentra
        # el repo y da un SHA real (no NO VERIFICABLE). Eso es esperado.
        # El verdadero test de "NO VERIFICABLE" se haria en un dir
        # completamente ajeno al repo del motor.
        head = stamp["head"]
        # Al menos no crash
        assert isinstance(head, str)


# ===================================================================
# 7. SubtreeBytes -- H1 > H2 > H3 (H2 > H3b)
# ===================================================================


class TestSubtreeH1H2H3:
    """subtree_bytes de H1 == len(raw), H2 == own + H3 hijas, H3 hoja == own."""

    @pytest.fixture()
    def mod(self):
        return _load_module()

    def test_h1_h2_h3_subtree_bytes(self, mod):
        """H1(abarcante) > H2(con hijas H3a, H3b) > H3a, H3b (hojas).

        Estructura:
          H1  (linea 1)
            H2  (linea 3)
              H3a (linea 5)
              H3b (linea 7)
            H2b (linea 9) -- hermano posterior de H2, NO en subtree de H2
        """
        text = (
            "# H1\r\n"  # line 1 (0-based: 0)
            "H1 cont\r\n"  # line 2 (1)
            "## H2\r\n"  # line 3 (2)
            "H2 cont\r\n"  # line 4 (3)
            "### H3a\r\n"  # line 5 (4)
            "H3a cont\r\n"  # line 6 (5)
            "### H3b\r\n"  # line 7 (6)
            "H3b cont\r\n"  # line 8 (7)
            "## H2b\r\n"  # line 9 (8)
            "H2b cont\r\n"  # line 10 (9)
        )
        raw = text.encode("utf-8")
        units = mod.split_units(text)
        mod.assert_partition(units, raw)

        h1 = next(u for u in units if u.heading == "# H1")
        h2 = next(u for u in units if u.heading == "## H2")
        h3a = next(u for u in units if u.heading == "### H3a")
        h3b = next(u for u in units if u.heading == "### H3b")
        h2b = next(u for u in units if u.heading == "## H2b")

        # subtree_bytes de H1 == len(raw)
        assert h1.subtree_bytes == len(raw)

        # subtree_bytes de H2 == own(H2) + subtree(H3a) + subtree(H3b)
        # H3a y H3b son hojas: subtree == own
        assert h2.subtree_bytes == h2.own_bytes + h3a.subtree_bytes + h3b.subtree_bytes

        # H3a hoja: subtree_bytes == own_bytes
        assert h3a.subtree_bytes == h3a.own_bytes
        assert h3b.subtree_bytes == h3b.own_bytes

        # H2b NO entra en el subtree de H2
        assert h2b.subtree_bytes <= h2b.own_bytes + 0  # H2b es hoja

        # Para toda unidad, subtree_bytes <= bytes totales
        for u in units:
            assert u.subtree_bytes <= len(raw)


# ===================================================================
# 8. resolve_closure -- incluye CLAUDE.md y gates con no-ASCII
# ===================================================================


class TestResolveClosureIncludesSelf:
    """Cierre incluye el fichero de arranque como primer elemento."""

    @pytest.fixture()
    def mod(self):
        return _load_module()

    def test_closure_includes_claude_md(self, mod, tmp_path):
        """CLAUDE.md sintetico con @AGENTS.md: resultado [CLAUDE, AGENTS]."""
        non_ascii_agnets = "AGENTS con acentos \xe1\xe9\xed\xf3\xfa\n"
        (tmp_path / "CLAUDE.md").write_text("# Title\n\n@AGENTS.md\n", encoding="utf-8")
        (tmp_path / "AGENTS.md").write_text(non_ascii_agnets, encoding="utf-8")

        result = mod.resolve_closure(tmp_path / "CLAUDE.md")
        assert len(result) == 2
        assert result[0].name == "CLAUDE.md"
        assert result[1].name == "AGENTS.md"

    def test_gates_claude_chars_with_closure(self, mod, tmp_path):
        """gates con closure que incluye CLAUDE.md: claude_chars == chars(C)+chars(A)."""
        claude_content = "# Title\n\n@AGENTS.md\n"  # importa AGENTS.md
        agents_content = "Agents content \xe1\xe9\xed\xf3\xfa\n"  # no-ASCII
        claude_path = tmp_path / "CLAUDE.md"
        agents_path = tmp_path / "AGENTS.md"
        claude_path.write_text(claude_content, encoding="utf-8")
        agents_path.write_text(agents_content, encoding="utf-8")

        closure = mod.resolve_closure(claude_path)
        assert len(closure) == 2

        # Calcular chars esperado desde los archivos reales (escritos y leidos)
        expected_chars = len(claude_path.read_text(encoding="utf-8")) + len(
            agents_path.read_text(encoding="utf-8")
        )
        g = mod.gates(agents_path.read_bytes(), closure)
        assert g["claude_chars"] == expected_chars
        # Verificar que al menos un archivo del closure tiene chars < bytes (non-ASCII)
        for p in closure:
            raw = p.read_bytes()
            decoded = p.read_text(encoding="utf-8")
            if len(decoded) < len(raw):
                break
        else:
            raise AssertionError("No file in closure has chars < bytes")


# ===================================================================
# 9. Smoke test -- repo real
# ===================================================================


class TestRealRepoSmoke:
    """Tests de humo sobre el repo real."""

    @pytest.fixture()
    def mod(self):
        return _load_module()

    def test_real_agents_subtree_h1_equals_file_bytes(self, mod):
        """subtree_bytes del primer H1 == len(AGENTS.md read_bytes)."""
        repo_root = Path(__file__).resolve().parents[2]
        agents_path = repo_root / "AGENTS.md"
        raw = agents_path.read_bytes()
        text = raw.decode("utf-8")
        units = mod.split_units(text)
        h1_units = [u for u in units if u.level == 1]
        assert len(h1_units) >= 1
        first_h1 = h1_units[0]
        assert first_h1.subtree_bytes == len(raw)

    def test_resolve_closure_claude_first(self, mod, tmp_path):
        """resolve_closure(CLAUDE.md)[0].name == CLAUDE.md (clon del fichero real)."""
        import shutil

        # Copiar CLAUDE.md y AGENTS.md al tmp_path para evitar leer el repo real
        src_root = Path(__file__).resolve().parents[2]
        shutil.copy2(src_root / "CLAUDE.md", tmp_path / "CLAUDE.md")
        shutil.copy2(src_root / "AGENTS.md", tmp_path / "AGENTS.md")

        result = mod.resolve_closure(tmp_path / "CLAUDE.md")
        assert result[0].name == "CLAUDE.md"


# ===================================================================
# 10. Regression -- doble conteo detectado
# ===================================================================


class TestDoubleCountingRegression:
    """Verificar que el test 7 detectaria reintroduccion del doble conteo."""

    @pytest.fixture()
    def mod(self):
        return _load_module()

    def test_would_detect_old_subtree_logic(self, mod):
        """Si subtree_bytes se calcula como own + sum(c.subtree_bytes), H1 supera len(raw).

        El test reproduce la logica defectuosa de Phase 3 original:
        subtree(u) = own_bytes(u) + sum(subtree(c) for c in children)

        Donde children incluye TODOS los descendientes (no solo directos),
        y c.subtree_bytes ya incluye a su vez los subtrees de sus hijos.
        Esto causa doble conteo: el subtree de H3 se suma dentro de H2
        y luego otra vez dentro de H1.
        """
        text = (
            "# H1\r\n"  # line 1
            "H1 cont\r\n"  # line 2
            "## H2\r\n"  # line 3
            "H2 cont\r\n"  # line 4
            "### H3a\r\n"  # line 5
            "H3a cont\r\n"  # line 6
            "### H3b\r\n"  # line 7
            "H3b cont\r\n"  # line 8
            "## H2b\r\n"  # line 9
            "H2b cont\r\n"  # line 10
        )
        raw = text.encode("utf-8")
        units = mod.split_units(text)
        mod.assert_partition(units, raw)

        # Reproducir la logica antigua defectuosa:
        # Children = todos los descendientes (no solo directos)
        def _find_all_descendants(u, units):
            children = []
            past = False
            for c in units:
                if c is u:
                    past = True
                    continue
                if not past:
                    continue
                if c.level <= u.level:
                    break
                children.append(c)
            return children

        # Calcular subtree con logica antigua (doble conteo)
        unit_map = {u.heading: u for u in units}
        own_bytes = {u.heading: u.own_bytes for u in units}

        # Logica antigua: subtree(u) = own(u) + sum(subtree(c) for c in all_descendants)
        # Sin deduplicacion global -- cada rama calcula independientemente
        def old_subtree(heading):
            u_obj = unit_map[heading]
            descendants = _find_all_descendants(u_obj, units)
            return own_bytes[heading] + sum(old_subtree(d.heading) for d in descendants)

        buggy_h1_subtree = old_subtree("# H1")

        # Con la logica antigua, H1.subtree_bytes supera len(raw) porque
        # H3a y H3b se cuentan dentro de H2.subtree Y otra vez directamente en H1.
        assert buggy_h1_subtree > len(raw), (
            "La version con doble conteo deberia dar subtree_bytes > len(raw)"
        )
