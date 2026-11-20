"""Barrera WOT-2026-048h: `write: false` sin enforcement posible FALLA nombrando el par.

Cierra la laguna DECLARADA de WOT-2026-048k. El criterio load-bearing es que
solo se vigilan los perfiles con VECTOR REAL (`channel: agent`): un gate que
exigiera `readonly_agent` a un backend HTTP (`channel: api`) seria over-gating,
y un gate que grita donde no hay riesgo acaba con allowlist o desactivado.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest
import yaml
from scripts.check_agent_write_enforced import (
    NON_READ_PERMISSION_KEYS,
    _permissive_write_permissions,
    find_unenforced_pairs,
    has_native_sandbox,
    main,
)


MOTOR_AUDITOR_PATH = (
    Path(__file__).resolve().parents[2] / ".opencode" / "agents" / "auditor.md"
)
_MOTOR_ROOT = Path(__file__).resolve().parents[2]
# Cadena RAW a proposito: la clave del mapa external_directory lleva barras
# dobles YAML ("C:\\Users\\...") y un \U simple se leeria como escape unicode
# de 8 digitos, rompiendo el frontmatter (WOT-2026-209a F3, medido A/B
# 2026-11-20: con barra simple el parser falla y opencode DESCARTA el agente).
DESTINO_AUDITOR_TEXT = r"""---
description: Read-only audit lens for ensemble governance loops
mode: primary
permission:
  "*": deny
  read: allow
  glob: allow
  grep: allow
  list: allow
  edit: deny
  bash: deny
  task: deny
  todowrite: deny
  webfetch: deny
  websearch: deny
  codesearch: deny
  skill: deny
  external_directory:
    "*": deny
    "C:\\Users\\fdl\\Proyectos_Python\\orquestador_de_agentes\\**": allow
---

You are a READ-ONLY audit lens for the orquestador_de_agentes repo, running through OpenCode
as one participant of an ensemble governance loop (`scripts/ensemble_dispatch.py`).

Your job is to JUDGE the bundle you receive, not to implement anything.

## Why this agent exists

Ensemble profiles declare `write: false` in `.agent/config/agents.json`. Before WOT-2026-048k
that field was DECORATIVE: the dispatcher never translated it into anything on the command
line, so `opencode run` fell back to `default_agent` (`builder`), and an audit lens received
the BUILDER system prompt -- with `edit`, `bash` and `task` allowed -- while being asked to
audit. Measured 2026-08-05: a GLM lens deliberated about whether to call `--mark-ready` and
about its `Files Likely Touched` whitelist, neither of which appeared anywhere in its bundle.
The only thing standing between an audit lens and a write was the model's own restraint.

This agent is the enforcement half of that contract: a profile declaring `write: false` is
dispatched with `--agent auditor`, and the permissions above make the declaration real.

## Operating rules

- Answer ONLY what the bundle asks. Do not implement, refactor or "fix while you are there".
- Never call `--mark-ready`, never emit `BUILDER_EXIT`, never close a ticket. You are not the
  Builder; there is usually no active Builder ticket that corresponds to your bundle.
- Do not treat the repository's collaboration state (`.agent/collaboration/*`) as your task.
  If the bundle embeds content, judge the EMBEDDED content -- that is the point of a bundle.
- If a claim cannot be settled with the evidence you were given, say `INSUFICIENTE` and name
  the exact measurement that is missing. Do not infer the missing link and do not soften it.
- Prefer refuting over confirming. A confirmation that is wrong is far more expensive than a
  refutation that is wrong: the loop exists to catch plausible-but-false claims.
- Report verdicts in the format the bundle requests. Your final text IS the return value.
"""
# F6 (P34 r1): este JSON es un DELTA DE FUSION, no un fichero de
# reemplazo. La coordinadora debe FUSIONAR "mcp": {"github": {"enabled":
# false}} en el .opencode/opencode.json EXISTENTE del destino (creandolo con
# estas claves si aun no existe), conservando cualquier clave que ya traiga
# (default_agent, model, share, ...). Rutas destino exactas, con <destino> =
# C:/Users/fdl/Proyectos_Python/orquestador_de_agentes_workspace:
#   <destino>/.opencode/agents/auditor.md  -> REEMPLAZAR por DESTINO_AUDITOR_TEXT
#   <destino>/.opencode/opencode.json      -> FUSIONAR mcp.github.enabled=false (sin reemplazar)
DESTINO_OPENCODE_JSON = """{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "github": {
      "enabled": false
    }
  }
}
"""


def derive_destino_auditor(motor_text: str) -> str:
    """Deriva la copia destino desde el auditor del motor.

    Before: `motor_text` contiene el artefacto canonico con el bloque scalar.
    During: reemplaza unicamente la regla scalar de `external_directory` por
        el mapa destino: catch-all `"*": deny` PRIMERO y el allow del arbol
        del motor AL FINAL (orden de la correccion). La clave del allow se
        escribe con barras DOBLES YAML: con barra simple `\\U` es un escape
        unicode invalido, el frontmatter no parsea y opencode descarta el
        agente entero (medido A/B 2026-11-20, WOT-2026-209a F3).
    After: devuelve el artefacto destino; `derive_destino_auditor(motor)`
        debe ser byte-igual al literal `DESTINO_AUDITOR_TEXT`.
    """
    slash = chr(92)
    destination_path = slash.join(
        ("C:", "Users", "fdl", "Proyectos_Python", "orquestador_de_agentes", "**")
    )
    yaml_path = destination_path.replace(slash, slash * 2)
    replacement = '  external_directory:\n    "*": deny\n    "' + yaml_path + '": allow'
    return motor_text.replace("  external_directory: deny", replacement)


def _opencode_bin() -> str:
    """Resuelve el binario de opencode sin skip: PATH o fallo explicito.

    Before: sin binario no hay medida posible; el contrato del ticket exige
        FALLAR, nunca saltar el test (m-06).
    During: `shutil.which("opencode")` -- sin variables de entorno, para que
        el helper sea hermetico y identico al del fichero de
        test_ensemble_dispatch (alli el guard 025z ademas prohibe
        `os.environ`). Si no resuelve, `pytest.fail` explicito.
    After: ruta absoluta ejecutable del CLI de opencode.
    """
    found = shutil.which("opencode")
    if found:
        return found
    pytest.fail(
        "binario opencode ausente de PATH; el test exige el binario y NO "
        "se salta (WOT-2026-209a m-06)"
    )


def _skip_construct_count(text: str) -> int:
    """Cuenta construcciones de salto sin dejar patrones literales en el test.

    Before: `text` es fuente de test potencialmente peligrosa.
    During: ensambla los tokens de control y cuenta sus apariciones.
    After: devuelve el número de construcciones prohibidas encontradas.
    """
    tokens = [
        "pytest." + "mark.skip",
        "pytest." + "skip(",
        "import" + "orskip",
        "skip" + "if",
    ]
    return sum(text.count(token) for token in tokens)


def test_destino_fixture_is_derived_from_motor_and_materialized(tmp_path):
    """La fixture literal es una copia fiel derivada del unico origen motor.

    F4 (P34 r1): la materializacion es HERMETICA, bajo `tmp_path` -- nunca
    en una ruta absoluta de la maquina del autor. La copia de entrega fuera
    del repo (C:/Temp/co141/im-209a/destino_fixture) se regenera out-of-band
    por el IM; este test solo prueba fidelidad y materializacion.
    """
    motor_text = MOTOR_AUDITOR_PATH.read_text(encoding="utf-8")
    assert derive_destino_auditor(motor_text) == DESTINO_AUDITOR_TEXT
    root = tmp_path / ".opencode"
    (root / "agents").mkdir(parents=True, exist_ok=True)
    (root / "agents" / "auditor.md").write_text(DESTINO_AUDITOR_TEXT, encoding="utf-8")
    (root / "opencode.json").write_text(DESTINO_OPENCODE_JSON, encoding="utf-8")
    assert (root / "agents" / "auditor.md").read_text(
        encoding="utf-8"
    ) == DESTINO_AUDITOR_TEXT
    assert (root / "opencode.json").read_text(encoding="utf-8") == DESTINO_OPENCODE_JSON


def _frontmatter_permission(text: str) -> dict:
    """Parsea el mapping `permission` del frontmatter YAML de un auditor.md.

    Before: `text` es el contenido completo del artefacto (frontmatter
        cerrado por lineas `---`).
    During: extrae el bloque entre el primer par de lineas `---` y lo parsea
        con PyYAML -- la misma semantica de escapes de doble comilla que el
        parser de opencode (js-yaml). Un `\\U` sin escapar levanta
        ScannerError aqui: exactamente el defecto F3 que este test caza.
    After: el mapping `permission` (escalar por clave o mapa patron->accion).
    """
    match = re.match(r"\A---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    assert match, "el artefacto debe llevar frontmatter YAML cerrado por ---"
    document = yaml.safe_load(match.group(1))
    permission = (document or {}).get("permission")
    assert isinstance(permission, dict) and permission, "permission vacio"
    return permission


def _permission_map_to_rules(permission: dict) -> list[dict]:
    """Convierte el mapping `permission` a la lista de reglas tipo `agent list`.

    Before: `permission` es el mapping crudo del frontmatter.
    During: cada escalar vira a `{permission, action, pattern:"*"}` y cada
        mapa (patron -> accion) a una regla por entrada, conservando el
        orden del documento (el orden es semantica, F7).
    After: lista de reglas comparable con las que devuelve
        `_agent_permission_rules` de produccion.
    """
    rules: list[dict] = []
    for key, value in permission.items():
        if isinstance(value, dict):
            for pattern, action in value.items():
                rules.append({"permission": key, "action": action, "pattern": pattern})
        else:
            rules.append({"permission": key, "action": value, "pattern": "*"})
    return rules


def test_motor_and_destino_have_same_resolved_non_read_rules():
    """m-01: motor y destino resuelven identicas las 14 claves no-lectura.

    F3 (P34 r1): las reglas destino ya NO se escriben a mano -- se construyen
    PARSEANDO el frontmatter de `DESTINO_AUDITOR_TEXT` (el texto real que
    aplicara la coordinadora). Asi un error de escape o de orden en el
    artefacto rompe este test en vez de quedar tapado por una lista
    inventada. La UNICA diferencia permitida es el allow especifico de
    `external_directory` al arbol del motor, y se afirma explicitamente.
    """
    import scripts.check_agent_write_enforced as cawe

    motor_rules = _permission_map_to_rules(
        _frontmatter_permission(MOTOR_AUDITOR_PATH.read_text(encoding="utf-8"))
    )
    destino_rules = _permission_map_to_rules(
        _frontmatter_permission(DESTINO_AUDITOR_TEXT)
    )
    for key in NON_READ_PERMISSION_KEYS:
        motor_action = cawe._permission_action(motor_rules, key)
        destino_action = cawe._permission_action(destino_rules, key)
        assert motor_action == destino_action, (
            f"m-01: {key} difiere entre motor ({motor_action}) y "
            f"destino ({destino_action})"
        )
    # La diferencia declarada: el motor NO tiene allow especifico de
    # external_directory; el destino tiene EXACTAMENTE uno, al arbol real
    # del motor y sin la ruta _dev inexistente.
    motor_specific = [
        r
        for r in motor_rules
        if r["permission"] == "external_directory" and r["pattern"] != "*"
    ]
    destino_specific = [
        r
        for r in destino_rules
        if r["permission"] == "external_directory" and r["pattern"] != "*"
    ]
    assert motor_specific == []
    assert len(destino_specific) == 1
    assert destino_specific[0]["action"] == "allow"
    assert "orquestador_de_agentes" in destino_specific[0]["pattern"]
    assert "orquestador_de_agentes_dev" not in destino_specific[0]["pattern"]


def test_destino_artifact_parses_and_renders_via_opencode(tmp_path):
    """F3: opencode PARSEA y RENDERIZA el artefacto destino real (binario).

    Before: el texto de `DESTINO_AUDITOR_TEXT` debe ser aceptado por el
        parser real de opencode (no solo por PyYAML): un frontmatter roto
        hace que el CLI DESCARTE el agente entero (medido A/B 2026-11-20).
    During: materializa el artefacto bajo `tmp_path` (hermetico) y ejecuta
        `<opencode> agent list` desde ahi con los helpers de produccion.
        Si el binario falta, `_opencode_bin` hace `pytest.fail` (sin skip).
    After: el agente `auditor` aparece en el listado y sus 14 claves
        no-lectura resuelven `deny`, con el allow especifico al motor
        presente entre las reglas renderizadas.
    """
    import scripts.check_agent_write_enforced as cawe

    root = tmp_path / ".opencode" / "agents"
    root.mkdir(parents=True, exist_ok=True)
    (root / "auditor.md").write_text(DESTINO_AUDITOR_TEXT, encoding="utf-8")
    rules = cawe._agent_permission_rules(_opencode_bin(), str(tmp_path), "auditor")
    assert rules is not None, (
        "opencode NO listo el auditor desde la fixture: el frontmatter del "
        "artefacto destino no esta parseando (escape/orden)"
    )
    for key in NON_READ_PERMISSION_KEYS:
        assert cawe._permission_action(rules, key) == "deny", key
    specific = [
        r
        for r in rules
        if r.get("permission") == "external_directory" and r.get("pattern") != "*"
    ]
    assert any(
        r.get("action") == "allow" and "orquestador_de_agentes" in str(r.get("pattern"))
        for r in specific
    ), "el allow especifico al motor debe sobrevivir al render real"


@pytest.mark.parametrize("permission", NON_READ_PERMISSION_KEYS)
def test_every_non_read_allow_is_open(permission):
    """Cada permiso no lector abierto produce exactamente un hallazgo."""
    rules = [
        {"permission": "*", "action": "deny", "pattern": "*"},
        {"permission": permission, "action": "allow", "pattern": "*"},
    ]
    assert _permissive_write_permissions(rules) == [permission]


def test_empty_and_none_rules_are_failures():
    assert _permissive_write_permissions([]) == list(NON_READ_PERMISSION_KEYS)
    assert _permissive_write_permissions(None) == list(NON_READ_PERMISSION_KEYS)


def test_non_read_universe_is_exactly_the_declared_fourteen():
    """F1 (P34 r1): el oraculo del universo es INDEPENDIENTE de la constante.

    Sin este test, quitar una clave de `NON_READ_PERMISSION_KEYS` (p.ej.
    `skill`) encogeria los parametrizados y nada fallaria: el universo
    cerrado de 14 claves se afirma aqui contra literales escritos a mano.
    """
    esperadas = {
        "edit",
        "bash",
        "task",
        "todowrite",
        "webfetch",
        "websearch",
        "codesearch",
        "skill",
        "doom_loop",
        "lsp",
        "question",
        "plan_enter",
        "plan_exit",
        "external_directory",
    }
    assert len(NON_READ_PERMISSION_KEYS) == 14
    assert len(set(NON_READ_PERMISSION_KEYS)) == 14, "claves duplicadas"
    assert set(NON_READ_PERMISSION_KEYS) == esperadas


def test_ask_counts_as_open():
    """F2 (P34 r1): `ask` esta declarado ABIERTO y ahora tiene test propio."""
    rules = [
        {"permission": "*", "action": "deny", "pattern": "*"},
        {"permission": "doom_loop", "action": "ask", "pattern": "*"},
    ]
    assert _permissive_write_permissions(rules) == ["doom_loop"]


def test_all_non_read_denied_passes_and_external_catchall_is_special():
    rules = [
        {"permission": "*", "action": "deny", "pattern": "*"},
        {
            "permission": "external_directory",
            "action": "allow",
            "pattern": r"C:\specific",
        },
    ]
    assert _permissive_write_permissions(rules) == []
    assert _permissive_write_permissions(
        [
            {"permission": "*", "action": "allow", "pattern": "*"},
            {"permission": "external_directory", "action": "deny", "pattern": "*"},
            {
                "permission": "external_directory",
                "action": "allow",
                "pattern": r"C:\specific",
            },
        ]
    ) == [key for key in NON_READ_PERMISSION_KEYS if key != "external_directory"]


def test_external_directory_catchall_respects_order_and_ignores_specific():
    """F7 (P34 r1): de external_directory solo cuentan los catch-alls, en orden.

    Documenta y fija la semantica elegida (ver docstring de
    `_permission_action`):
    (a) un `"*": allow` GENERICO posterior a un catch-all deny gana ->
        abierto (el orden entre catch-alls se respeta, sin fail-open);
    (b) con el catch-all deny al final, deny -> cerrado;
    (c) los patrones especificos NO participan aunque sean amplios
        (`C:\\**`: allow pasa el gate): excepciones de lectura acotadas
        por diseno, limite declarado;
    (d) sin ningun catch-all externo, manda el ultimo catch-all generico.
    """
    import scripts.check_agent_write_enforced as cawe

    externo_deny_generico_allow = [
        {"permission": "external_directory", "action": "deny", "pattern": "*"},
        {"permission": "*", "action": "allow", "pattern": "*"},
    ]
    assert (
        cawe._permission_action(externo_deny_generico_allow, "external_directory")
        == "allow"
    )
    generico_allow_externo_deny = [
        {"permission": "*", "action": "allow", "pattern": "*"},
        {"permission": "external_directory", "action": "deny", "pattern": "*"},
    ]
    assert (
        cawe._permission_action(generico_allow_externo_deny, "external_directory")
        == "deny"
    )
    catchall_deny_allow_amplio = [
        {"permission": "external_directory", "action": "deny", "pattern": "*"},
        {"permission": "external_directory", "action": "allow", "pattern": "C:**"},
    ]
    assert (
        cawe._permission_action(catchall_deny_allow_amplio, "external_directory")
        == "deny"
    )
    solo_generico = [{"permission": "*", "action": "allow", "pattern": "*"}]
    assert cawe._permission_action(solo_generico, "external_directory") == "allow"


def test_opencode_json_disables_github_mcp():
    data = json.loads(
        (_MOTOR_ROOT / ".opencode" / "opencode.json").read_text(encoding="utf-8")
    )
    assert data["mcp"]["github"]["enabled"] is False


def test_auditor_text_has_four_network_skill_denies_and_no_dev_path():
    for text in (MOTOR_AUDITOR_PATH.read_text(encoding="utf-8"), DESTINO_AUDITOR_TEXT):
        assert (
            len(
                re.findall(
                    r"^  (?:webfetch|websearch|codesearch|skill): deny$",
                    text,
                    re.MULTILINE,
                )
            )
            == 4
        )
        assert "orquestador_de_agentes_dev" not in text


def test_skip_construct_counter_control():
    assert _skip_construct_count("assert True") == 0
    sample = "pytest." + "skip(" + "'control')"
    assert _skip_construct_count(sample) == 1


def test_real_opencode_auditor_permissions_from_repo_root():
    import scripts.check_agent_write_enforced as cawe

    rules = cawe._agent_permission_rules(_opencode_bin(), str(_MOTOR_ROOT), "auditor")
    assert rules is not None
    assert all(
        cawe._permission_action(rules, key) == "deny"
        for key in NON_READ_PERMISSION_KEYS
    )
    assert all(
        cawe._effective_action(rules, key) == "allow"
        for key in {"read", "glob", "grep", "list"}
    )


def _cfg(profiles: dict, backends: dict) -> dict:
    return {"ensemble_profiles": profiles, "backends": backends}


def test_agent_profile_without_readonly_agent_is_reported():
    """(2) el par huerfano se NOMBRA: perfil + backend, no un 'hay problemas'.

    Mutation que aisla la rama: si el gate deja de comprobar `readonly_agent`
    (o lo da por bueno cuando falta), esta lista queda vacia y el test cae. El
    fixture tiene UN solo perfil con vector, asi que nada mas puede producir el
    hallazgo.
    """
    cfg = _cfg(
        {"p_agente": {"channel": "agent", "write": False, "backend": "b_sin"}},
        {"b_sin": {}},
    )
    pairs = find_unenforced_pairs(cfg)
    assert len(pairs) == 1, f"el par huerfano debe detectarse: {pairs}"
    assert pairs[0]["profile"] == "p_agente"
    assert pairs[0]["backend"] == "b_sin", (
        "nombrar solo el perfil obliga a buscar el backend a mano"
    )


def test_api_channel_is_not_over_gated():
    """(1) un backend HTTP NO se vigila: no tiene el vector.

    Es la mitad del DoD que evita que el gate se relaje solo. Los cuatro
    perfiles `nan_api` reales van por HTTP, sin system prompt de agente ni
    permisos de FS: exigirles `readonly_agent` seria ruido, y el ruido es como
    mueren los gates.
    """
    cfg = _cfg(
        {"p_http": {"channel": "api", "write": False, "backend": "b_sin"}},
        {"b_sin": {}},
    )
    assert find_unenforced_pairs(cfg) == [], (
        "un backend sin vector no debe exigir enforcement (over-gating)"
    )


def test_agent_with_readonly_agent_passes():
    """Control positivo: con `readonly_agent` declarado, no hay hallazgo."""
    cfg = _cfg(
        {"p_ok": {"channel": "agent", "write": False, "backend": "b_ok"}},
        {"b_ok": {"readonly_agent": "auditor"}},
    )
    assert find_unenforced_pairs(cfg) == []


def test_write_true_is_not_gated():
    """Un perfil que NO declara `write: false` no promete nada que enforcear."""
    cfg = _cfg(
        {"p_rw": {"channel": "agent", "write": True, "backend": "b_sin"}},
        {"b_sin": {}},
    )
    assert find_unenforced_pairs(cfg) == []


def test_undeclared_backend_is_reported_not_silently_passed():
    """Un backend ausente de `backends` se REPORTA, no se da por bueno.

    Sin esto, un typo en `backend:` convertiria el gate en verde mudo -- la
    misma clase de fallo que el ticket denuncia (un guard que no encuentra su
    objeto y pasa).
    """
    cfg = _cfg(
        {"p_typo": {"channel": "agent", "write": False, "backend": "no_existe"}},
        {"b_ok": {"readonly_agent": "auditor"}},
    )
    pairs = find_unenforced_pairs(cfg)
    assert len(pairs) == 1
    assert pairs[0]["backend_declared"] is False


def test_cli_exit_1_on_orphan_and_0_when_clean(tmp_path, capsys):
    """El CLI mapea hallazgo -> exit 1 y limpio -> exit 0."""
    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps(
            _cfg(
                {"p": {"channel": "agent", "write": False, "backend": "b"}},
                {"b": {}},
            )
        ),
        encoding="utf-8",
    )
    assert main(["--config", str(bad)]) == 1
    assert "p" in capsys.readouterr().err

    good = tmp_path / "good.json"
    good.write_text(
        json.dumps(
            _cfg(
                {"p": {"channel": "agent", "write": False, "backend": "b"}},
                {"b": {"readonly_agent": "auditor"}},
            )
        ),
        encoding="utf-8",
    )
    assert main(["--config", str(good)]) == 0


def test_unreadable_config_fails_closed(tmp_path):
    """No poder LEER la config no es estar limpio: exit 2, nunca 0."""
    assert main(["--config", str(tmp_path / "no_existe.json")]) == 2


def test_check_is_wired_into_closeout(tmp_path, monkeypatch):
    """(3) CABLEADO: el gate se INVOCA desde `run_preflight_check` en closeout.

    Es la asercion que lo separa de una norma. Mutation: quitar la llamada de
    `run_preflight_check` deja `llamado` en False, sin que ningun otro test de
    este fichero se entere -- comportamiento y cableado se miden por separado.
    """
    import scripts.prepush_check as pc

    llamado = {"v": False}

    def _spy(root):
        llamado["v"] = True
        return pc.CheckResult(name="spy", passed=True, output="", is_blocking=False)

    ok = pc.CheckResult(name="stub", passed=True, output="", is_blocking=True)
    for fn in (
        "run_delivery_hygiene_check",
        "run_portable_memory_archive_check",
        "run_ruff_check",
        "run_ruff_format_check",
        "run_agent_controller_validate",
        "run_git_status_check",
        "run_validate_all",
        "run_closeout_reconciliation_check",
        "run_motor_destination_integration_check",
        "run_contract_formation_check",
        "run_backlog_contract_check",
    ):
        monkeypatch.setattr(pc, fn, lambda *a, **k: ok)
    monkeypatch.setattr(pc, "run_agent_write_enforced_check", _spy)

    pc.run_preflight_check(tmp_path, closeout_mode=True)
    assert llamado["v"] is True, (
        "el gate existe pero nadie lo invoca -> norma, no barrera (DoD punto 3)"
    )


def test_warn_is_visible_not_silent(tmp_path, monkeypatch):
    """El WARN se modela `passed=False` + `is_blocking=False`, nunca `passed=True`.

    `run_preflight_check` imprime `result.output` SOLO si `not result.passed`:
    un WARN con `passed=True` seria INVISIBLE, que es la deuda-invisible que
    estos gates combaten. Mutation: cambiar a `passed=True` deja de reportar el
    par huerfano y esta asercion cae.
    """
    import scripts.prepush_check as pc

    monkeypatch.setattr(
        pc,
        "_MOTOR_ROOT",
        tmp_path,
    )
    cfg = tmp_path / ".agent" / "config"
    cfg.mkdir(parents=True)
    (cfg / "agents.json").write_text(
        json.dumps(
            _cfg(
                {"p_huerfano": {"channel": "agent", "write": False, "backend": "b"}},
                {"b": {}},
            )
        ),
        encoding="utf-8",
    )
    r = pc.run_agent_write_enforced_check(tmp_path)
    assert r.passed is False, "un WARN con passed=True seria invisible en el runner"
    assert r.is_blocking is False, "la deuda es PREEXISTENTE: avisa, no bloquea"
    assert "p_huerfano" in r.output, (
        f"debe nombrar el par, no decir 'hay deuda': {r.output}"
    )


def test_dynamic_check_wired_into_preflight_runner(tmp_path, monkeypatch):
    """WOT-2026-086 (DEC-086P10-001): `run_agent_write_enforced_check` tambien
    corre la comprobacion DINAMICA cuando el `readonly_agent` estatico ya paso.

    Mutation que aisla la rama: si el runner deja de llamar a
    `find_dynamic_unenforced_pairs`, este test deja de detectar el agente
    ausente y cae.
    """
    import scripts.check_agent_write_enforced as cawe
    import scripts.prepush_check as pc

    monkeypatch.setattr(pc, "_MOTOR_ROOT", tmp_path)
    cfg = tmp_path / ".agent" / "config"
    cfg.mkdir(parents=True)
    (cfg / "agents.json").write_text(
        json.dumps(
            _cfg(
                {
                    "p_destino": {
                        "channel": "agent",
                        "write": False,
                        "backend": "b_opencode",
                        "repo_scope": "destino",
                    }
                },
                {"b_opencode": {"executable": "opencode", "readonly_agent": "auditor"}},
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        cawe, "_list_agents", lambda executable, cwd: ["build", "manager"]
    )
    project_root = tmp_path / "destino"
    project_root.mkdir()

    r = pc.run_agent_write_enforced_check(project_root)
    assert r.passed is False, (
        "el agente declarado ausente del cwd real debe verse: la restriccion "
        f"era decorativa aunque la estatica pasara: {r.output}"
    )
    assert "auditor" in r.output
    assert r.is_blocking is True, (
        "bucle adversarial WOT-2026-086 (BA30/BA05, CRITICO): esto NO es deuda "
        "preexistente como el WARN estatico -- es un vector de escritura real "
        "confirmado; dejarlo pasar como WARN permitiria el push con la barrera "
        "rota"
    )


def test_dynamic_check_cli_error_never_blocks(tmp_path, monkeypatch):
    """Bucle adversarial WOT-2026-086, SEGUNDA RONDA (sobre el commit que ya
    tenia el fix de arriba): 5/5 lentes convergieron en que este caso SI
    bloqueaba, contradiciendo la propia politica documentada en el commit
    ("medicion fallida no es vector confirmado").

    Causa raiz medida: `find_dynamic_unenforced_pairs` NUNCA propaga la
    excepcion de `_list_agents` -- la captura internamente y la mete en
    `dyn_pairs` con clave `error`. El `try/except` de
    `run_agent_write_enforced_check` (que solo atrapa una excepcion que ya no
    llega) era CODIGO MUERTO, y `dyn_pairs` no vacio se mapeaba entero a
    `is_blocking=True` sin mirar si el elemento traia `error`.

    Mutation que aisla la rama: si el runner deja de distinguir `error` de
    agente-ausente-confirmado (vuelve a tratar TODO `dyn_pairs` como
    confirmado), este test cae porque `is_blocking` pasa a `True`.
    """
    import scripts.check_agent_write_enforced as cawe
    import scripts.prepush_check as pc

    monkeypatch.setattr(pc, "_MOTOR_ROOT", tmp_path)
    cfg = tmp_path / ".agent" / "config"
    cfg.mkdir(parents=True)
    (cfg / "agents.json").write_text(
        json.dumps(
            _cfg(
                {
                    "p_destino": {
                        "channel": "agent",
                        "write": False,
                        "backend": "b_opencode",
                        "repo_scope": "destino",
                    }
                },
                {"b_opencode": {"executable": "opencode", "readonly_agent": "auditor"}},
            )
        ),
        encoding="utf-8",
    )

    def _boom(executable, cwd):
        raise FileNotFoundError("opencode: no such file or directory")

    monkeypatch.setattr(cawe, "_list_agents", _boom)
    project_root = tmp_path / "destino"
    project_root.mkdir()

    r = pc.run_agent_write_enforced_check(project_root)
    assert r.passed is False, "una medicion fallida sigue siendo visible (no OK mudo)"
    assert r.is_blocking is False, (
        "CLI ausente/roto es MEDICION FALLIDA, no vector confirmado -- "
        f"bloquear aqui rompe pushes legitimos en maquinas sin opencode: {r.output}"
    )
    assert "opencode" in r.output


def test_dynamic_check_confirmed_agent_blocks_even_with_a_measurement_failure(
    tmp_path, monkeypatch
):
    """Control: si HAY un agente confirmado ausente Y ADEMAS otro perfil no se
    pudo medir, el bloqueo por el confirmado no debe degradarse a WARN."""
    import scripts.check_agent_write_enforced as cawe
    import scripts.prepush_check as pc

    monkeypatch.setattr(pc, "_MOTOR_ROOT", tmp_path)
    cfg = tmp_path / ".agent" / "config"
    cfg.mkdir(parents=True)
    (cfg / "agents.json").write_text(
        json.dumps(
            _cfg(
                {
                    "p_confirmado": {
                        "channel": "agent",
                        "write": False,
                        "backend": "b_a",
                        "repo_scope": "destino",
                    },
                    "p_sin_medir": {
                        "channel": "agent",
                        "write": False,
                        "backend": "b_b",
                        "repo_scope": "destino",
                    },
                },
                {
                    "b_a": {"executable": "a_exe", "readonly_agent": "auditor"},
                    "b_b": {"executable": "b_exe", "readonly_agent": "auditor"},
                },
            )
        ),
        encoding="utf-8",
    )

    def _fake_list(executable, cwd):
        if executable == "a_exe":
            return ["build", "manager"]  # confirmado: auditor ausente
        raise TimeoutError("b_exe no respondio")

    monkeypatch.setattr(cawe, "_list_agents", _fake_list)
    project_root = tmp_path / "destino"
    project_root.mkdir()

    r = pc.run_agent_write_enforced_check(project_root)
    assert r.is_blocking is True, "un confirmado real no se diluye por otro sin medir"
    assert "p_confirmado" in r.output
    assert "p_sin_medir" in r.output, "la medicion fallida se reporta, no se silencia"


def test_dynamic_check_passes_when_agent_is_present(tmp_path, monkeypatch):
    """Control positivo: con el agente presente en el listado real, no hay WARN
    dinamico (el estatico sigue siendo el unico que puede fallar)."""
    import scripts.check_agent_write_enforced as cawe
    import scripts.prepush_check as pc

    monkeypatch.setattr(pc, "_MOTOR_ROOT", tmp_path)
    cfg = tmp_path / ".agent" / "config"
    cfg.mkdir(parents=True)
    (cfg / "agents.json").write_text(
        json.dumps(
            _cfg(
                {
                    "p_destino": {
                        "channel": "agent",
                        "write": False,
                        "backend": "b_opencode",
                        "repo_scope": "destino",
                    }
                },
                {"b_opencode": {"executable": "opencode", "readonly_agent": "auditor"}},
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        cawe, "_list_agents", lambda executable, cwd: ["build", "auditor", "manager"]
    )
    # Mockear _agent_permission_rules para que no ejecute subprocess contra el
    # backend real. Lista REALISTA (como la medida 2026-10-25 para `auditor`):
    # la generica allow-all SIEMPRE va primero, las especificas la sobreescriben.
    monkeypatch.setattr(
        cawe,
        "_agent_permission_rules",
        lambda executable, cwd, agent_name: [
            {"permission": "*", "action": "deny", "pattern": "*"}
        ],
    )
    project_root = tmp_path / "destino"
    project_root.mkdir()

    r = pc.run_agent_write_enforced_check(project_root)
    assert r.passed is True
    assert r.is_blocking is False


class TestNativeSandboxCountsAsEnforcement:
    """Un sandbox nativo del CLI acredita `write: false` (incidente 2026-08-05).

    Contexto medido: una lente `codex` con `write: false` ESCRIBIO en el
    workspace de otra sesion -- reescribio `work_plan.md`, `TURN.md`, `STATE.md`
    y `.session_state.json`. La restriccion era DECORATIVA porque `codex` no
    declara `readonly_agent` (mecanismo de opencode) y nadie miraba otra forma.

    La leccion, y por eso hay tests para AMBAS formas: la lente no fallo por
    inestabilidad, fallo por encargo mal acotado. GLM, sin permisos, ABORTA;
    codex, con permisos, ACTUA. El encargo malo es el mismo; el dano, no.
    """

    def test_codex_style_sandbox_flag_is_accepted(self):
        backend = {"args": ["exec", "--skip-git-repo-check", "--sandbox", "read-only"]}
        assert has_native_sandbox(backend) is True

    def test_short_sandbox_flag_is_accepted(self):
        assert has_native_sandbox({"args": ["exec", "-s", "read-only"]}) is True

    def test_write_capable_sandbox_modes_are_rejected(self):
        """`workspace-write` y `danger-full-access` NO son readonly."""
        for mode in ("workspace-write", "danger-full-access"):
            assert has_native_sandbox({"args": ["exec", "--sandbox", mode]}) is False, (
                f"{mode} permite escribir y no puede acreditar write:false"
            )

    def test_bare_sandbox_flag_acredits_nothing(self):
        assert has_native_sandbox({"args": ["exec", "--sandbox"]}) is False

    def test_claude_style_readonly_tool_allowlist_is_accepted(self):
        backend = {"args": ["-p", "--tools", "Read,Grep,Glob"]}
        assert has_native_sandbox(backend) is True

    def test_tool_allowlist_with_a_mutating_tool_is_rejected(self):
        """Una sola herramienta mutadora en la allowlist reabre el vector."""
        for tool in ("Bash", "Edit", "Write", "Task"):
            backend = {"args": ["-p", "--tools", f"Read,Grep,{tool}"]}
            assert has_native_sandbox(backend) is False, (
                f"{tool} puede mutar el arbol: la allowlist no acredita readonly"
            )

    def test_backend_without_any_enforcement_is_reported(self):
        """Control: sin sandbox ni readonly_agent, el par sigue siendo huerfano."""
        config = {
            "backends": {"x": {"args": ["run"]}},
            "ensemble_profiles": {
                "p": {"backend": "x", "channel": "agent", "write": False}
            },
        }
        pairs = find_unenforced_pairs(config)
        assert [p["profile"] for p in pairs] == ["p"]

    def test_real_config_has_no_unenforced_agent_profiles(self):
        """El repo REAL: ningun perfil con vector queda sin enforcement.

        Este es el test que habria cazado el incidente antes de que ocurriera.
        """
        import json
        from pathlib import Path

        root = Path(__file__).resolve().parents[2]
        config = json.loads(
            (root / ".agent" / "config" / "agents.json").read_text(encoding="utf-8")
        )
        pairs = find_unenforced_pairs(config)
        assert pairs == [], (
            f"perfiles con write:false y vector sin enforcement: "
            f"{[p['profile'] for p in pairs]}"
        )


class TestDynamicReadonlyAgentExistence:
    """WOT-2026-086 (DEC-086P10-001): `readonly_agent` DECLARADO no es `readonly_agent`
    QUE EXISTE desde el cwd real de la lente.

    Incidente medido 2026-09-30: `challenger_opencode_glm_5_2` declara
    `readonly_agent: auditor` y `repo_scope: destino`, pero `auditor.md` solo
    vivia en `<motor>/.opencode/agents/`. Con `cwd=<destino>`, `opencode agent
    list` no incluia `auditor` y `opencode run --agent auditor` caia al agente
    por defecto (`build`, con edit+bash). La comprobacion ESTATICA de
    `find_unenforced_pairs` (arriba) pasaba en verde: solo mira si el backend
    DECLARA `readonly_agent`, nunca si existe donde se necesita.
    """

    def test_agent_missing_from_destino_listing_is_reported(self, monkeypatch):
        """El agente declarado NO aparece en el listado del cwd real -> hallazgo.

        Mutation que aisla la rama: si `find_dynamic_unenforced_pairs` deja de
        comparar contra el listado real (o lo da por bueno sin comparar), esta
        lista queda vacia y el test cae.
        """
        from scripts.check_agent_write_enforced import find_dynamic_unenforced_pairs

        config = {
            "ensemble_profiles": {
                "p_destino": {
                    "channel": "agent",
                    "write": False,
                    "backend": "b_opencode",
                    "repo_scope": "destino",
                }
            },
            "backends": {
                "b_opencode": {"executable": "opencode", "readonly_agent": "auditor"}
            },
        }

        def _fake_list(executable, cwd):
            # Simula el listado REAL medido: el destino no tiene `auditor`.
            if str(cwd) == str(destino):
                return ["build", "compaction", "explore", "general", "plan", "manager"]
            return ["build", "compaction", "auditor", "builder", "manager"]

        import scripts.check_agent_write_enforced as cawe

        motor = "C:/fake/motor"
        destino = "C:/fake/destino"
        monkeypatch.setattr(cawe, "_list_agents", _fake_list)
        pairs = find_dynamic_unenforced_pairs(
            config, motor_root=motor, project_root=destino
        )
        assert len(pairs) == 1, f"el agente ausente en destino debe detectarse: {pairs}"
        assert pairs[0]["profile"] == "p_destino"
        assert pairs[0]["missing_agent"] == "auditor"
        assert pairs[0]["cwd"] == destino

    def test_agent_present_in_destino_listing_passes(self, monkeypatch):
        """Control positivo: si el agente SI aparece en el listado real, no hay hallazgo."""
        import scripts.check_agent_write_enforced as cawe
        from scripts.check_agent_write_enforced import find_dynamic_unenforced_pairs

        config = {
            "ensemble_profiles": {
                "p_destino": {
                    "channel": "agent",
                    "write": False,
                    "backend": "b_opencode",
                    "repo_scope": "destino",
                }
            },
            "backends": {
                "b_opencode": {"executable": "opencode", "readonly_agent": "auditor"}
            },
        }
        monkeypatch.setattr(
            cawe,
            "_list_agents",
            lambda executable, cwd: ["build", "auditor", "manager"],
        )
        # _agent_permission_rules llama subprocess.run directo; hay que
        # mockearlo para que no intente ejecutar el backend real. Lista
        # REALISTA (genérica allow-all primero, especificas que la
        # sobreescriben despues -- formato medido 2026-10-25).
        monkeypatch.setattr(
            cawe,
            "_agent_permission_rules",
            lambda executable, cwd, agent_name: [
                {"permission": "*", "action": "deny", "pattern": "*"}
            ],
        )
        pairs = find_dynamic_unenforced_pairs(
            config, motor_root="C:/fake/motor", project_root="C:/fake/destino"
        )
        assert pairs == []

    def test_profile_without_repo_scope_destino_checks_motor_cwd(self, monkeypatch):
        """Un perfil SIN `repo_scope: destino` se comprueba contra el cwd del motor.

        `resolve_lens_repo_root` (ya existente) decide el cwd real; esta funcion
        no debe re-implementar esa resolucion, solo consumirla.
        """
        import scripts.check_agent_write_enforced as cawe
        from scripts.check_agent_write_enforced import find_dynamic_unenforced_pairs

        config = {
            "ensemble_profiles": {
                "p_motor": {"channel": "agent", "write": False, "backend": "b_opencode"}
            },
            "backends": {
                "b_opencode": {"executable": "opencode", "readonly_agent": "auditor"}
            },
        }
        seen_cwds = []

        def _fake_list(executable, cwd):
            seen_cwds.append(str(cwd))
            return ["build", "auditor", "manager"]

        monkeypatch.setattr(cawe, "_list_agents", _fake_list)
        # mockear _agent_permission_rules para que no ejecute subprocess
        # contra el backend real. Lista REALISTA (ver test anterior).
        monkeypatch.setattr(
            cawe,
            "_agent_permission_rules",
            lambda executable, cwd, agent_name: [
                {"permission": "*", "action": "deny", "pattern": "*"}
            ],
        )
        pairs = find_dynamic_unenforced_pairs(
            config, motor_root="C:/fake/motor", project_root="C:/fake/destino"
        )
        assert pairs == []
        assert seen_cwds == ["C:/fake/motor"], (
            f"sin repo_scope:destino debe consultar el motor, no el destino: {seen_cwds}"
        )

    def test_list_agents_raises_on_nonzero_returncode(self, monkeypatch):
        """Bucle adversarial WOT-2026-086 (5/5 lentes, BA13/BA24/BA30/BA05 con
        severidad CRITICO/ALTO): un CLI que falla (rc!=0) NO debe parsearse
        como listado valido. Un mensaje de error en stdout podria contener por
        casualidad el nombre del agente buscado y producir un FALSO OK del
        gate de seguridad.

        Mutation: quitar la comprobacion de `returncode` hace que este test
        falle (el nombre del agente en el "mensaje de error" se colaria como
        listado valido en vez de lanzar).
        """
        import pytest
        import scripts.check_agent_write_enforced as cawe

        class _FailingProc:
            returncode = 1
            stdout = "auditor: agent not found in this directory\n"
            stderr = "error: unknown command"

        monkeypatch.setattr(cawe.subprocess, "run", lambda *a, **k: _FailingProc())
        with pytest.raises(RuntimeError, match="rc=1"):
            cawe._list_agents("opencode", "C:/fake/destino")

    def test_list_agents_parses_stdout_on_success(self, monkeypatch):
        """Control positivo: con rc=0 el parseo normal sigue funcionando."""
        import scripts.check_agent_write_enforced as cawe

        class _OkProc:
            returncode = 0
            stdout = "build (primary)\nauditor (primary)\nmanager (primary)\n"
            stderr = ""

        monkeypatch.setattr(cawe.subprocess, "run", lambda *a, **k: _OkProc())
        names = cawe._list_agents("opencode", "C:/fake/motor")
        assert names == ["build", "auditor", "manager"]

    def test_listing_command_failure_is_reported_not_silently_passed(self, monkeypatch):
        """Si `_list_agents` no puede ejecutarse (CLI ausente, error), se reporta,
        nunca se da por bueno en silencio (misma disciplina fail-closed del resto
        del gate)."""
        import scripts.check_agent_write_enforced as cawe
        from scripts.check_agent_write_enforced import find_dynamic_unenforced_pairs

        config = {
            "ensemble_profiles": {
                "p_destino": {
                    "channel": "agent",
                    "write": False,
                    "backend": "b_opencode",
                    "repo_scope": "destino",
                }
            },
            "backends": {
                "b_opencode": {"executable": "opencode", "readonly_agent": "auditor"}
            },
        }

        def _boom(executable, cwd):
            raise OSError("opencode no encontrado")

        monkeypatch.setattr(cawe, "_list_agents", _boom)
        pairs = find_dynamic_unenforced_pairs(
            config, motor_root="C:/fake/motor", project_root="C:/fake/destino"
        )
        assert len(pairs) == 1
        assert pairs[0]["missing_agent"] == "auditor"
        assert "error" in pairs[0]

    def test_static_pass_with_dynamic_fail_is_caught_by_cli(
        self, tmp_path, monkeypatch
    ):
        """Extremo a extremo: la barrera ESTATICA da verde (declara readonly_agent)
        pero la DINAMICA (agente ausente del cwd real) hace fallar el CLI.

        Es exactamente el incidente medido: `find_unenforced_pairs` solo mira si
        se DECLARA; el nuevo paso dinamico mira si EXISTE donde hace falta.
        """
        import scripts.check_agent_write_enforced as cawe

        cfg_path = tmp_path / "agents.json"
        cfg_path.write_text(
            json.dumps(
                {
                    "ensemble_profiles": {
                        "p_destino": {
                            "channel": "agent",
                            "write": False,
                            "backend": "b_opencode",
                            "repo_scope": "destino",
                        }
                    },
                    "backends": {
                        "b_opencode": {
                            "executable": "opencode",
                            "readonly_agent": "auditor",
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        # Estatico: pasaria solo (readonly_agent SI declarado).
        assert (
            find_unenforced_pairs(json.loads(cfg_path.read_text(encoding="utf-8")))
            == []
        )

        monkeypatch.setattr(
            cawe, "_list_agents", lambda executable, cwd: ["build", "manager"]
        )
        rc = cawe.main(
            [
                "--config",
                str(cfg_path),
                "--check-dynamic",
                "--motor-root",
                "C:/fake/motor",
                "--project-root",
                "C:/fake/destino",
            ]
        )
        assert rc == 1, "la barrera dinamica debe fallar aunque la estatica pase"


class TestParseAgentPermissionBlocks:
    """WOT-2026-059j: _parse_agent_permission_blocks convierte el stdout crudo
    de `<backend> agent list` en un dict {nombre_agente: [reglas...]}.

    El formato real medido es una cabecera "nombre (primary)" sin indentacion,
    seguida de un bloque JSON tipo array indentado con espacios, hasta una linea
    `]`.
    """

    def test_parses_real_fixture_format(self):
        """Fixture real medido con este repo: dos agentes, cada uno con reglas."""
        from scripts.check_agent_write_enforced import _parse_agent_permission_blocks

        stdout = (
            "build (primary)\n"
            "  [\n"
            "  {\n"
            '    "permission": "*",\n'
            '    "action": "allow",\n'
            '    "pattern": "*"\n'
            "  },\n"
            "  {\n"
            '    "permission": "doom_loop",\n'
            '    "action": "ask",\n'
            '    "pattern": "*"\n'
            "  }\n"
            "]\n"
            "auditor (primary)\n"
            "  [\n"
            "  {\n"
            '    "permission": "*",\n'
            '    "action": "allow",\n'
            '    "pattern": "*"\n'
            "  }\n"
            "]\n"
        )
        result = _parse_agent_permission_blocks(stdout)
        assert "build" in result
        assert "auditor" in result
        assert len(result["build"]) == 2
        assert result["build"][0]["permission"] == "*"
        assert result["build"][0]["action"] == "allow"
        assert result["build"][0]["pattern"] == "*"
        assert len(result["auditor"]) == 1
        assert result["auditor"][0]["permission"] == "*"

    def test_parses_multiple_rules_in_order(self):
        """El orden de las reglas se preserva tal como aparece en el fixture."""
        from scripts.check_agent_write_enforced import _parse_agent_permission_blocks

        stdout = (
            "build (primary)\n"
            "  [\n"
            '  {"permission": "*", "action": "allow", "pattern": "*"},\n'
            '  {"permission": "edit", "action": "deny", "pattern": "*"}\n'
            "]\n"
        )
        result = _parse_agent_permission_blocks(stdout)
        assert len(result["build"]) == 2
        assert result["build"][0]["permission"] == "*"
        assert result["build"][1]["permission"] == "edit"

    def test_empty_block_gives_empty_list(self):
        """Un bloque sin reglas (solo []) -> lista vacia."""
        from scripts.check_agent_write_enforced import _parse_agent_permission_blocks

        stdout = "solo (primary)\n  []\n"
        result = _parse_agent_permission_blocks(stdout)
        assert result["solo"] == []


class TestAgentPermissionRules:
    """_agent_permission_rules obtiene la lista COMPLETA de reglas de un agente.

    Sustituye a `_first_permission_rule` (que devolvia solo rules[0]). Medido
    2026-10-25: rules[0] es un baseline allow-all UNIVERSAL en el formato real
    de `opencode agent list` (build/plan/manager/auditor lo comparten
    identico), asi que mirar solo la primera regla no distingue un agente
    abierto de uno correctamente restringido -- hace falta la lista entera.
    """

    def test_returns_full_rule_list_for_existing_agent(self, monkeypatch):
        """Devuelve TODAS las reglas del agente pedido, no solo la primera."""
        import scripts.check_agent_write_enforced as cawe

        class _OkProc:
            returncode = 0
            stdout = (
                "build (primary)\n"
                "  [\n"
                '  {"permission": "*", "action": "allow", "pattern": "*"},\n'
                '  {"permission": "edit", "action": "deny", "pattern": "*"}\n'
                "  ]\n"
            )
            stderr = ""

        monkeypatch.setattr(cawe.subprocess, "run", lambda *a, **k: _OkProc())
        rules = cawe._agent_permission_rules("opencode", "C:/fake", "build")
        assert rules == [
            {"permission": "*", "action": "allow", "pattern": "*"},
            {"permission": "edit", "action": "deny", "pattern": "*"},
        ]

    def test_returns_none_for_agent_not_in_listing(self, monkeypatch):
        """El agente no aparece en el listado -> None."""
        import scripts.check_agent_write_enforced as cawe

        class _OkProc:
            returncode = 0
            stdout = 'build (primary)\n  [\n  {"permission": "*", "action": "allow", "pattern": "*"}\n  ]\n'
            stderr = ""

        monkeypatch.setattr(cawe.subprocess, "run", lambda *a, **k: _OkProc())
        rules = cawe._agent_permission_rules("opencode", "C:/fake", "no_existe")
        assert rules is None

    def test_returns_empty_list_for_empty_agent_block(self, monkeypatch):
        """Agente con bloque vacio -> lista vacia (existe, sin reglas)."""
        import scripts.check_agent_write_enforced as cawe

        class _OkProc:
            returncode = 0
            stdout = "solo (primary)\n  []\n"
            stderr = ""

        monkeypatch.setattr(cawe.subprocess, "run", lambda *a, **k: _OkProc())
        rules = cawe._agent_permission_rules("opencode", "C:/fake", "solo")
        assert rules == []

    def test_raises_on_nonzero_returncode(self, monkeypatch):
        """Un CLI que falla (rc!=0) -> RuntimeError, nunca parsea stdout de error."""
        import pytest
        import scripts.check_agent_write_enforced as cawe

        class _FailingProc:
            returncode = 1
            stdout = "auditor: agent not found in this directory\n"
            stderr = "error: unknown command"

        monkeypatch.setattr(cawe.subprocess, "run", lambda *a, **k: _FailingProc())
        with pytest.raises(RuntimeError, match="rc=1"):
            cawe._agent_permission_rules("opencode", "C:/fake", "auditor")

    def test_ignores_nonzero_process_not_parsing_failing_stdout(self, monkeypatch):
        """Bucle adversarial WOT-2026-059j: el stdout de un proceso fallido
        podria contener el nombre del agente buscado por casualidad. Si se
        parsea, se colaria como listado valido -> FALSO OK del gate.

        Mutation: quitar la comprobacion de `returncode` hace que este test
        falle (el nombre del agente en el "mensaje de error" se colaria como
        regla valida).
        """
        import pytest
        import scripts.check_agent_write_enforced as cawe

        class _FailingProc:
            returncode = 1
            stdout = (
                "error: permission denied\n"
                "auditor (primary)\n"
                "  [\n"
                '  {"permission": "*", "action": "allow", "pattern": "*"}\n'
                "  ]\n"
            )
            stderr = "failed"

        monkeypatch.setattr(cawe.subprocess, "run", lambda *a, **k: _FailingProc())
        with pytest.raises(RuntimeError, match="rc=1"):
            cawe._agent_permission_rules("opencode", "C:/fake", "auditor")


class TestPermissiveWritePermissions:
    """_permissive_write_permissions resuelve last-match-wins sobre la lista
    COMPLETA de reglas, restringido a los 4 permisos de escritura vigilados.

    Sustituye a `_is_permissive_rule(rules[0])`. MEDIDO 2026-10-25: el formato
    real de `opencode agent list` pone SIEMPRE `{permission: "*", action:
    "allow", pattern: "*"}` como primera regla -- build, plan, manager Y
    auditor lo comparten identico -- y las reglas que SI restringen
    (edit/bash/task/todowrite: deny) vienen despues, sobreescribiendola. Mirar
    solo rules[0] producia FALSO POSITIVO para TODO agente.
    """

    def test_baseline_only_is_fully_permissive(self):
        """Sin ninguna regla especifica que sobreescriba, el baseline allow-all
        deja los 4 permisos de escritura abiertos -- un agente genuinamente sin
        restriccion SI debe detectarse."""
        from scripts.check_agent_write_enforced import _permissive_write_permissions

        rules = [{"permission": "*", "action": "allow", "pattern": "*"}]
        assert _permissive_write_permissions(rules) == list(NON_READ_PERMISSION_KEYS)

    def test_specific_denies_after_baseline_clear_the_agent(self):
        """Caso REAL medido de `auditor`: baseline allow-all PRIMERO, luego
        edit/bash/task/todowrite: deny -- no debe reportarse nada."""
        from scripts.check_agent_write_enforced import _permissive_write_permissions

        rules = [
            {"permission": "*", "action": "allow", "pattern": "*"},
            {"permission": "doom_loop", "action": "deny", "pattern": "*"},
            {"permission": "read", "action": "allow", "pattern": "*"},
            {"permission": "edit", "action": "deny", "pattern": "*"},
            {"permission": "glob", "action": "allow", "pattern": "*"},
            {"permission": "bash", "action": "deny", "pattern": "*"},
            {"permission": "task", "action": "deny", "pattern": "*"},
            {"permission": "todowrite", "action": "deny", "pattern": "*"},
            {"permission": "webfetch", "action": "deny", "pattern": "*"},
            {"permission": "websearch", "action": "deny", "pattern": "*"},
            {"permission": "codesearch", "action": "deny", "pattern": "*"},
            {"permission": "skill", "action": "deny", "pattern": "*"},
            {"permission": "lsp", "action": "deny", "pattern": "*"},
            {"permission": "question", "action": "deny", "pattern": "*"},
            {"permission": "plan_enter", "action": "deny", "pattern": "*"},
            {"permission": "plan_exit", "action": "deny", "pattern": "*"},
            {"permission": "external_directory", "action": "deny", "pattern": "*"},
        ]
        assert _permissive_write_permissions(rules) == []

    def test_partial_override_names_only_the_open_ones(self):
        """Si solo `edit` tiene override a deny, `bash`/`task`/`todowrite`
        siguen abiertos por el baseline -- deben nombrarse, no silenciarse."""
        from scripts.check_agent_write_enforced import _permissive_write_permissions

        rules = [
            {"permission": "*", "action": "allow", "pattern": "*"},
            {"permission": "edit", "action": "deny", "pattern": "*"},
        ]
        assert _permissive_write_permissions(rules) == [
            key for key in NON_READ_PERMISSION_KEYS if key != "edit"
        ]

    def test_later_rule_overrides_earlier_specific_rule(self):
        """Last-match-wins tambien entre dos reglas ESPECIFICAS del mismo tipo."""
        from scripts.check_agent_write_enforced import _permissive_write_permissions

        rules = [
            {"permission": "edit", "action": "deny", "pattern": "*"},
            {"permission": "edit", "action": "allow", "pattern": "*"},
        ]
        assert _permissive_write_permissions(rules) == list(NON_READ_PERMISSION_KEYS)

    def test_none_or_empty_is_fail_closed_for_every_non_read_permission(self):
        """Sin datos, la ausencia de deny es un fallo para cada permiso."""
        from scripts.check_agent_write_enforced import _permissive_write_permissions

        assert _permissive_write_permissions(None) == list(NON_READ_PERMISSION_KEYS)
        assert _permissive_write_permissions([]) == list(NON_READ_PERMISSION_KEYS)


class TestEffectiveActionIsLastMatchByOrder:
    """WOT-2026-125a: `_effective_action` resuelve por ORDEN (last-match-wins),
    NO por especificidad -- y eso es lo CORRECTO, no un supuesto a corregir.

    Fuente: documentacion de opencode (https://opencode.ai/docs/permissions):
    "Rules are evaluated by pattern match, with the last matching rule
    winning." y "A common pattern is to put the catch-all "*" rule first, and
    more specific rules after it." La doc NO menciona especificidad y NO
    garantiza que `"*"` preceda a las especificas; garantiza que gana la ULTIMA
    que matchea.

    Por eso cambiar a specificity-wins seria una REGRESION: con
    `[edit deny, * allow]` opencode resuelve `allow` (la `*` posterior gana) y
    un resolvedor por especificidad diria `deny` -- un FALSO VERDE del gate
    sobre un agente realmente permisivo. Estos tests fijan la semantica
    documentada contra la funcion REAL.

    NO VERIFICADA: la semantica del binario `opencode` 1.18.35 (solo se
    contrasto la doc y el formato de `agent list`; no hay fuente del binario ni
    prueba de ejecucion real con un agente de orden invertido).
    """

    def test_generic_after_specific_wins_the_inverted_order_case(self):
        """Caso de la fila: `edit: deny` ANTES de `*: allow` => allow (la
        ultima que matchea gana). Mata un resolvedor specificity-wins (diria
        deny) y uno que ignore `*` (diria deny)."""
        from scripts.check_agent_write_enforced import _effective_action

        rules = [
            {"permission": "edit", "action": "deny", "pattern": "*"},
            {"permission": "*", "action": "allow", "pattern": "*"},
        ]
        assert _effective_action(rules, "edit") == "allow"

    def test_specific_after_generic_wins_the_documented_common_order(self):
        """Orden comun documentado: `*: allow` primero, `edit: deny` despues =>
        deny. Mata un resolvedor first-match-wins (diria allow)."""
        from scripts.check_agent_write_enforced import _effective_action

        rules = [
            {"permission": "*", "action": "allow", "pattern": "*"},
            {"permission": "edit", "action": "deny", "pattern": "*"},
        ]
        assert _effective_action(rules, "edit") == "deny"

    def test_wildcard_alone_decides_and_no_match_is_none(self):
        """Un solo match: `*` sola decide (mata 'ignorar `*`'); sin ningun
        match la ausencia de dato es None, no un default inventado."""
        from scripts.check_agent_write_enforced import _effective_action

        assert (
            _effective_action([{"permission": "*", "action": "allow"}], "edit")
            == "allow"
        )
        assert (
            _effective_action([{"permission": "edit", "action": "deny"}], "edit")
            == "deny"
        )
        assert (
            _effective_action([{"permission": "read", "action": "deny"}], "edit")
            is None
        )

    def test_inverted_order_agent_is_reported_permissive_end_to_end(self):
        """El mismo orden invertido, visto desde el gate: el agente se reporta
        permisivo en los 4 permisos de escritura (no se silencia por una
        especifica ANTERIOR a la generica)."""
        from scripts.check_agent_write_enforced import _permissive_write_permissions

        rules = [
            {"permission": "edit", "action": "deny", "pattern": "*"},
            {"permission": "*", "action": "allow", "pattern": "*"},
        ]
        assert _permissive_write_permissions(rules) == list(NON_READ_PERMISSION_KEYS)


class TestPermissiveAgentDetection:
    """WOT-2026-059j: ROJO-a-VERDE -- un readonly_agent declarado y EXISTENTE
    pero con permisos de escritura REALMENTE abiertos debe ser detectado.

    Caso medido ORIGINAL: `challenger_opencode_glm_5_2` (readonly_agent:
    auditor, write: false) tenia como primera regla real {"permission": "*",
    "action": "allow", "pattern": "*"}, identica a la del agente de escritura
    `build`.

    CORRECCION 2026-10-25 (misma sesion, hallazgo NUEVO sobre el mecanismo de
    arriba): esa primera regla allow-all resulto ser UNIVERSAL -- build, plan,
    manager Y auditor la comparten identica en el formato real de `opencode
    agent list` -- asi que mirar solo rules[0] (`_is_permissive_rule`) daba
    FALSO POSITIVO para TODO agente, incluido uno correctamente restringido.
    El fix mira la lista COMPLETA (`_agent_permission_rules` +
    `_permissive_write_permissions`, last-match-wins) para que las reglas
    especificas (edit/bash/task/todowrite: deny) que vienen DESPUES del
    baseline en la misma lista puedan despejar al agente.
    """

    def test_rojo_permissive_agent_detected(self, monkeypatch):
        """Perfil write:false + readonly_agent declarado y EXISTENTE, pero SIN
        ninguna regla especifica que cierre los permisos de escritura ->
        find_dynamic_unenforced_pairs lo lista (agente genuinamente abierto,
        como `build`: solo tiene el baseline allow-all, sin overrides)."""
        import scripts.check_agent_write_enforced as cawe
        from scripts.check_agent_write_enforced import find_dynamic_unenforced_pairs

        config = {
            "ensemble_profiles": {
                "challenger_test": {
                    "channel": "agent",
                    "write": False,
                    "backend": "b_opencode",
                    "repo_scope": "destino",
                }
            },
            "backends": {
                "b_opencode": {
                    "executable": "opencode",
                    "readonly_agent": "auditor",
                }
            },
        }

        def _fake_list_agents(executable, cwd):
            return ["build", "auditor", "manager"]

        def _fake_rules(executable, cwd, agent_name):
            if agent_name == "auditor":
                return [{"permission": "*", "action": "allow", "pattern": "*"}]
            return None

        monkeypatch.setattr(cawe, "_list_agents", _fake_list_agents)
        monkeypatch.setattr(cawe, "_agent_permission_rules", _fake_rules)

        pairs = find_dynamic_unenforced_pairs(
            config, motor_root="C:/fake/motor", project_root="C:/fake/destino"
        )
        assert len(pairs) == 1, f"debe detectar el agente permisivo: {pairs}"
        assert pairs[0]["profile"] == "challenger_test"
        assert pairs[0]["permissive_agent"] == "auditor"
        assert pairs[0]["open_permissions"] == list(NON_READ_PERMISSION_KEYS)

    def test_green_with_baseline_plus_specific_denies_passes(self, monkeypatch):
        """Caso REAL medido 2026-10-25 de `auditor`: baseline allow-all
        PRIMERO (universal en el CLI), edit/bash/task/todowrite: deny
        DESPUES -- no debe generar hallazgo. Este es el caso que la version
        vieja (rules[0] unicamente) marcaba incorrectamente como permisivo."""
        import scripts.check_agent_write_enforced as cawe
        from scripts.check_agent_write_enforced import find_dynamic_unenforced_pairs

        config = {
            "ensemble_profiles": {
                "challenger_test": {
                    "channel": "agent",
                    "write": False,
                    "backend": "b_opencode",
                    "repo_scope": "destino",
                }
            },
            "backends": {
                "b_opencode": {
                    "executable": "opencode",
                    "readonly_agent": "auditor",
                }
            },
        }

        def _fake_list_agents(executable, cwd):
            return ["build", "auditor", "manager"]

        def _fake_rules(executable, cwd, agent_name):
            if agent_name == "auditor":
                return [{"permission": "*", "action": "deny", "pattern": "*"}]
            return None

        monkeypatch.setattr(cawe, "_list_agents", _fake_list_agents)
        monkeypatch.setattr(cawe, "_agent_permission_rules", _fake_rules)

        pairs = find_dynamic_unenforced_pairs(
            config, motor_root="C:/fake/motor", project_root="C:/fake/destino"
        )
        assert pairs == [], (
            f"baseline + overrides especificos de escritura a deny no debe "
            f"generar hallazgo: {pairs}"
        )

    def test_mutation_isolates_branch(self, monkeypatch):
        """Mutation que aisla la rama _permissive_write_permissions: compara
        baseline (sin mock) contra version mutada (-> []) y exige que los
        resultados SEAN DISTINTOS.

        baseline: no mock _permissive_write_permissions -> la implementacion
            real detecta el agente permisivo -> pairs_baseline == [1 hallazgo].
        mutada: monkeypatch _permissive_write_permissions a [] -> si la rama se
            comenta/quita, el resultado es identico a baseline -> test FALLA.
            Con el fix cableado: pairs_mutada == [] (se pierden los permisivos).
        """
        import scripts.check_agent_write_enforced as cawe
        from scripts.check_agent_write_enforced import find_dynamic_unenforced_pairs

        config = {
            "ensemble_profiles": {
                "challenger_test": {
                    "channel": "agent",
                    "write": False,
                    "backend": "b_opencode",
                    "repo_scope": "destino",
                }
            },
            "backends": {
                "b_opencode": {
                    "executable": "opencode",
                    "readonly_agent": "auditor",
                }
            },
        }

        def _fake_list_agents(executable, cwd):
            return ["build", "auditor", "manager"]

        def _fake_rules(executable, cwd, agent_name):
            if agent_name == "auditor":
                return [{"permission": "*", "action": "allow", "pattern": "*"}]
            return None

        monkeypatch.setattr(cawe, "_list_agents", _fake_list_agents)
        monkeypatch.setattr(cawe, "_agent_permission_rules", _fake_rules)

        # PASO 1: baseline SIN mock _permissive_write_permissions.
        pairs_baseline = find_dynamic_unenforced_pairs(
            config, motor_root="C:/fake/motor", project_root="C:/fake/destino"
        )
        assert len(pairs_baseline) == 1, (
            f"baseline debe detectar el agente permisivo: {pairs_baseline}"
        )
        assert pairs_baseline[0]["permissive_agent"] == "auditor"

        # PASO 2: mutacion -- _permissive_write_permissions SIEMPRE [].
        monkeypatch.setattr(cawe, "_permissive_write_permissions", lambda rules: [])

        pairs_mutada = find_dynamic_unenforced_pairs(
            config, motor_root="C:/fake/motor", project_root="C:/fake/destino"
        )
        assert pairs_mutada == [], (
            f"con _permissive_write_permissions forzado a [], no debe haber "
            f"hallazgo: {pairs_mutada}"
        )

        # PASO 3: los resultados SON DISTINTOS -> _permissive_write_permissions
        # es load-bearing. Si se comenta la llamada en
        # find_dynamic_unenforced_pairs, baseline y mutada darian [] y este
        # assert falla.
        assert pairs_baseline != pairs_mutada, (
            "baseline y mutada deben diferir; si son iguales, la rama "
            "_permissive_write_permissions no se ejecuta en "
            "find_dynamic_unenforced_pairs"
        )

    def test_dynamic_cli_fails_with_permissive_agent(
        self, tmp_path, monkeypatch, capsys
    ):
        """Extremo a extremo: el CLI (main con --check-dynamic) retorna 1
        cuando hay un agente permisivo detectado."""
        import scripts.check_agent_write_enforced as cawe

        cfg_path = tmp_path / "agents.json"
        cfg_path.write_text(
            json.dumps(
                {
                    "ensemble_profiles": {
                        "challenger_test": {
                            "channel": "agent",
                            "write": False,
                            "backend": "b_opencode",
                            "repo_scope": "destino",
                        }
                    },
                    "backends": {
                        "b_opencode": {
                            "executable": "opencode",
                            "readonly_agent": "auditor",
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

        def _fake_list_agents(executable, cwd):
            return ["build", "auditor", "manager"]

        def _fake_rules(executable, cwd, agent_name):
            if agent_name == "auditor":
                return [{"permission": "*", "action": "allow", "pattern": "*"}]
            return None

        monkeypatch.setattr(cawe, "_list_agents", _fake_list_agents)
        monkeypatch.setattr(cawe, "_agent_permission_rules", _fake_rules)

        rc = cawe.main(
            [
                "--config",
                str(cfg_path),
                "--check-dynamic",
                "--motor-root",
                "C:/fake/motor",
                "--project-root",
                "C:/fake/destino",
            ]
        )
        assert rc == 1, "el CLI debe fallar con un agente permisivo detectado"
        err = capsys.readouterr().err
        assert "permisiva" in err or "PERMISIVOS" in err, (
            f"el mensaje debe distinguir permisisvo de ausente: {err}"
        )

    def test_mixed_permissive_and_missing_reports_both(self, monkeypatch):
        """Si hay un perfil con agente permisivo y otro con agente ausente,
        ambos se reportan."""
        import scripts.check_agent_write_enforced as cawe
        from scripts.check_agent_write_enforced import find_dynamic_unenforced_pairs

        config = {
            "ensemble_profiles": {
                "p_permissive": {
                    "channel": "agent",
                    "write": False,
                    "backend": "b_a",
                    "repo_scope": "destino",
                },
                "p_missing": {
                    "channel": "agent",
                    "write": False,
                    "backend": "b_b",
                    "repo_scope": "destino",
                },
            },
            "backends": {
                "b_a": {"executable": "opencode", "readonly_agent": "auditor"},
                "b_b": {"executable": "opencode", "readonly_agent": "ghost"},
            },
        }

        def _fake_list_agents(executable, cwd):
            # "ghost" NO aparece en el listado (agente ausente)
            return ["build", "auditor", "manager"]

        def _fake_rules(executable, cwd, agent_name):
            if agent_name == "auditor":
                return [{"permission": "*", "action": "allow", "pattern": "*"}]
            return None

        monkeypatch.setattr(cawe, "_list_agents", _fake_list_agents)
        monkeypatch.setattr(cawe, "_agent_permission_rules", _fake_rules)

        pairs = find_dynamic_unenforced_pairs(
            config, motor_root="C:/fake/motor", project_root="C:/fake/destino"
        )
        assert len(pairs) == 2
        profiles = {p["profile"] for p in pairs}
        assert "p_permissive" in profiles
        assert "p_missing" in profiles
        permissive_pair = next(p for p in pairs if p["profile"] == "p_permissive")
        missing_pair = next(p for p in pairs if p["profile"] == "p_missing")
        assert permissive_pair["permissive_agent"] == "auditor"
        assert permissive_pair["open_permissions"] == list(NON_READ_PERMISSION_KEYS)
        assert missing_pair["missing_agent"] == "ghost"
