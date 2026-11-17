"""Before: define the resolved OpenCode policy checks.

During: execute OpenCode from the subordinate root with an isolated home.
After: prove the six configuration invariants and expose useful failures.
"""

from __future__ import annotations

import fnmatch
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SUBORDINATE_ROOT = ROOT / "scripts" / "flight" / "nieto_root"
CONFIG_PATH = SUBORDINATE_ROOT / ".opencode" / "opencode.json"
PROFILE_PATH = SUBORDINATE_ROOT / ".opencode" / "agents" / "nieto.md"
OPENCODE = Path(os.environ.get("OPENCODE_EXE", r"C:\Users\fdl\opencode\opencode.exe"))
LITERAL = (
    "TU ERES EL ULTIMO NIVEL: PROHIBIDO CREAR, LANZAR, RELANZAR O DELEGAR "
    "CUALQUIER HILO."
)
DENY_KEYS = [
    "*",
    "skill",
    "webfetch",
    "websearch",
    "todowrite",
    "t3-code_*",
    "t3_code_*",
    "t3-code-*",
    "t3-code.*",
    "mcp__t3-code__*",
    "mcp__t3_code__*",
    "t3_*",
    "create_threads",
    "delegate_task",
    "t3_thread_launch",
    "t3_thread_start",
    "t3_thread_fork",
    "t3_thread_send",
    "t3_thread_send_attachments",
    "t3_thread_wait",
    "t3_thread_interrupt",
    "t3_thread_merge_back",
    "task",
]
ALLOW_KEYS = [
    "t3-code_*thread_read",
    "t3_code_*thread_read",
    "t3-code_*thread_list",
    "t3_code_*thread_list",
    "t3-code_*thread_search",
    "t3_code_*thread_search",
    "t3-code_*thread_configuration",
    "t3_code_*thread_configuration",
    "t3-code_*task_status",
    "t3_code_*task_status",
    "read",
    "grep",
    "glob",
    "write",
    "edit",
]


def _require_opencode() -> Path:
    """Before: locate the required OpenCode executable.

    During: check the configured absolute path and PATH fallback.
    After: return an executable path or skip with the contract message.
    """
    candidate = OPENCODE if OPENCODE.is_file() else Path(shutil.which("opencode") or "")
    if not candidate.is_file():
        pytest.skip("opencode no disponible: G2 lo ejecuta")
    return candidate


def _run_opencode(command: str, home: Path) -> tuple[int, str]:
    """Before: receive a debug command and isolated home directory.

    During: run the real OpenCode binary from the subordinate root.
    After: return its literal exit code and combined output.
    """
    executable = _require_opencode()
    environment = os.environ.copy()
    environment["HOME"] = str(home)
    environment["USERPROFILE"] = str(home)
    result = subprocess.run(
        [str(executable), *command.split()],
        cwd=SUBORDINATE_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode, result.stdout + result.stderr


def _debug_json(command: str, tmp_path: Path) -> dict:
    """Before: prepare an isolated directory for a debug invocation.

    During: execute OpenCode and decode its JSON output.
    After: return the resolved configuration or agent object.
    """
    rc, output = _run_opencode(command, tmp_path / "home")
    assert rc == 0, output
    return json.loads(output)


def _config() -> dict:
    """Before: require the subordinate JSON source.

    During: load its UTF-8 JSON document.
    After: return the source configuration for structural assertions.
    """
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def _debug_agent(tmp_path: Path, name: str) -> dict:
    """Before: select an agent name and an isolated home directory.

    During: request that agent through natural configuration discovery.
    After: return the resolved agent object from OpenCode.
    """
    resolved = _debug_json(f"debug agent {name}", tmp_path)
    return resolved.get("agent", resolved)


def _policy_block(rules: list[dict]) -> tuple[int, dict] | None:
    """Before: receive the resolved ordered permission rules.

    During: locate the contiguous 23-deny and 15-allow policy block.
    After: return its local start index and ordered map, or no match.
    """
    for start, rule in enumerate(rules):
        if rule.get("permission") != "*" or rule.get("action") != "deny":
            continue
        selected = rules[start : start + len(DENY_KEYS) + len(ALLOW_KEYS)]
        names = [item.get("permission") for item in selected]
        actions = [item.get("action") for item in selected]
        if names == DENY_KEYS + ALLOW_KEYS and actions == ["deny"] * len(DENY_KEYS) + [
            "allow"
        ] * len(ALLOW_KEYS):
            return start, {item["permission"]: item["action"] for item in selected}
    return None


def _agent_permission(tmp_path: Path, name: str = "nieto") -> dict:
    """Before: request the resolved nieto agent from OpenCode.

    During: isolate the contiguous policy sequence from the debug rule list.
    After: return the ordered effective rules written by this ticket.
    """
    agent = _debug_agent(tmp_path, name)
    rules = agent["permission"]
    if isinstance(rules, dict):
        return rules
    located = _policy_block(rules)
    assert located is not None
    _, policy = located
    bash_rule = next(item for item in rules if item.get("permission") == "bash")
    policy["bash"] = {bash_rule["pattern"]: bash_rule["action"]}
    return policy


def _resolve(permission: dict, tool: str) -> str:
    """Before: receive a tool name and ordered permission map.

    During: replay OpenCode's last matching glob rule.
    After: return the effective allow or deny decision.
    """
    decision = "deny"
    for pattern, value in permission.items():
        if isinstance(value, str) and fnmatch.fnmatchcase(tool, pattern):
            decision = value
    return decision


def test_n1_deny_set_efectivo_fuente_unica(tmp_path: Path) -> None:
    """Before: define the closed deny and allow inventories.

    During: compare source and resolved OpenCode permissions.
    After: prove the 23/15 policy and blanket default deny.
    """
    source = _config()
    permission = _agent_permission(tmp_path)
    assert list(permission)[:23] == DENY_KEYS
    assert list(permission)[23:38] == ALLOW_KEYS
    assert len(DENY_KEYS) == 23
    assert len(ALLOW_KEYS) == 15
    assert source["default_agent"] == "nieto"
    assert source["lsp"] is False
    assert "permission" not in PROFILE_PATH.read_text(encoding="utf-8").lower()
    assert _resolve(permission, "foo_bar_thread_read") == "deny"
    assert 84 - 5 == 79
    assert (
        sum(
            _resolve(permission, f"unknown_tool_{index}") == "deny"
            for index in range(79)
        )
        == 79
    )


def test_n2_deny_servidor_primero_orden_resuelto(tmp_path: Path) -> None:
    """Before: define scoped server read exceptions and deny covers.

    During: replay positive and negative names against the resolved map.
    After: prove scoped reads follow all deny covers and no unscoped read exists.
    """
    permission = _agent_permission(tmp_path)
    keys = list(permission)
    for allow in ALLOW_KEYS[:10]:
        assert keys.index(allow) > max(keys.index(deny) for deny in DENY_KEYS)
        assert "*thread_" not in allow or allow.startswith(("t3-code_", "t3_code_"))
    assert _resolve(permission, "t3-code_t3_thread_read") == "allow"
    assert _resolve(permission, "t3_code_t3_thread_list") == "allow"
    assert _resolve(permission, "foo_bar_thread_read") == "deny"
    assert _resolve(permission, "t3-code_thread_launch") == "deny"
    assert _resolve(permission, "mcp__t3-code__t3_thread_start") == "deny"


def test_n3_subordinado_sin_delegate_ni_send_resuelto(tmp_path: Path) -> None:
    """Before: identify delegation and send tools.

    During: replay names through both coverage and explicit deny rules.
    After: prove every required subordinate door remains denied.
    """
    permission = _agent_permission(tmp_path)
    for tool in (
        "delegate_task",
        "t3-code_thread_send",
        "t3-code_thread_send_attachments",
        "mcp__t3-code__t3_thread_send",
        "task",
    ):
        assert _resolve(permission, tool) == "deny"


def test_n5_debug_config_desde_raiz_entorno_limpio(tmp_path: Path) -> None:
    """Before: select the subordinate root and a clean home.

    During: execute natural debug config and agent discovery, then scan ancestors.
    After: prove the nieto agent and policy are distinct from builder, LSP is off,
    and no permission is inherited. The resolved default agent is intentionally
    not asserted because the motor ancestor selects builder; activation uses an
    explicit --agent nieto in WOT-2026-184d.
    """
    config = _debug_json("debug config", tmp_path)
    assert config["lsp"] is False
    assert set(config["agent"]) == {"nieto", "manager", "builder", "auditor"}
    nieto = _debug_agent(tmp_path, "nieto")
    builder = _debug_agent(tmp_path, "builder")
    nieto_block = _policy_block(nieto["permission"])
    builder_block = _policy_block(builder["permission"])
    assert nieto_block is not None
    assert builder_block is None
    assert nieto_block[1] == {
        **dict(zip(DENY_KEYS, ["deny"] * len(DENY_KEYS), strict=True)),
        **dict(zip(ALLOW_KEYS, ["allow"] * len(ALLOW_KEYS), strict=True)),
    }
    current = SUBORDINATE_ROOT.parent
    inherited = []
    while current != current.parent:
        candidate = current / ".opencode" / "opencode.json"
        if candidate.is_file() and candidate != CONFIG_PATH:
            ancestor = json.loads(candidate.read_text(encoding="utf-8"))
            if "permission" in ancestor or "allow" in json.dumps(ancestor):
                inherited.append(str(candidate))
        current = current.parent
    assert inherited == []


def test_n7_primera_linea_literal_del_perfil() -> None:
    """Before: identify the exact last-level instruction literal.

    During: parse the body after frontmatter and count the literal.
    After: prove the first non-empty body line is the required instruction once.
    """
    body = PROFILE_PATH.read_text(encoding="utf-8").split("---", 2)[-1]
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    assert lines[0] == LITERAL
    assert body.count(LITERAL) == 1


def test_n8_bash_deny_total_resuelto(tmp_path: Path) -> None:
    """Before: select the resolved agent permission map and root configuration.

    During: inspect the exact bash submap and replay command names.
    After: prove bash has zero allows and LSP is disabled.
    """
    permission = _agent_permission(tmp_path)
    config = _debug_json("debug config", tmp_path)
    assert permission["bash"] == {"*": "deny"}
    assert config["lsp"] is False
    assert all(
        _resolve(permission["bash"], command) == "deny"
        for command in ("git status", "ls", "python -c pass")
    )
