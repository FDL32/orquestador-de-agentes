"""Renderiza, aplica y comprueba la vista de asignaciones del vuelo."""

import argparse
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RESOLVER_PATH = Path(__file__).with_name("resolver_asignacion.py")
DEFAULT_DOC = ROOT / "docs" / "protocol" / "sistema_agnostico_celdas_y_lentes.md"
DEFAULT_HOOK = ROOT / ".agent" / "hooks" / "session_start_hook.py"
DEFAULT_MEMORY = ROOT / "scripts" / "memory_context.py"
_BEGIN_RE = re.compile(rb"ASIGNACIONES:BEGIN(?: sha=([0-9a-fA-F]{16}))?")
_END = b"ASIGNACIONES:END"


def _resolver():
    """Before: existe el resolvedor hermano. During: lo carga por ruta. After: devuelve su modulo."""
    spec = importlib.util.spec_from_file_location("resolver_for_render", RESOLVER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("no se pudo cargar resolver_asignacion.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _description(candidate, backend_keys, resolver):
    """Before: candidate es una entrada declarada. During: normaliza su descripcion. After: devuelve texto ASCII."""
    info = resolver.candidate_info(candidate, backend_keys)
    if info["tipo"] == "t3_session":
        return f"{info['familia']}:{info['instanceId']}/{info['model']}"
    return f"{info['familia']} {info['model']}"


def _common_refuge(asignaciones, resolver):
    """Before: cada puesto declara refugio. During: comprueba igualdad exacta. After: devuelve el refugio comun o falla cerrado."""
    common_refuge = asignaciones[resolver.PUESTOS[0]]["refugio"]
    for post in resolver.PUESTOS[1:]:
        refuge = asignaciones[post]["refugio"]
        if refuge != common_refuge:
            raise ValueError(f"refugio divergente en {post}: {refuge}")
    return common_refuge


def render_block(asignaciones, backend_keys):
    """Before: asignaciones y backends cumplen el contrato. During: compone la vista determinista. After: devuelve el bloque compacto."""
    resolver = _resolver()
    lines = ["**Asignaciones del vuelo**:"]
    common_refuge_data = _common_refuge(asignaciones, resolver)
    common_refuge = ",".join(
        _description(item, backend_keys, resolver) for item in common_refuge_data
    )
    lines.append("refugio comun: " + common_refuge)
    for post in resolver.PUESTOS:
        data = asignaciones[post]
        candidates = []
        for candidate in data["candidatos"]:
            label = _description(candidate, backend_keys, resolver)
            if resolver.is_pendiente(data, candidate):
                label += " PENDIENTE"
            candidates.append(label)
        lines.append(f"- {post} [{data['nivel']}]: {' > '.join(candidates)}")
    lines.append(
        "cambio: pega messageId; edita asignaciones.<puesto>.candidatos; ejecuta render_asignaciones.py --apply."
    )
    lines.append("no derivados: " + ", ".join(resolver.CLAVES_NO_DERIVADAS))
    return "\n".join(lines)


def _marker_bounds(raw, path):
    """Before: raw contiene bytes de un destino. During: localiza un unico par de marcadores. After: devuelve limites o falla rc 3."""
    begins = list(_BEGIN_RE.finditer(raw))
    ends = [match.start() for match in re.finditer(re.escape(_END), raw)]
    if len(begins) != 1 or len(ends) != 1 or ends[0] < begins[0].start():
        raise ValueError(f"marcadores invalidos: {path}")
    begin = raw.rfind(b"\n", 0, begins[0].start()) + 1
    end_line = raw.find(b"\n", ends[0])
    end = len(raw) if end_line < 0 else end_line + 1
    return begin, end, begins[0].group(1)


def _rendered_file(raw, path, block):
    """Before: raw tiene marcadores validos y block es texto. During: prepara reemplazo acotado. After: devuelve bytes nuevos y hash."""
    begin, end, _old_hash = _marker_bounds(raw, path)
    is_doc = path.suffix.lower() == ".md"
    digest = hashlib.sha256(block.encode("utf-8")).hexdigest()[:16]
    if is_doc:
        rendered = f"<!-- ASIGNACIONES:BEGIN sha={digest} -->\n{block}\n<!-- ASIGNACIONES:END -->\n"
    else:
        commented = "\n".join("# " + line for line in block.splitlines())
        rendered = (
            f"# ASIGNACIONES:BEGIN sha={digest}\n{commented}\n# ASIGNACIONES:END\n"
        )
    return raw[:begin] + rendered.encode("utf-8") + raw[end:], digest


def _surface(path, block):
    """Before: path es una superficie viva. During: calcula su reemplazo sin escribir. After: devuelve bytes y hash."""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"superficie ilegible: {path}") from exc
    return _rendered_file(raw, path, block)


def _load_document(path):
    """Before: path apunta a agents.json. During: carga su JSON y declaracion. After: devuelve documento y asignaciones."""
    resolver = _resolver()
    document, assignments = resolver.load_declaration(path)
    return resolver, document, assignments


def _expected(document, assignments):
    """Before: document tiene registro y asignaciones. During: deriva vistas y bloque. After: devuelve todos los esperados."""
    resolver = _resolver()
    backends = document["ensemble_registry"]["backend_keys"]
    block = render_block(assignments, backends)
    eligible = resolver.derive_eligible(assignments, document)
    builder_model = resolver.derive_role_models_builder(assignments, backends)
    builder_backend = resolver.derive_role_assignments_builder(assignments, backends)
    return block, eligible, builder_model, builder_backend


def _apply_agents(path, document, eligible, builder_model, builder_backend):
    """Before: document es JSON parseado. During: cambia solo claves derivadas y escribe JSON. After: agents.json queda materializado."""
    coverage = document["ensemble_registry"]["eligible_coverage"][
        "MANAGER_REVIEW:repo_motor"
    ]
    coverage["backend_keys"] = eligible
    document["role_models"]["BUILDER"] = builder_model
    document["role_assignments"]["BUILDER"] = builder_backend
    path.write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _check_agents(document, eligible, builder_model, builder_backend):
    """Before: document contiene posibles vistas derivadas. During: compara cuatro valores. After: devuelve motivos de deriva."""
    errors = []
    actual = document["ensemble_registry"]["eligible_coverage"][
        "MANAGER_REVIEW:repo_motor"
    ].get("backend_keys")
    if actual != eligible:
        errors.append(
            "ensemble_registry.eligible_coverage.MANAGER_REVIEW:repo_motor.backend_keys"
        )
    if document.get("role_models", {}).get("BUILDER") != builder_model:
        errors.append("role_models.BUILDER")
    if document.get("role_assignments", {}).get("BUILDER") != builder_backend:
        errors.append("role_assignments.BUILDER")
    return errors


def _check_surfaces(paths, block):
    """Before: paths apuntan a superficies marcadas. During: mide hashes sin escribir. After: devuelve deriva por sitio."""

    def _surface_drift(path):
        """Before: path apunta a una superficie. During: compara marker y bytes. After: devuelve su nombre si deriva."""
        try:
            raw = path.read_bytes()
            _begin, _end, marker_hash = _marker_bounds(raw, path)
            expected, expected_hash = _rendered_file(raw, path, block)
            if (
                marker_hash is None
                or marker_hash.decode("ascii").lower() != expected_hash
            ):
                return str(path)
            return str(path) if expected != raw else None
        except (OSError, ValueError):
            return str(path)

    return [drift for path in paths if (drift := _surface_drift(path)) is not None]


def _parser():
    """Before: se invoca desde main. During: declara la CLI. After: devuelve parser configurado."""
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--check", action="store_true")
    parser.add_argument(
        "--agents-json", type=Path, default=ROOT / ".agent" / "config" / "agents.json"
    )
    parser.add_argument("--doc", type=Path, default=DEFAULT_DOC)
    parser.add_argument("--hook", type=Path, default=DEFAULT_HOOK)
    parser.add_argument("--memory-context", type=Path, default=DEFAULT_MEMORY)
    return parser


def main(argv=None):
    """Before: recibe modo y rutas. During: deriva, comprueba o aplica superficies. After: devuelve rc 0, 1 o 3."""
    args = _parser().parse_args(argv)
    try:
        _resolver_module, document, assignments = _load_document(args.agents_json)
        block, eligible, builder_model, builder_backend = _expected(
            document, assignments
        )
        paths = (args.doc, args.hook, args.memory_context)
        if args.check:
            errors = _check_agents(document, eligible, builder_model, builder_backend)
            errors.extend(_check_surfaces(paths, block))
            if errors:
                print("deriva: " + "; ".join(errors), file=sys.stderr)
                return 1
            return 0
        replacements = [_surface(path, block)[0] for path in paths]
        _apply_agents(
            args.agents_json, document, eligible, builder_model, builder_backend
        )
        for path, replacement in zip(paths, replacements, strict=True):
            path.write_bytes(replacement)
        return 0
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
