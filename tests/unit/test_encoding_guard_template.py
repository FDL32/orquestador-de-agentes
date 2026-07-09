"""Mutation-verified barrier tests for CTL-2026-012i (conformidad template HTML).

Guards (Check 2; cross-repo):
(a) REGISTRY: ``build_template_registry`` lee 3 templates fixture (Product,
    CollectionPage, Article) y retorna dict con ``h2_count`` y ``accent_freq``
    > 0. Fail-closed: dir inexistente, sin templates, o @type primario
    duplicado lanzan (el CLI traduce a exit 2, nunca silent skip).
(b) @type BARRIER (mutation-verify): Product valido pasa; ``Thing`` (no en
    registry) -> ``<unknown-type>``; sin JSON-LD -> ``<missing-jsonld>``; solo
    FAQPage -> ``<missing-primary-type>``; sin FAQPage -> ``<missing-faqpage>``.
(c) H2 BARRIER (mutation-verify): H2 suficiente (>= template - tolerancia)
    pasa; H2 colapsado (1-2) -> ``<h2-collapse>``.
(d) ACCENT BARRIER (mutation-verify): output acentuado pasa; output totalmente
    de-acentuado (freq ~0) -> ``<accent-below-template>``. Demuestra que 012i
    caza el caso que 012j NO caza (limitacion conocida: doc totalmente
    de-acentuado tiene baseline ~0 y no se flaggea intra-documento).
(e) NO FALSE POSITIVE: output conforme al template Product con divergencia
    legitima de 1 H2 (8 vs 9 = ``H2_TOLERANCE``) -> 0 issues (no falso positivo
    sobre el caso real medido que diverge del template).
(f) CLI: ``check_template_conformity.py`` exit 0 conforme / 1 no conforme /
    2 pathing invalido (fail-closed).
(g) THRESHOLDS: ``H2_TOLERANCE`` y ``TEMPLATE_ACCENT_FRACTION`` son constantes
    nombradas con los valores medidos (medicion reproducible sobre
    templates/outputs reales del destino registrada en ``execution_log.md``).

Reference convention: ``tests/unit/test_encoding_guard_deaccent.py`` (012j).
Los tests usan fixtures propios (self-contained, el motor no depende del
destino en CI); la medicion reproducible sobre templates/outputs reales del
destino esta registrada en ``execution_log.md`` (Fase 3).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

_MOTOR_ROOT = Path(__file__).resolve().parents[2]
_CLI = _MOTOR_ROOT / "scripts" / "check_template_conformity.py"

from encoding_guard import (  # noqa: E402
    H2_TOLERANCE,
    TEMPLATE_ACCENT_FRACTION,
    TemplateProfile,
    accent_frequency,
    build_template_registry,
    count_h2,
    extract_jsonld_types,
    find_deaccentuation_lossy,
    find_template_conformity_issues,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# Template Product: 9 H2 (espeja el template real del destino).
_PRODUCT_H2 = [
    "¿Qué es?",
    "Historia y origen",
    "Significado espiritual",
    "Características del producto",
    "Cómo se usa",
    "Tipos y variantes",
    "Cómo conservar",
    "Preguntas frecuentes",
    "Ficha técnica",
]
# Template CollectionPage: 8 H2.
_CATEGORIA_H2 = [
    "¿Qué es?",
    "Comprar baratas",
    "Venta online con entrega",
    "Precio y filtros",
    "Decoración especial",
    "Historia",
    "Simbolismo litúrgico",
    "Preguntas frecuentes",
]
# Template Article: 8 H2.
_BLOG_H2 = [
    "¿Qué es?",
    "Historia",
    "Significado litúrgico",
    "Sección adicional",
    "Otra sección",
    "Conclusión",
    "Mensaje pastoral",
    "Preguntas frecuentes",
]
# Output conforme: 8 H2 (divergencia legitima de 1 vs template Product de 9).
_PRODUCT_OUTPUT_H2 = [
    "¿Qué es el incienso litúrgico?",
    "Historia y origen del incienso",
    "Significado espiritual del incienso",
    "Características del producto litúrgico",
    "Cómo se usa el incienso litúrgico",
    "Tipos de incienso litúrgico",
    "Cómo conservar el incienso aromático",
    "Preguntas frecuentes sobre el incienso",
]
# Output de-acentuado: mismos H2 sin tildes (freq ~0).
_PRODUCT_OUTPUT_H2_DEACCENT = [
    "Que es el incienso liturgico?",
    "Historia y origen del incienso",
    "Significado espiritual del incienso",
    "Caracteristicas del producto liturgico",
    "Como se usa el incienso liturgico",
    "Tipos de incienso liturgico",
    "Como conservar el incienso aromatico",
    "Preguntas frecuentes sobre el incienso",
]

_ACCENTED_PROSE = (
    "La liturgia católica celebra la solemnidad con incienso aromático en la "
    "celebración eucarística; la oración litúrgica eleva el alma hacia Dios "
    "en la parroquia durante la celebración solemne."
)
_DEACCENTED_PROSE = (
    "La liturgia catolica celebra la solemnidad con incienso aromatico en la "
    "celebracion eucaristica; la oracion liturgica eleva el alma hacia Dios "
    "en la parroquia durante la celebracion solemne."
)


def _template_html(primary_type: str, h2_titles: list[str]) -> str:
    head = (
        '<html lang="es"><head><meta charset="UTF-8">\n'
        '<script type="application/ld+json">'
        '{"@context":"https://schema.org","@type":"'
        f'{primary_type}","name":"Incienso litúrgico"}}'
        "</script>\n"
        '<script type="application/ld+json">'
        '{"@context":"https://schema.org","@type":"FAQPage","mainEntity":[]}'
        "</script>\n"
        "</head><body><article>\n"
    )
    body = "\n".join(f"<h2>{title}</h2>" for title in h2_titles) + "\n"
    return head + body + "</article></body></html>\n"


def _output_html(
    types: list[str],
    h2_titles: list[str],
    prose: str,
    name: str = "Incienso litúrgico",
) -> str:
    blocks = ""
    for type_name in types:
        blocks += (
            '<script type="application/ld+json">'
            '{"@context":"https://schema.org","@type":"'
            f'{type_name}","name":"{name}"}}'
            "</script>\n"
        )
    head = (
        f'<html lang="es"><head><meta charset="UTF-8">\n{blocks}'
        "</head><body><article>\n"
    )
    body = "\n".join(f"<h2>{title}</h2>\n<p>{prose}</p>" for title in h2_titles) + "\n"
    return head + body + "</article></body></html>\n"


def _make_templates_dir(tmp_path: Path) -> Path:
    """Create ``tmp_path/content_roles/templates/`` with the 3 fixture templates."""
    templates_dir = tmp_path / "content_roles" / "templates"
    templates_dir.mkdir(parents=True)
    (templates_dir / "article_producto_template.html").write_text(
        _template_html("Product", _PRODUCT_H2), encoding="utf-8"
    )
    (templates_dir / "article_categoria_template.html").write_text(
        _template_html("CollectionPage", _CATEGORIA_H2), encoding="utf-8"
    )
    (templates_dir / "article_blog_template.html").write_text(
        _template_html("Article", _BLOG_H2), encoding="utf-8"
    )
    return templates_dir


def _registry(tmp_path: Path) -> dict[str, TemplateProfile]:
    return build_template_registry(_make_templates_dir(tmp_path))


def _conforme_output() -> str:
    return _output_html(["Product", "FAQPage"], _PRODUCT_OUTPUT_H2, _ACCENTED_PROSE)


# ---------------------------------------------------------------------------
# (a) Registry
# ---------------------------------------------------------------------------


class TestTemplateRegistry:
    def test_registry_has_three_unique_entries(self, tmp_path: Path) -> None:
        reg = _registry(tmp_path)
        assert set(reg) == {"Product", "CollectionPage", "Article"}

    def test_entries_have_positive_h2_and_accent(self, tmp_path: Path) -> None:
        reg = _registry(tmp_path)
        for primary, profile in reg.items():
            assert profile.h2_count > 0, f"{primary}: h2_count <= 0"
            assert profile.accent_freq > 0, f"{primary}: accent_freq <= 0"
            assert profile.has_faqpage is True, f"{primary}: missing FAQPage"

    def test_product_template_has_nine_h2(self, tmp_path: Path) -> None:
        assert _registry(tmp_path)["Product"].h2_count == 9

    def test_failclosed_missing_dir(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            build_template_registry(tmp_path / "does_not_exist")

    def test_failclosed_no_templates(self, tmp_path: Path) -> None:
        empty = tmp_path / "content_roles" / "templates"
        empty.mkdir(parents=True)
        with pytest.raises(FileNotFoundError):
            build_template_registry(empty)

    def test_failclosed_duplicate_primary_type(self, tmp_path: Path) -> None:
        templates_dir = tmp_path / "content_roles" / "templates"
        templates_dir.mkdir(parents=True)
        (templates_dir / "article_producto_template.html").write_text(
            _template_html("Product", _PRODUCT_H2), encoding="utf-8"
        )
        (templates_dir / "article_producto_dup_template.html").write_text(
            _template_html("Product", _PRODUCT_H2), encoding="utf-8"
        )
        with pytest.raises(ValueError, match="duplicate primary @type"):
            build_template_registry(templates_dir)


# ---------------------------------------------------------------------------
# (b) @type barrier (mutation-verify)
# ---------------------------------------------------------------------------


class TestTypeBarrier:
    def test_valid_product_type_passes(self, tmp_path: Path) -> None:
        assert (
            find_template_conformity_issues(_conforme_output(), _registry(tmp_path))
            == []
        )

    def test_unknown_type_thing_fails(self, tmp_path: Path) -> None:
        html = _output_html(["Thing", "FAQPage"], _PRODUCT_OUTPUT_H2, _ACCENTED_PROSE)
        assert find_template_conformity_issues(html, _registry(tmp_path)) == [
            "<unknown-type:Thing>"
        ]

    def test_missing_jsonld_fails(self, tmp_path: Path) -> None:
        html = (
            '<html lang="es"><head><meta charset="UTF-8"></head><body><article>\n'
            + "\n".join(f"<h2>{t}</h2>" for t in _PRODUCT_OUTPUT_H2)
            + "\n</article></body></html>\n"
        )
        assert find_template_conformity_issues(html, _registry(tmp_path)) == [
            "<missing-jsonld>"
        ]

    def test_only_faqpage_fails(self, tmp_path: Path) -> None:
        html = _output_html(["FAQPage"], _PRODUCT_OUTPUT_H2, _ACCENTED_PROSE)
        assert find_template_conformity_issues(html, _registry(tmp_path)) == [
            "<missing-primary-type>"
        ]

    def test_missing_faqpage_fails(self, tmp_path: Path) -> None:
        html = _output_html(["Product"], _PRODUCT_OUTPUT_H2, _ACCENTED_PROSE)
        assert find_template_conformity_issues(html, _registry(tmp_path)) == [
            "<missing-faqpage>"
        ]


# ---------------------------------------------------------------------------
# (c) H2 barrier (mutation-verify)
# ---------------------------------------------------------------------------


class TestH2Barrier:
    def test_h2_sufficient_passes(self, tmp_path: Path) -> None:
        # 8 H2 vs template 9 -> 8 >= 9 - 1 (H2_TOLERANCE) -> PASS.
        issues = find_template_conformity_issues(
            _conforme_output(), _registry(tmp_path)
        )
        assert not any("<h2-collapse" in i for i in issues), issues

    def test_h2_collapsed_fails(self, tmp_path: Path) -> None:
        collapsed = ["¿Qué es el incienso litúrgico?"]
        html = _output_html(["Product", "FAQPage"], collapsed, _ACCENTED_PROSE)
        issues = find_template_conformity_issues(html, _registry(tmp_path))
        assert any("<h2-collapse" in i for i in issues), issues


# ---------------------------------------------------------------------------
# (d) Accent barrier (mutation-verify)
# ---------------------------------------------------------------------------


class TestAccentBarrier:
    def test_accented_output_passes(self, tmp_path: Path) -> None:
        issues = find_template_conformity_issues(
            _conforme_output(), _registry(tmp_path)
        )
        assert not any("<accent-below-template" in i for i in issues), issues

    def test_fully_deaccented_output_fails(self, tmp_path: Path) -> None:
        html = _output_html(
            ["Product", "FAQPage"],
            _PRODUCT_OUTPUT_H2_DEACCENT,
            _DEACCENTED_PROSE,
            name="Incienso liturgico",
        )
        # Sanity: the fixture really is fully de-accented (freq 0).
        assert accent_frequency(html) == 0.0
        issues = find_template_conformity_issues(html, _registry(tmp_path))
        assert any("<accent-below-template" in i for i in issues), issues

    def test_012j_does_not_catch_fully_deaccented(self) -> None:
        """012i caza lo que 012j NO caza: doc totalmente de-acentuado.

        Un documento COMPLETAMENTE de-acentuado tiene baseline ~0
        (< DEACCENT_BASELINE_MIN) y ``find_deaccentuation_lossy`` (012j) no lo
        flaggea (limitacion conocida). 012i lo caza cross-documento via el
        baseline del template.
        """
        deaccented_doc = "\n".join([_DEACCENTED_PROSE] * 200) + "\n"
        assert find_deaccentuation_lossy(deaccented_doc) == []


# ---------------------------------------------------------------------------
# (e) No false positive on real divergence
# ---------------------------------------------------------------------------


class TestNoFalsePositive:
    def test_real_divergence_one_h2_passes(self, tmp_path: Path) -> None:
        """Output con 8 H2 vs template Product 9 (divergencia 1 = tolerancia).

        Es el caso real medido (incienso ES: 8 vs 9). No debe haber falso
        positivo: 0 issues.
        """
        reg = _registry(tmp_path)
        assert reg["Product"].h2_count == 9
        html = _conforme_output()
        assert count_h2(html) == 8
        assert find_template_conformity_issues(html, reg) == []


# ---------------------------------------------------------------------------
# (f) CLI exit codes
# ---------------------------------------------------------------------------


class TestCliExitCodes:
    def _run_cli(self, project_root: Path, html_path: Path) -> int:
        return subprocess.run(
            [
                sys.executable,
                str(_CLI),
                "--project-root",
                str(project_root),
                "--html",
                str(html_path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).returncode

    def test_cli_conforme_exit0(self, tmp_path: Path) -> None:
        _make_templates_dir(tmp_path)
        html_path = tmp_path / "conforme.html"
        html_path.write_text(_conforme_output(), encoding="utf-8")
        assert self._run_cli(tmp_path, html_path) == 0

    def test_cli_nonconforme_exit1(self, tmp_path: Path) -> None:
        _make_templates_dir(tmp_path)
        html_path = tmp_path / "collapsed.html"
        html_path.write_text(
            _output_html(
                ["Product", "FAQPage"],
                ["¿Qué es el incienso litúrgico?"],
                _ACCENTED_PROSE,
            ),
            encoding="utf-8",
        )
        assert self._run_cli(tmp_path, html_path) == 1

    def test_cli_invalid_projectroot_failclosed(self, tmp_path: Path) -> None:
        # project-root without content_roles/templates/ -> fail-closed (!= 0).
        html_path = tmp_path / "x.html"
        html_path.write_text("<html></html>", encoding="utf-8")
        assert self._run_cli(tmp_path, html_path) != 0

    def test_cli_nonexistent_projectroot_failclosed(self, tmp_path: Path) -> None:
        html_path = tmp_path / "x.html"
        html_path.write_text("<html></html>", encoding="utf-8")
        assert self._run_cli(tmp_path / "nope", html_path) != 0


# ---------------------------------------------------------------------------
# (g) Threshold constants + unit functions
# ---------------------------------------------------------------------------


class TestThresholdConstants:
    def test_constants_are_measured_values(self) -> None:
        assert H2_TOLERANCE == 1
        assert TEMPLATE_ACCENT_FRACTION == 0.5

    def test_extract_jsonld_types(self) -> None:
        html = (
            '<script type="application/ld+json">{"@type":"Product"}</script>'
            '<script type="application/ld+json">{"@type":"FAQPage"}</script>'
        )
        assert extract_jsonld_types(html) == ["Product", "FAQPage"]

    def test_extract_jsonld_list_type(self) -> None:
        html = '<script type="application/ld+json">{"@type":["Product","FAQPage"]}</script>'
        assert extract_jsonld_types(html) == ["Product", "FAQPage"]

    def test_count_h2_robust_to_attributes(self) -> None:
        assert count_h2("<h2>a</h2><h2 style='x'>b</h2><h3>c</h3><h4>d</h4>") == 2

    def test_accent_frequency(self) -> None:
        assert accent_frequency("") == 0.0
        assert accent_frequency("aaaa") == 0.0
        assert accent_frequency("cámara") > 0.0
