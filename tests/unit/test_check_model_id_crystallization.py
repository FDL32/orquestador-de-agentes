"""Tests del guard de cristalizacion de identidad de modelo (WOT-2026-022a).

Cobertura del DoD (e): 4 clases del patron -- (i) variante/version explicita
(bloquea), (ii) contexto `(1M context)` (bloquea), (iii) trailer humano (pasa),
(iv) trailer generico sin discriminante (pasa). La mutation (c)/(d) se prueban
con trailer modelo vs borde adjudicado (marca base sin discriminante).
"""

from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from check_model_id_crystallization import (
    crystallization_issues,
    main,
)


# --------------------------------------------------------------------------
# Clase (i): variante/version explicita -> BLOQUEA
# --------------------------------------------------------------------------


def test_blocks_model_variant_literal(tmp_path):
    """`Claude Opus 5 <noreply@anthropic.com>` es cristalizacion -> bloquea."""
    m = tmp_path / "msg.txt"
    m.write_text(
        "fix: algo\n\nCo-Authored-By: Claude Opus 5 <noreply@anthropic.com>\n",
        encoding="utf-8",
    )
    assert main([str(m)]) == 1
    assert crystallization_issues(m.read_text(encoding="utf-8"))


def test_blocks_gpt_version(tmp_path):
    """`GPT-5 <noreply@openai.com>` bloquea."""
    m = tmp_path / "msg.txt"
    m.write_text(
        "fix: algo\n\nCo-Authored-By: GPT-5 <noreply@openai.com>\n", encoding="utf-8"
    )
    assert main([str(m)]) == 1


def test_blocks_deepseek_version(tmp_path):
    """`deepseek-v4 <noreply@...>` (marca base + version) bloquea."""
    m = tmp_path / "msg.txt"
    m.write_text(
        "fix: algo\n\nCo-Authored-By: deepseek-v4 <noreply@example.com>\n",
        encoding="utf-8",
    )
    assert main([str(m)]) == 1


# --------------------------------------------------------------------------
# Clase (ii): contexto (1M context) -> BLOQUEA
# --------------------------------------------------------------------------


def test_blocks_model_with_context(tmp_path):
    """`Claude Opus 4.8 (1M context)` bloquea por discriminante + contexto."""
    m = tmp_path / "msg.txt"
    m.write_text(
        "fix: algo\n\n"
        "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>\n",
        encoding="utf-8",
    )
    assert main([str(m)]) == 1


# --------------------------------------------------------------------------
# Clase (iii): trailer humano -> PASA
# --------------------------------------------------------------------------


def test_allows_human_coauthor(tmp_path):
    """`Nombre <email@dominio.com>` (email NO noreply@) pasa."""
    m = tmp_path / "msg.txt"
    m.write_text(
        "fix: algo\n\nCo-Authored-By: Ana Perez <ana@empresa.com>\n",
        encoding="utf-8",
    )
    assert main([str(m)]) == 0


def test_allows_no_trailer(tmp_path):
    """Un mensaje sin Co-Authored-By pasa."""
    m = tmp_path / "msg.txt"
    m.write_text("fix: algo\n", encoding="utf-8")
    assert main([str(m)]) == 0


# --------------------------------------------------------------------------
# Clase (iv): generico sin discriminante -> PASA (borde adjudicado L710, DoD d)
# --------------------------------------------------------------------------


def test_allows_provider_without_discriminator(tmp_path):
    """BORDE ADJUDICADO: `Claude <noreply@anthropic.com>` (marca base SIN
    discriminante) pasa -- es identidad de proveedor/agente, no de modelo."""
    m = tmp_path / "msg.txt"
    m.write_text(
        "fix: algo\n\nCo-Authored-By: Claude <noreply@anthropic.com>\n",
        encoding="utf-8",
    )
    assert main([str(m)]) == 0, "marca base sin version no es cristalizacion"
    assert not crystallization_issues(m.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# Mutation / distincion modelo-vs-proveedor (DoD c + d)
# --------------------------------------------------------------------------


def test_discriminates_model_from_provider(tmp_path):
    """El MISMO trailer con `Claude` solo pasa y con `Claude Opus 5` bloquea.

    Demuestra que el guard distingue identidad de MODELO de identidad de
    PROVEEDOR/agente: el discriminante es lo que decide, no la marca base.
    """
    provider = tmp_path / "p.txt"
    provider.write_text(
        "Co-Authored-By: Claude <noreply@anthropic.com>\n", encoding="utf-8"
    )
    model = tmp_path / "m.txt"
    model.write_text(
        "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>\n", encoding="utf-8"
    )
    assert main([str(provider)]) == 0
    assert main([str(model)]) == 1


def test_comments_are_stripped(tmp_path):
    """Los comentarios `#` de git (scissors/template) no generan hallazgo."""
    m = tmp_path / "msg.txt"
    m.write_text(
        "fix: algo\n\n"
        "# Esta es una plantilla con Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>\n"
        "Co-Authored-By: Ana Perez <ana@empresa.com>\n",
        encoding="utf-8",
    )
    assert main([str(m)]) == 0
