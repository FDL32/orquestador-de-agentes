#!/usr/bin/env python3
"""PreToolUse gate for Claude delegate_task (WOT-2026-221c)."""

from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path


EXPECTED_MATCHER = "mcp__t3-code__delegate_task"
LEVEL_ORDER = {"base": 0, "medio": 1, "alto": 2, "premium": 3}


def _root_from_cwd() -> Path:
    current = Path.cwd().resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".claude").is_dir():
            return candidate
    return current


def _inactive(reason: str) -> int:
    message = f"HOOK INACTIVE: {reason}"
    print(json.dumps({"additionalContext": message}))
    print(message, file=sys.stderr)
    return 2


def _reject(reason: str) -> int:
    instruction = (
        "Revalida con una peticion de usuario UUID36 y repite el dispatch; "
        "el hook no verifica el almacen de mensajes."
    )
    message = f"nivel-no-autorizado: {reason}. {instruction}"
    print(json.dumps({"additionalContext": message}))
    print(message, file=sys.stderr)
    return 2


def _settings_active(root: Path) -> bool:
    try:
        data = json.loads(
            (root / ".claude" / "settings.json").read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    for group in (data.get("hooks") or {}).get("PreToolUse", []):
        if group.get("matcher") != EXPECTED_MATCHER:
            continue
        if any(
            "guard_model_level.py" in str(hook.get("command", ""))
            for hook in group.get("hooks", [])
        ):
            return True
    return False


def main() -> int:  # noqa: C901 - boundary validation is intentionally fail-closed
    root = _root_from_cwd()
    if not _settings_active(root):
        return _inactive("settings.json ausente, invalido o matcher mutado")
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError, UnicodeError):
        return _inactive("entrada JSON ilegible")
    if payload.get("tool_name") != EXPECTED_MATCHER:
        return _inactive("matcher no reconocido")
    try:
        config = json.loads(
            (root / ".agent" / "config" / "agents.json").read_text(encoding="utf-8")
        )
        registry = config["ensemble_registry"]
        maximum = registry["roles"]["U4"]["nivel"]
        ceiling = registry["uso_maximo_por_tipo"][maximum]
        if (
            not isinstance(ceiling, (int, float))
            or isinstance(ceiling, bool)
            or not math.isfinite(float(ceiling))
            or ceiling < 0
        ):
            return _inactive("techo de U4 invalido")
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
    ):
        return _inactive("agents.json no carga")
    target = (payload.get("tool_input") or {}).get("target")
    if (
        not isinstance(target, dict)
        or not target.get("providerInstanceId")
        or not target.get("model")
    ):
        print(
            json.dumps(
                {
                    "additionalContext": "NO VERIFICADO: target no explicito; se permite por herencia del padre."
                }
            )
        )
        return 0
    instance = str(target["providerInstanceId"])
    backend = instance.split("_", 1)[0]
    matches = []
    for key, entry in (registry.get("backend_keys") or {}).items():
        if (
            entry.get("status") == "active"
            and entry.get("backend") == backend
            and entry.get("model") == target["model"]
        ):
            matches.append((key, entry))
    if len(matches) != 1:
        print(
            json.dumps(
                {"additionalContext": "NO VERIFICADO: destino ambiguo o inexistente."}
            )
        )
        return 0
    key, entry = matches[0]
    levels = entry.get("niveles") or [entry.get("nivel")]
    valid = [level for level in levels if level in LEVEL_ORDER]
    eligible = [level for level in valid if LEVEL_ORDER[level] <= LEVEL_ORDER[maximum]]
    effective = max(eligible, key=LEVEL_ORDER.get) if eligible else "premium"
    request = (payload.get("tool_input") or {}).get("peticion_usuario")
    if entry.get("acceso") == "externo_pago":
        return _reject("acceso-externo-pago")
    if (
        LEVEL_ORDER.get(effective, 3) > LEVEL_ORDER.get(maximum, -1)
        or effective == "premium"
    ) and not isinstance(request, str):
        return _reject("nivel superior sin peticion")
    if (
        LEVEL_ORDER.get(effective, 3) > LEVEL_ORDER.get(maximum, -1)
        or effective == "premium"
    ) and not re.fullmatch(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
        r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
        request,
    ):
        return _reject("peticion_usuario no tiene formato UUID36")
    print(
        json.dumps({"additionalContext": f"nivel autorizado: {key}; techo={ceiling}"})
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
