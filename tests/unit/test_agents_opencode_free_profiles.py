"""WOT-2026-204a: conformidad del lote de perfiles opencode/*-free (BA261-BA266)."""
# [NON-REVERSE-CLASSICAL: test de contrato nuevo sobre el registro vivo]
#
# Antes: el lote gratuito de la ruta opencode/ no tenia barrera de conformidad:
# una clave duplicada, un nombre con version colada o un campo de clasificacion
# vacio entraria en agents.json sin poner nada en rojo.
# Durante: tres chequeos derivados del config REAL (m-02 claves, m-03 forma de
# nombre, m-04 clasificacion) mas controles positivos por mutacion sobre una
# copia en memoria (el arbol vivo nunca se muta).
# Despues: cada defecto sale como hallazgo legible; solo una lista vacia esta
# en verde. La URL fuente del laboratorio de cada modelo se fija aqui como
# contrato del lote (ficha WOT-2026-204a s.2).

from __future__ import annotations

import copy
import json
import re
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import check_ensemble_registry_classification as cec  # noqa: E402


CONFIG_PATH = PROJECT_ROOT / ".agent" / "config" / "agents.json"
BASE_COMMIT = "c3438d748aea099e397431eb9fa885fcd8a7fce1"

# Lote medido por la celda IM (smoke ida/vuelta rc 0 el 2026-11-20 + fuente de
# lab). generation = ordinal de version dentro de (family, tier) siguiendo las
# claves previas del registro (v4.1 -> 2, 3.5 -> 2, primera version -> 1).
LOT: dict[str, dict[str, object]] = {
    "opencode/deepseek-v4.1-flash-free": {
        "key": "BA261",
        "profile": "challenger_opencode_deepseek_free",
        "lab": "DeepSeek",
        "family": "deepseek",
        "tier": "flash",
        "generation": 2,
        "source": "https://openrouter.ai/deepseek/deepseek-v4.1-flash",
    },
    "opencode/hy4-flash-free": {
        "key": "BA262",
        "profile": "challenger_opencode_hy_free",
        "lab": "Tencent",
        "family": "hy",
        "tier": "flash",
        "generation": 1,
        "source": "https://openrouter.ai/tencent/hy4-flash",
    },
    "opencode/longcat-2.5-free": {
        "key": "BA263",
        "profile": "challenger_opencode_longcat_free",
        "lab": "Meituan",
        "family": "longcat",
        "tier": "full",
        "generation": 1,
        "source": "familia LongCat (Meituan): https://openrouter.ai/meituan/longcat-2.0",
    },
    "opencode/mimo-v2.6-flash-free": {
        "key": "BA264",
        "profile": "challenger_opencode_mimo_free",
        "lab": "Xiaomi",
        "family": "mimo",
        "tier": "flash",
        "generation": 1,
        "source": "https://openrouter.ai/xiaomi/mimo-v2.6-flash",
    },
    "opencode/nemotron-3.5-lightning-free": {
        "key": "BA265",
        "profile": "challenger_opencode_nemotron_lightning_free",
        "lab": "NVIDIA",
        "family": "nemotron",
        "tier": "full",
        "generation": 2,
        "source": "https://openrouter.ai/nvidia/nemotron-3.5-lightning",
    },
    "opencode/nemotron-3.5-super-vl-free": {
        "key": "BA266",
        "profile": "challenger_opencode_nemotron_super_vl_free",
        "lab": "NVIDIA",
        "family": "nemotron",
        "tier": "full",
        "generation": 2,
        "source": "https://openrouter.ai/nvidia/nemotron-3.5-super-vl",
    },
}
NEW_KEYS = {str(spec["key"]) for spec in LOT.values()}
NEW_PROFILES = {str(spec["profile"]) for spec in LOT.values()}
# WOT-2026-222a adds two non-free OpenCode nan registry keys in the same
# agents.json; they are counted here but remain outside this free-profile LOT.
ADDITIONAL_TICKET_KEYS = {"BA267", "BA268"}
# Forma rol_backend_familia[_caracteristica] (ensemble_profile_nomenclature.md):
# solo minusculas; un digitos en cualquier segmento (version o tamano colado,
# p.ej. ..._v41 o ..._40b) la rechaza; hasta 3 segmentos tras la familia
# (free; lightning_free; super_vl_free).
PROFILE_NAME_RE = re.compile(r"^(proposer|challenger)_[a-z]+_[a-z]+(?:_[a-z]+){0,3}$")


def _load(path: Path = CONFIG_PATH) -> dict:
    """Carga un agents.json (el vivo por defecto) como dict."""
    return json.loads(path.read_text(encoding="utf-8"))


def _baseline_keys() -> set[str]:
    """Claves del registro en el commit base del ticket (medicion, no criterio).

    Before: m-02 debe separar las claves nuevas de las 65 previas sin
        hardcodear la lista entera.
    During: lee .agent/config/agents.json del commit BASE_COMMIT con git show
        y devuelve su conjunto de claves.
    After: el conjunto base; si git falla el error es ruidoso (nunca verde vacio).
    """
    raw = subprocess.check_output(
        ["git", "show", f"{BASE_COMMIT}:.agent/config/agents.json"],
        cwd=PROJECT_ROOT,
        text=True,
    )
    cfg = json.loads(raw)
    return set(cfg["ensemble_registry"]["backend_keys"])


def m02_findings(cfg: dict) -> list[str]:
    """m-02: claves nuevas presentes, unicas y sin reutilizar claves previas.

    Before: `cfg` es un agents.json (vivo o copia mutada); las claves nuevas
        son las que no existen en el commit base.
    During: compara el conjunto nuevo con el lote BA261..BA266, busca
        interseccion con las previas y exige total == base + lote (una clave
        repetida desplaza otra y rompe el conteo).
    After: lista de hallazgos legibles; vacia = conforme (m-02).
    """
    findings: list[str] = []
    backend_keys = cfg.get("ensemble_registry", {}).get("backend_keys", {})
    if not isinstance(backend_keys, dict):
        return ["m-02: ensemble_registry.backend_keys ausente o no es objeto"]
    baseline = _baseline_keys()
    new = set(backend_keys) - baseline
    expected_new = NEW_KEYS | ADDITIONAL_TICKET_KEYS
    if new != expected_new:
        findings.append(
            f"m-02: claves nuevas {sorted(new)} != lote esperado {sorted(expected_new)}"
        )
    collision = sorted(new & baseline)
    if collision:
        findings.append(f"m-02: claves nuevas reutilizan claves previas: {collision}")
    expected_total = len(baseline) + len(expected_new)
    if len(backend_keys) != expected_total:
        findings.append(
            f"m-02: total de claves {len(backend_keys)} != base+lote "
            f"({expected_total}): clave duplicada o faltante"
        )
    return findings


def m03_findings(cfg: dict) -> list[str]:
    """m-03: todo perfil que referencia una clave del lote cumple la forma.

    Before: `cfg` es un agents.json (vivo o copia mutada); el lote se detecta
        por backend_key en NEW_KEYS, no por nombre (para que un renombrado
        con la version colada no se esconda cambiando la llave del dict).
    During: exige que el conjunto de perfiles del lote sea exactamente el
        esperado y que cada nombre case con PROFILE_NAME_RE.
    After: lista de hallazgos legibles; vacia = conforme (m-03).
    """
    findings: list[str] = []
    profiles = cfg.get("ensemble_profiles", {})
    if not isinstance(profiles, dict):
        return ["m-03: ensemble_profiles ausente"]
    lot_profiles = {
        name: prof
        for name, prof in profiles.items()
        if isinstance(prof, dict) and prof.get("backend_key") in NEW_KEYS
    }
    if set(lot_profiles) != NEW_PROFILES:
        findings.append(
            f"m-03: perfiles del lote {sorted(lot_profiles)} != esperados "
            f"{sorted(NEW_PROFILES)}"
        )
    for name in lot_profiles:
        if not PROFILE_NAME_RE.match(name):
            findings.append(  # noqa: PERF401
                f"m-03: nombre fuera de forma (version/tamano o digitos): {name!r}"
            )
    return findings


def m04_findings(cfg: dict) -> list[str]:  # noqa: C901
    """m-04: clasificacion completa y activa de cada clave del lote.

    Before: `cfg` es un agents.json (vivo o copia mutada); por cada modelo del
        lote localiza su clave y su perfil.
    During: exige lab/family/tier/generation/source no vacios, status active,
        valores exactos del contrato, lab dentro de classification.labs, tier
        igual al que dicta la regla del validador real (cec.tier_by_rule),
        generation entero >= 1 y paridad perfil<->clave (backend, model,
        backend_key, channel agent y write false: es una lente).
    After: lista de hallazgos legibles; vacia = conforme (m-04).
    """
    findings: list[str] = []
    registry = cfg.get("ensemble_registry", {})
    backend_keys = registry.get("backend_keys", {})
    labs = registry.get("classification", {}).get("labs", [])
    profiles = cfg.get("ensemble_profiles", {})
    for model, spec in LOT.items():
        key = str(spec["key"])
        ent = backend_keys.get(key)
        if not isinstance(ent, dict):
            findings.append(f"m-04: clave {key} ausente para {model}")
            continue
        if ent.get("model") != model:
            findings.append(f"m-04: {key}.model={ent.get('model')!r} != {model!r}")
        if ent.get("status") != "active":
            findings.append(f"m-04: {key}.status={ent.get('status')!r} != 'active'")
        for field in ("lab", "family", "tier", "generation", "source"):
            value = ent.get(field)
            if value is None or (isinstance(value, str) and not value.strip()):
                findings.append(f"m-04: {key}.{field} vacio")
        for field in ("lab", "family", "tier", "generation"):
            if field in spec and ent.get(field) != spec[field]:
                findings.append(  # noqa: PERF401
                    f"m-04: {key}.{field}={ent.get(field)!r} != esperado "
                    f"{spec[field]!r}"
                )
        if ent.get("lab") not in labs:
            findings.append(
                f"m-04: {key}.lab={ent.get('lab')!r} fuera de classification.labs"
            )
        tier_rule = cec.tier_by_rule(ent.get("model"))
        if ent.get("tier") != tier_rule:
            findings.append(
                f"m-04: {key}.tier={ent.get('tier')!r} contradice la regla del "
                f"validador para {model!r} (da {tier_rule!r})"
            )
        gen = ent.get("generation")
        if isinstance(gen, bool) or not isinstance(gen, int) or gen < 1:
            findings.append(f"m-04: {key}.generation={gen!r} debe ser entero >= 1")
        prof = profiles.get(str(spec["profile"]))
        if not isinstance(prof, dict):
            findings.append(f"m-04: perfil {spec['profile']} ausente para {key}")
            continue
        if prof.get("backend_key") != key:
            findings.append(f"m-04: {spec['profile']}.backend_key != {key}")
        if prof.get("model") != model:
            findings.append(f"m-04: {spec['profile']}.model != {model!r}")
        if prof.get("backend") != "opencode" or prof.get("channel") != "agent":
            findings.append(
                f"m-04: {spec['profile']} con backend/channel != opencode/agent"
            )
        if prof.get("write") is not False:
            findings.append(f"m-04: {spec['profile']}.write debe ser false (lente)")
    return findings


def test_m02_new_keys_are_unique_and_start_at_ba261():
    """m-02: el lote real no colisiona ni reutiliza claves de las 65 previas."""
    assert m02_findings(_load()) == []


def test_m02_control_reused_key_on_copy_is_caught():
    """Control positivo: copia con BA261 reutilizando la clave previa BA06 -> rojo."""
    cfg = copy.deepcopy(_load())
    keys = cfg["ensemble_registry"]["backend_keys"]
    if "BA261" in keys:
        keys["BA06"] = keys.pop("BA261")
    findings = m02_findings(cfg)
    assert findings, "la mutacion clave-repetida debe producir hallazgos m-02"


def test_m03_new_profile_names_match_form():
    """m-03: los 6 perfiles del lote cumplen rol_backend_familia[_caracteristica]."""
    assert m03_findings(_load()) == []


def test_m03_control_version_suffix_on_copy_is_caught():
    """Control positivo: copia con el sufijo ..._v41_free en un nombre -> rojo."""
    cfg = copy.deepcopy(_load())
    profiles = cfg["ensemble_profiles"]
    prof = profiles.pop("challenger_opencode_deepseek_free", None)
    if prof is not None:
        profiles["challenger_opencode_deepseek_v41_free"] = prof
    findings = m03_findings(cfg)
    assert findings, "la mutacion con version en el sufijo debe producir hallazgos m-03"


def test_m04_classification_complete_and_active():
    """m-04: lab/family/tier/generation/source no vacios y status active en el lote."""
    assert m04_findings(_load()) == []


def test_m04_control_empty_lab_on_copy_is_caught():
    """Control positivo: copia con lab vacio en BA261 -> rojo."""
    cfg = copy.deepcopy(_load())
    key = cfg.get("ensemble_registry", {}).get("backend_keys", {}).get("BA261")
    if isinstance(key, dict):
        key["lab"] = ""
    findings = m04_findings(cfg)
    assert findings, "la mutacion lab-vacio debe producir hallazgos m-04"
