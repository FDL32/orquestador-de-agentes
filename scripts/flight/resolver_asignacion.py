"""Carga y resuelve la declaracion de asignaciones del vuelo."""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path


NIVELES = ("base", "medio", "alto", "premium")
EFFORT_NORMALIZADO = {
    "low": "bajo",
    "medium": "medio",
    "high": "alto",
    "xhigh": "maximo",
    "max": "maximo",
}
UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)
PUESTOS = (
    "co",
    "co_subagentes",
    "supervisora",
    "im.builder",
    "im.revisor",
    "im.v1",
    "im.subagentes",
    "tr.triador",
    "tr.revisor",
    "tr.subagentes",
    "lentes_p34",
    "lente_de_cierre",
    "bucle_retro",
)
CLAVES_NO_DERIVADAS = {
    "role_models.REVISOR": "mimo lo fija test_agents_json_model_levels y role_mapping.revisor lo ata (test_loop_registry_coherence) y luna chocaria con check_role_models_distinct",
    "role_models.MANAGER": "null por contrato 098b / sin puesto equivalente",
    "role_assignments.MANAGER": "null por contrato 098b / sin puesto equivalente",
    "role_assignments.SUPERVISOR": "default es un centinela",
}
DEFAULT_AGENTS_JSON = (
    Path(__file__).resolve().parents[2] / ".agent" / "config" / "agents.json"
)
ROTACION_DUENA = "coordinadora del vuelo"


def normalize_effort(value):
    """Before: ``value`` es el esfuerzo de un candidato. During: traduce alias del proveedor. After: devuelve vocabulario de registro o el valor original."""
    if not isinstance(value, str):
        return value
    return EFFORT_NORMALIZADO.get(value.casefold(), value)


class AsignacionError(ValueError):
    """Before: una entrada de asignaciones puede ser invalida. During: se expresa el fallo. After: el llamador recibe un ValueError."""


class SinCandidatoError(AsignacionError):
    """Before: ningun candidato pasa los filtros. During: conserva los descartes. After: expone saltados al llamador."""

    def __init__(self, message, saltados):
        """Before: recibe un mensaje y descartes. During: inicializa la excepcion. After: saltados queda disponible."""
        super().__init__(message)
        self.saltados = saltados


def _require(condition, message):
    """Before: condition representa una invariante. During: la comprueba. After: falla de forma explicita si no se cumple."""
    if not condition:
        raise AsignacionError(message)


def load_declaration(path=DEFAULT_AGENTS_JSON):
    """Before: path apunta a un agents.json. During: lee y valida su declaracion. After: devuelve documento y asignaciones."""
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError) as exc:
        raise AsignacionError(f"declaracion ilegible: {path}") from exc
    _require(isinstance(document, dict), "agents.json no es un objeto")
    assignments = document.get("asignaciones")
    _require(isinstance(assignments, dict), "falta asignaciones")
    _require(
        set(assignments) == set(PUESTOS),
        "asignaciones debe contener exactamente los puestos declarados",
    )
    for post in PUESTOS:
        data = assignments[post]
        _require(isinstance(data, dict), f"puesto invalido: {post}")
        _require(
            isinstance(data.get("candidatos"), list) and data["candidatos"],
            f"candidatos invalidos: {post}",
        )
        _require(data.get("nivel") in NIVELES, f"nivel invalido: {post}")
        refuge = data.get("refugio")
        _require(isinstance(refuge, list), f"refugio invalido: {post}")
        for item in refuge:
            _require(
                isinstance(item, dict)
                and isinstance(item.get("backend_key"), str)
                and isinstance(item.get("cuenta"), str),
                f"refugio invalido: {post}",
            )
        _require(
            isinstance(data.get("orden"), dict) and "messageId" in data["orden"],
            f"orden invalida: {post}",
        )
    return document, assignments


def subtree_hash(asignaciones):
    """Before: asignaciones es un objeto serializable. During: serializa canonicamente y calcula SHA-256. After: devuelve el hash hexadecimal completo."""
    payload = json.dumps(
        asignaciones, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def short_hash(asignaciones):
    """Before: existe una declaracion. During: calcula su hash canonico. After: devuelve sus primeros 16 caracteres."""
    return subtree_hash(asignaciones)[:16]


def _nonempty_string(value, field):
    """Before: value procede de un candidato t3_session. During: valida texto no vacio. After: devuelve value."""
    _require(isinstance(value, str) and bool(value), f"campo invalido: {field}")
    return value


def candidate_info(candidate, backend_keys):
    """Before: candidate es backend_key o t3_session. During: normaliza familia, nivel y lanzamiento. After: devuelve metadatos publicos."""
    _require(isinstance(candidate, dict), "candidato invalido")
    if "backend_key" in candidate:
        key = candidate["backend_key"]
        entry = backend_keys.get(key) if isinstance(backend_keys, dict) else None
        _require(isinstance(entry, dict), f"backend_key desconocido: {key}")
        family = _nonempty_string(entry.get("family"), "family")
        levels = entry.get("niveles", [entry.get("nivel")])
        _require(
            isinstance(levels, list)
            and levels
            and all(level in NIVELES for level in levels),
            f"niveles invalidos: {key}",
        )
        effort = _nonempty_string(entry.get("esfuerzo"), "esfuerzo")
        model = _nonempty_string(entry.get("model"), "model")
        return {
            "tipo": "backend_key",
            "familia": family,
            "nivel_min": min(levels, key=NIVELES.index),
            "niveles": list(levels),
            "esfuerzo": effort,
            "model": model,
            "backend_key": key,
            "backend": _nonempty_string(entry.get("backend"), "backend"),
            "instanceId": None,
            "lanzamiento": {
                "backend_key": key,
                "backend": entry["backend"],
                "model": model,
            },
        }
    _require(candidate.get("tipo") == "t3_session", "tipo de candidato invalido")
    family = _nonempty_string(candidate.get("familia"), "familia")
    level = _nonempty_string(candidate.get("nivel"), "nivel")
    _require(level in NIVELES, "nivel invalido")
    instance = _nonempty_string(candidate.get("instanceId"), "instanceId")
    model = _nonempty_string(candidate.get("model"), "model")
    effort = _nonempty_string(candidate.get("effort"), "effort")
    return {
        "tipo": "t3_session",
        "familia": family,
        "nivel_min": level,
        "niveles": [level],
        "esfuerzo": effort,
        "model": model,
        "backend_key": None,
        "backend": None,
        "instanceId": instance,
        "lanzamiento": {"instanceId": instance, "model": model, "effort": effort},
    }


def effective_orden(puesto_data, candidate):
    """Before: puesto_data y candidate forman una asignacion. During: aplica la precedencia de orden. After: devuelve UUID valido o None."""
    value = (
        candidate.get("orden", puesto_data["orden"]).get("messageId")
        if isinstance(candidate.get("orden", puesto_data["orden"]), dict)
        else None
    )
    return value if isinstance(value, str) and UUID_RE.fullmatch(value) else None


def is_pendiente(puesto_data, candidate):
    """Before: existe una orden efectiva potencial. During: la valida. After: indica si requiere confirmacion."""
    return effective_orden(puesto_data, candidate) is None


def resolve(
    asignaciones, puesto, backend_keys, excluir_familias=(), nivel=None, cuenta=None
):
    """Before: la declaracion y registro de backends estan disponibles. During: filtra en orden los candidatos. After: devuelve la primera resolucion o sus descartes."""
    _require(
        puesto in PUESTOS and puesto in asignaciones, f"puesto desconocido: {puesto}"
    )
    data = asignaciones[puesto]
    allowed = (
        min((data["nivel"], nivel), key=NIVELES.index)
        if nivel is not None
        else data["nivel"]
    )
    excluded = {family.casefold() for family in excluir_familias}
    skipped = []
    for candidate in data["candidatos"]:
        info = candidate_info(candidate, backend_keys)
        if info["familia"].casefold() in excluded:
            skipped.append({"candidato": candidate, "motivo": "familia"})
            continue
        if not any(
            NIVELES.index(item) <= NIVELES.index(allowed) for item in info["niveles"]
        ):
            skipped.append({"candidato": candidate, "motivo": "nivel"})
            continue
        if is_pendiente(data, candidate):
            skipped.append({"candidato": candidate, "motivo": "pendiente_confirmacion"})
            continue
        if (
            cuenta is not None
            and candidate.get("cuenta") is not None
            and candidate.get("cuenta") != cuenta
        ):
            skipped.append({"candidato": candidate, "motivo": "cuenta"})
            continue
        return {
            "puesto": puesto,
            "candidato": candidate,
            "info": info,
            "orden": effective_orden(data, candidate),
            "nivel_puesto": data["nivel"],
            "refugio": data["refugio"],
            "saltados": skipped,
            "rotacion_duena": ROTACION_DUENA,
        }
    motivos = ", ".join(item["motivo"] for item in skipped)
    raise SinCandidatoError(f"sin candidato valido para {puesto}: {motivos}", skipped)


def derive_eligible(asignaciones, config):
    """Before: config contiene perfiles y cobertura. During: filtra lentes_p34 por nivel, perfil y exclusiones. After: devuelve backend_key unicos en orden."""
    backend_keys = config.get("ensemble_registry", {}).get("backend_keys", {})
    profiles = config.get("ensemble_profiles", {})
    profile_keys = {
        item.get("backend_key") for item in profiles.values() if isinstance(item, dict)
    }
    coverage = (
        config.get("ensemble_registry", {})
        .get("eligible_coverage", {})
        .get("MANAGER_REVIEW:repo_motor", {})
    )
    excluded = set(coverage.get("excluded_backend_keys", []))
    allowed = asignaciones["lentes_p34"]["nivel"]
    result = []
    for candidate in asignaciones["lentes_p34"]["candidatos"]:
        key = candidate.get("backend_key")
        if not key or key in result or key in excluded or key not in profile_keys:
            continue
        info = candidate_info(candidate, backend_keys)
        if any(
            NIVELES.index(level) <= NIVELES.index(allowed) for level in info["niveles"]
        ):
            result.append(key)
    return result


def derive_role_models_builder(asignaciones, backend_keys):
    """Before: im.builder tiene candidatos. During: resuelve el primero valido. After: devuelve su modelo."""
    return resolve(asignaciones, "im.builder", backend_keys)["info"]["model"]


def derive_role_assignments_builder(asignaciones, backend_keys):
    """Before: im.builder tiene candidatos backend. During: resuelve el primero valido. After: devuelve su backend."""
    return resolve(asignaciones, "im.builder", backend_keys)["info"]["backend"]


def _parser():
    """Before: se invoca desde main. During: declara argumentos CLI. After: devuelve el parser configurado."""
    parser = argparse.ArgumentParser()
    parser.add_argument("puesto", choices=PUESTOS)
    parser.add_argument("--excluir-familia", action="append", default=[])
    parser.add_argument("--nivel", choices=NIVELES)
    parser.add_argument("--cuenta")
    parser.add_argument("--agents-json", type=Path, default=DEFAULT_AGENTS_JSON)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv=None):
    """Before: recibe argumentos de resolucion. During: carga, resuelve y presenta el resultado. After: devuelve el codigo CLI."""
    args = _parser().parse_args(argv)
    try:
        document, assignments = load_declaration(args.agents_json)
        result = resolve(
            assignments,
            args.puesto,
            document["ensemble_registry"]["backend_keys"],
            args.excluir_familia,
            args.nivel,
            args.cuenta,
        )
    except SinCandidatoError as exc:
        print("; ".join(item["motivo"] for item in exc.saltados), file=sys.stderr)
        return 2
    except (AsignacionError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
        return 3
    output = {
        "puesto": result["puesto"],
        "candidato": result["candidato"],
        "familia": result["info"]["familia"],
        "nivel": result["info"]["nivel_min"],
        "lanzamiento": result["info"]["lanzamiento"],
        "orden": result["orden"],
        "refugio": result["refugio"],
        "saltados": result["saltados"],
        "rotacion_duena": result["rotacion_duena"],
    }
    if args.json:
        print(json.dumps(output, ensure_ascii=True, sort_keys=True))
    else:
        print(
            f"{output['puesto']}: {output['familia']} {output['nivel']} ({output['orden']})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
