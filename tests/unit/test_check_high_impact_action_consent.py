import json
import re
import sys
from pathlib import Path


_MOTOR_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_DIR = _MOTOR_ROOT / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import check_high_impact_action_consent as hiac  # noqa: E402


_CONFIGURED_BACKEND_ALIASES = {
    "anthropic",
    "claude",
    "codex",
    "cohere",
    "gemini",
    "groq",
    "kilo",
    "kiosapi",
    "llm7",
    "mistral",
    "nan",
    "nvidia",
    "opencode",
    "openrouter",
    "tokenharbor",
}
_CONFIGURED_FAMILY_PATTERNS = {
    family: re.compile(
        rf"\b{family}(?:\d+(?:\.\d+)?|-[a-z0-9]+(?:[.-][a-z0-9]+)*)?\b",
        re.IGNORECASE,
    )
    for family in (
        "claude",
        "codestral",
        "command",
        "deepseek",
        "gemini",
        "gemma",
        "glm",
        "gpt",
        "haiku",
        "kimi",
        "mimo",
        "minimax",
        "mistral",
        "nemotron",
        "north",
        "opus",
        "qwen",
        "sonnet",
    )
}
_EXCLUDED_CONFIG_FAMILIES = {"sol": "common Spanish word; never a provider token"}


def _write(tmp_path: Path, rel: str, text: str) -> Path:
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# WOT-2026-043n DoD (b): mutation en las dos direcciones, caso real 042q.
_DISPATCH_TEXT_NO_CONSENT = (
    "# Arranque del vuelo\n\n"
    "Haz fan-out a 5 backends externos con el bundle completo del ticket.\n"
)

_DISPATCH_TEXT_WITH_CONSENT = (
    "# Arranque del vuelo\n\n"
    "Autorizacion: usuario, en la sesion que redacto este prompt.\n\n"
    "Haz fan-out a 5 backends externos con el bundle completo del ticket.\n"
)


def test_dispatch_externo_sin_autorizacion_falla_nombrando_la_accion():
    errors = hiac.check_action_consent(_DISPATCH_TEXT_NO_CONSENT)

    assert len(errors) == 1
    assert "dispatch_externo" in errors[0]


def test_dispatch_externo_con_autorizacion_pasa():
    errors = hiac.check_action_consent(_DISPATCH_TEXT_WITH_CONSENT)

    assert errors == []


def test_mutation_both_directions():
    """DoD (b): ordenar sin clausula -> ROJO; con clausula -> VERDE."""
    red = hiac.check_action_consent(_DISPATCH_TEXT_NO_CONSENT)
    assert any("dispatch_externo" in e for e in red)

    green = hiac.check_action_consent(_DISPATCH_TEXT_WITH_CONSENT)
    assert green == []


def test_vague_sin_autorizacion_does_not_mask_as_consent():
    """'sin autorizacion' no debe leerse como una clausula POSITIVA."""
    text = "Haz fan-out a 5 backends externos, sin autorizacion explicita de nadie.\n"

    errors = hiac.check_action_consent(text)

    assert any("dispatch_externo" in e for e in errors)


def test_push_sin_autorizacion_falla():
    text = "Cuando termines, haz git push a origin de la rama del vuelo.\n"

    errors = hiac.check_action_consent(text)

    assert any("push" in e for e in errors)


def test_borrado_irreversible_sin_autorizacion_falla():
    text = "Antes de reintentar, ejecuta rm -rf sobre el directorio de cache.\n"

    errors = hiac.check_action_consent(text)

    assert any("borrado_irreversible" in e for e in errors)


def test_gasto_desproporcionado_sin_autorizacion_falla():
    text = "Lee 1070 lineas de contratos antes de la re-medicion read-only.\n"

    errors = hiac.check_action_consent(text)

    assert any("gasto_desproporcionado" in e for e in errors)


def test_local_readonly_artifact_is_never_blocked():
    """DoD (c): anti-falso-positivo, un artefacto solo local/read-only no se marca."""
    text = (
        "# Triaje local\n\n"
        "Lee el backlog.md y el STATE.md del destino, clasifica cada ticket y "
        "escribe el informe en orchestrator_pipeline/reports/. No toca git, no "
        "publica nada fuera de la maquina.\n"
    )

    errors = hiac.check_action_consent(text)

    assert errors == []


def test_main_cli_exits_1_naming_the_category(tmp_path, capsys):
    artifact = _write(tmp_path, "flight_start.md", _DISPATCH_TEXT_NO_CONSENT)

    rc = hiac.main(["--artifact", str(artifact)])

    assert rc == 1
    err = capsys.readouterr().err
    assert "dispatch_externo" in err


def test_main_cli_exits_0_when_consent_declared(tmp_path, capsys):
    artifact = _write(tmp_path, "flight_start.md", _DISPATCH_TEXT_WITH_CONSENT)

    rc = hiac.main(["--artifact", str(artifact)])

    assert rc == 0
    out = capsys.readouterr().out
    assert "OK" in out


def test_main_cli_errors_on_missing_artifact(tmp_path, capsys):
    missing = tmp_path / "does_not_exist.md"

    rc = hiac.main(["--artifact", str(missing)])

    assert rc == 2
    err = capsys.readouterr().err
    assert "no encontrado" in err


def test_marker_values_are_not_valid_for_any_consent_clause_form():
    """Each supported authorization spelling rejects every marker value."""
    forms = (
        "Autorizacion: {value}",
        "Autoriza: {value}",
        "Autorizado por {value}",
        "Con autorizacion explicita de {value}",
        "Quien autoriza: {value}",
    )
    markers = ("pendiente", "ninguna", "ninguno", "tbd", "n/a", "?")

    for form in forms:
        for marker in markers:
            text = (
                form.format(value=marker)
                + "\nHaz fan-out a 5 backends externos con el bundle completo.\n"
            )
            errors = hiac.check_action_consent(text)
            assert any("dispatch_externo" in error for error in errors), (
                form,
                marker,
                errors,
            )


def test_valid_clause_after_marker_still_allows_action():
    """One valid clause is sufficient even when an earlier clause is a marker."""
    text = (
        "Autorizacion: pendiente\n"
        "Con autorizacion de usuario\n"
        "Haz fan-out a 5 backends externos con el bundle completo.\n"
    )

    assert hiac.check_action_consent(text) == []


def test_consent_value_normalization_and_diacritic_marker():
    """Markdown punctuation and diacritics are normalized for markers."""
    cases = (
        "Autorizacion: **pendiente**",
        "Autoriza: `ninguna`",
        "Autorizado por 'tbd.'",
        "Con autorizacion explicita de PENDIENTE de ratificacion",
        "Autorizacion: péndiente",
        "Quien autoriza: ¿N/A?",
        "Autorizacion: (pendiente)",
        "Autorizacion: [pendiente]",
        "Autorizacion: <ninguna>",
        "Autorizacion: **",
        "Autorizacion: ***",
        "Autorizacion: ()",
    )

    for clause in cases:
        errors = hiac.check_action_consent(
            clause + "\nHaz fan-out a 5 backends externos con el bundle completo.\n"
        )
        assert any("dispatch_externo" in error for error in errors), (clause, errors)


def test_empty_consent_clause_does_not_consume_next_line():
    """A same-line value is required; a later order cannot be its value."""
    order = "Haz fan-out a 5 backends externos con el bundle completo.\n"
    for clause in ("Autorizacion:", "Quien autoriza:"):
        errors = hiac.check_action_consent(clause + "\n" + order)
        assert any("dispatch_externo" in error for error in errors), clause

    assert hiac.check_action_consent("Autorizacion: CO-29\n" + order) == []
    assert hiac.check_action_consent("**Autorizacion:** CO-29\n" + order) == []

    for clause in ("**Autorizacion:**", "**Autorizacion:** pendiente"):
        errors = hiac.check_action_consent(clause + "\n" + order)
        assert any("dispatch_externo" in error for error in errors), clause


def test_real_lens_loop_forms_are_dispatch_actions():
    """The two recorded CO-29 loop forms are treated as external dispatch."""
    texts = (
        "bucle codex gamsgo sol 6.1, claude alvarovans opus 5.5, "
        "glm opencode, deepseek nan, qwen3.8 con ficheros.\n",
        "bucle de lentes (codex gamsgo, glm opencode, deepseek nan...).\n",
        "Bucle de diseno: glm opencode (BA06, ficheros), qwen3.8 kilo "
        "(BA02, ficheros), deepseek nan (BA10, SOLO texto), codex gamsgo "
        "(ficheros), claude opus-5-5 alvarovans (ficheros).\n",
    )

    for text in texts:
        errors = hiac.check_action_consent(text)
        assert any("dispatch_externo" in error for error in errors), (text, errors)


def test_loop_model_variants_are_detected_and_same_provider_is_not():
    """Classifier-accepted model variants must preserve distinct-provider semantics."""
    for family, classifier in _CONFIGURED_FAMILY_PATTERNS.items():
        variant = next(
            candidate
            for candidate in (f"{family}4.7", f"{family}-v4-flash", f"{family}-k2")
            if classifier.fullmatch(candidate)
        )
        assert hiac.check_action_consent(f"Lanza un bucle con {variant} y codex.")
        assert hiac.check_action_consent(f"Lanza un bucle con {variant}.") == []
        assert (
            hiac.check_action_consent(f"Lanza un bucle con {variant} y {variant}.")
            == []
        )

    for text in (
        "Lanza un bucle con glm4.7 y qwen3.8.",
        "Lanza un bucle con glm5.3 y deepseek.",
    ):
        assert hiac.check_action_consent(text)


def test_loop_provider_variants_from_config_are_detected():
    """Configured backend aliases also accept versioned and hyphenated forms."""
    for backend in _CONFIGURED_BACKEND_ALIASES:
        for variant in (f"{backend}4.7", f"{backend}-v4-flash"):
            text = f"Lanza un bucle con {variant} y glm."
            assert hiac.check_action_consent(text), (backend, variant)


def test_loop_account_aliases_are_dispatch_providers():
    """The recorded account aliases are provider tokens, not prose."""
    for account in ("gamsgo", "alvarovans"):
        errors = hiac.check_action_consent(f"Lanza un bucle con {account} y glm.")
        assert any("dispatch_externo" in error for error in errors), (account, errors)


def test_loop_of_lenses_requires_same_line():
    """The documented loop phrase cannot cross a line boundary."""
    text = "Lanza un bucle de\nlentes con codex y glm.\n"

    assert hiac.check_action_consent(text) == []


def test_one_provider_loop_is_not_dispatch():
    """One provider, or the same provider twice, is not external fan-out."""
    texts = (
        "Describe un bucle con codex solamente.\n",
        "El bucle usa codex y de nuevo codex.\n",
    )

    for text in texts:
        assert hiac.check_action_consent(text) == []


def test_loop_provider_tokens_sync_with_agents_json():
    """Configured tokens and classifier variants are behaviorally synchronized."""
    config = json.loads(
        (_MOTOR_ROOT / ".agent" / "config" / "agents.json").read_text(encoding="utf-8")
    )
    profiles = config["ensemble_profiles"].values()
    backends = {profile["backend"].removesuffix("_api") for profile in profiles}
    models = [profile.get("model") for profile in config["ensemble_profiles"].values()]
    models = [model for model in models if model]

    missing_backends = sorted(backends - _CONFIGURED_BACKEND_ALIASES)
    assert not missing_backends, missing_backends

    missing_families = [
        model
        for model in models
        if not any(
            pattern.search(model) for pattern in _CONFIGURED_FAMILY_PATTERNS.values()
        )
        and not any(
            re.search(rf"\b{re.escape(excluded)}\b", model, re.IGNORECASE)
            for excluded in _EXCLUDED_CONFIG_FAMILIES
        )
    ]
    assert not missing_families, missing_families

    loop_pattern = hiac.ACTION_PATTERNS["dispatch_externo"]
    for token in sorted(backends):
        assert re.search(rf"\b{re.escape(token)}\b", loop_pattern.pattern)

    for family, classifier in _CONFIGURED_FAMILY_PATTERNS.items():
        variant = next(
            candidate
            for candidate in (f"{family}4.7", f"{family}-v4-flash", f"{family}-k2")
            if classifier.fullmatch(candidate)
        )
        assert hiac.check_action_consent(f"Lanza un bucle con {variant} y codex.")
        assert hiac.check_action_consent(f"Lanza un bucle con {variant}.") == []
        assert (
            hiac.check_action_consent(f"Lanza un bucle con {variant} y {variant}.")
            == []
        )


def test_descriptive_two_provider_loop_requires_consent():
    """The fail-closed structural heuristic also blocks descriptive prose."""
    text = (
        "La documentacion describe un bucle de lentes con codex y glm, sin "
        "enviar ningun bundle.\n"
    )

    errors = hiac.check_action_consent(text)

    assert any("dispatch_externo" in error for error in errors)


def test_prose_without_provider_names_is_not_dispatch():
    """A loop mention without provider names remains local documentation."""
    text = "La documentacion describe un bucle de lentes como concepto.\n"

    assert hiac.check_action_consent(text) == []
