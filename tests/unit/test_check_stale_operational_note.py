"""Tests del guard de notas operativas caducables (WOT-2026-026t DoD-c).

La barrera que prueban: una nota normativa que PROHIBE una via PORQUE FALLA es
una premisa disfrazada de orden y caduca sola; debe llevar marca de frescura.

Cada test ejerce la funcion real sobre ficheros reales en tmp_path. El caso
fundacional (`test_caza_la_nota_historica_de_026t`) usa la nota LITERAL que
causo el defecto medido.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


_MODULE_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "check_stale_operational_note.py"
)
_spec = importlib.util.spec_from_file_location(
    "check_stale_operational_note", _MODULE_PATH
)
assert _spec is not None and _spec.loader is not None
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)


def _write(tmp_path: Path, text: str) -> Path:
    target = tmp_path / "nota.md"
    target.write_text(text, encoding="utf-8")
    return target


class TestNotaHistorica:
    """El caso que origino el ticket."""

    def test_caza_la_nota_historica_de_026t(self, tmp_path: Path) -> None:
        """La nota LITERAL del defecto medido debe salir en rojo."""
        path = _write(
            tmp_path,
            "Lanza el bucle POR LA PRIMITIVA send_to_profile\n"
            "(NO uses `ensemble_dispatch.py run`: cuelga).\n",
        )
        violations = guard.scan_file(path)
        assert len(violations) == 1
        assert "ensemble_dispatch.py run" in violations[0]

    def test_la_misma_nota_fechada_pasa(self, tmp_path: Path) -> None:
        """Mutation inversa: anadir la fecha la vuelve aceptable."""
        path = _write(
            tmp_path,
            "Lanza el bucle POR LA PRIMITIVA send_to_profile\n"
            "(NO uses `ensemble_dispatch.py run`: cuelga -- medido 2026-07-21).\n",
        )
        assert guard.scan_file(path) == []


class TestMarcasDeFrescura:
    """Las tres formas de marca aceptadas, uno por forma."""

    @pytest.mark.parametrize(
        "marca",
        [
            "medido 2026-07-21",
            "commit: a1aaaa2",
            "re-verificar con el probe del ticket",
        ],
    )
    def test_cada_forma_de_marca_satisface_el_guard(
        self, tmp_path: Path, marca: str
    ) -> None:
        path = _write(tmp_path, f"NO uses `foo.py run`: cuelga ({marca}).\n")
        assert guard.scan_file(path) == []

    def test_marca_en_linea_siguiente_cuenta(self, tmp_path: Path) -> None:
        """La nota puede partirse por ancho de linea; la ventana lo cubre."""
        path = _write(
            tmp_path,
            "NO uses `foo.py run`: cuelga\n"
            "  (verificado el 2026-07-21 sobre el HEAD de entonces).\n",
        )
        assert guard.scan_file(path) == []

    def test_marca_demasiado_lejos_no_cuenta(self, tmp_path: Path) -> None:
        """Una fecha a 5 lineas no es la marca de ESTA nota."""
        path = _write(
            tmp_path,
            "NO uses `foo.py run`: cuelga\n\n\n\n\nOtra seccion, 2026-07-21.\n",
        )
        assert len(guard.scan_file(path)) == 1


class TestNoMuerdeProsaLegitima:
    """El alcance es estrecho a proposito (leccion 024u -> 025c)."""

    @pytest.mark.parametrize(
        "linea",
        [
            # Prohibicion SIN motivo de fallo: es politica, no premisa caducable.
            "NO uses `git add -A`: fichero a fichero.",
            # Motivo de fallo SIN prohibicion: es diagnostico.
            "El worktree detached `principal` cuelga de ningun branch.",
            # Prohibicion + fallo pero SIN referencia de codigo: prosa generica.
            "NO uses rutas absolutas porque rompe la portabilidad.",
            # Recomendacion positiva.
            "Usa `ensemble_dispatch.py loop-round` como ruta canonica.",
        ],
    )
    def test_no_dispara(self, tmp_path: Path, linea: str) -> None:
        assert guard.scan_file(_write(tmp_path, linea + "\n")) == []


class TestFailClosed:
    """Un fichero ilegible es violacion, no silencio."""

    def test_fichero_ilegible_es_violacion(self, tmp_path: Path) -> None:
        path = tmp_path / "roto.md"
        path.write_bytes(b"\xff\xfe\x00 invalid utf8 \xc3\x28")
        violations = guard.scan_file(path)
        assert len(violations) == 1
        assert "no se puede leer" in violations[0]


class TestCollectFiles:
    """El universo son las superficies normativas."""

    def test_recorre_subdirectorios(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """prompts/_shared/ debe entrar (un glob *.md no recursivo lo perderia)."""
        (tmp_path / "prompts" / "_shared").mkdir(parents=True)
        (tmp_path / "prompts" / "raiz.md").write_text("x", encoding="utf-8")
        (tmp_path / "prompts" / "_shared" / "anidado.md").write_text(
            "y", encoding="utf-8"
        )
        monkeypatch.setattr(guard, "PROJECT_ROOT", tmp_path)
        names = {p.name for p in guard.collect_files(tmp_path)}
        assert names == {"raiz.md", "anidado.md"}

    def test_directorio_ausente_no_rompe(self, tmp_path: Path) -> None:
        assert guard.collect_files(tmp_path) == []
