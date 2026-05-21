#!/usr/bin/env python3
import contextlib
import json
import subprocess
import sys
from pathlib import Path


# Paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
AGENT_DIR = PROJECT_ROOT / ".agent"
COLLAB_DIR = AGENT_DIR / "collaboration"
RUNTIME_DIR = AGENT_DIR / "runtime"
AUDIT_DIR = RUNTIME_DIR / "audit"


def run_cmd(cmd, cwd=PROJECT_ROOT):
    try:
        return subprocess.check_output(  # noqa: S603
            cmd, cwd=cwd, text=True, stderr=subprocess.STDOUT
        ).strip()
    except Exception as e:
        return f"[Error: {e}]"


def get_versions():
    versions = {}
    project_md = PROJECT_ROOT / "PROJECT.md"
    if project_md.exists():
        for line in project_md.read_text(encoding="utf-8").splitlines():
            if line.startswith("- Version:"):
                raw = line.split(":", 1)[1].strip()
                versions["project_md"] = raw.strip("`").strip("'").strip('"').strip()
                break

    version_manifest = AGENT_DIR / ".version_manifest.json"
    if version_manifest.exists():
        with contextlib.suppress(Exception):
            manifest = json.loads(version_manifest.read_text(encoding="utf-8"))
            versions["manifest"] = manifest.get("agent_core_version", "unknown")

    pyproject = PROJECT_ROOT / "pyproject.toml"
    if pyproject.exists():
        for line in pyproject.read_text(encoding="utf-8").splitlines():
            if line.startswith("version ="):
                versions["pyproject"] = line.split("=")[1].strip().strip('"').strip("'")
                break

    return versions


def check_version_drift(versions):
    cleaned = {}
    for k, v in versions.items():
        if v and v != "unknown":
            cleaned[k] = v.strip().strip("`").strip("'").strip('"').lstrip("v").strip()

    vals = list(cleaned.values())
    if len(vals) > 1 and len(set(vals)) > 1:
        return True, cleaned
    return False, cleaned


def fix_mojibake(text: str) -> str:
    # Replacement char (U+FFFD) means original byte was lost; surface as '?'
    # instead of leaking the replacement glyph through to JSON consumers.
    text = text.replace("\ufffd", "?")
    try:
        return text.encode("cp1252").decode("utf-8")
    except Exception:
        return text


def get_active_state_from_work_plan():
    work_plan_file = COLLAB_DIR / "work_plan.md"
    if not work_plan_file.exists():
        return None

    # Read and reverse lines to scan bottom-up (most recent first)
    lines = work_plan_file.read_text(encoding="utf-8").splitlines()
    current_wp = None
    current_status = None

    for line in reversed(lines):
        if "- **Estado:**" in line:
            current_status = (
                line.split(":", 1)[1].replace("**", "").replace("*", "").strip()
            )
        elif "- **ID:**" in line:
            current_wp = (
                line.split(":", 1)[1].replace("**", "").replace("*", "").strip()
            )
        elif line.startswith("## WP-"):
            if not current_wp:
                parts = line.split(":", 1)
                current_wp = parts[0].replace("##", "").strip()
            return {"plan": current_wp, "status": current_status or "Unknown"}

    return None


def get_active_state():
    state = {"plan": "None", "status": "None"}
    state_file = COLLAB_DIR / "STATE.md"
    if state_file.exists():
        for line in state_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("- **Plan Activo:**") or line.startswith("- **ID:**"):
                state["plan"] = (
                    line.split(":", 1)[1].replace("**", "").replace("*", "").strip()
                )
            elif line.startswith("- **Estado actual:**"):
                state["status"] = (
                    line.split(":", 1)[1].replace("**", "").replace("*", "").strip()
                )
        if state["plan"] != "None":
            return state

    wp_state = get_active_state_from_work_plan()
    if wp_state:
        return wp_state

    return state


def get_git_posture():
    posture = {}
    if (PROJECT_ROOT / ".git").exists():
        raw_status = run_cmd(["git", "status", "-sb"])
        # Filter out untracked files
        filtered_lines = [
            line
            for line in raw_status.splitlines()
            if not line.strip().startswith("??")
        ]
        posture["status"] = "\n".join(filtered_lines)
        posture["recent_commits"] = run_cmd(
            ["git", "log", "--oneline", "-5"]
        ).splitlines()
    else:
        posture["status"] = "No git repository found"
        posture["recent_commits"] = []
    return posture


def get_skills():
    skills = []
    skills_dir = PROJECT_ROOT / "skills"
    if skills_dir.exists():
        for skill_md in skills_dir.glob("*/SKILL.md"):
            skill_info = {"path": str(skill_md.relative_to(PROJECT_ROOT))}
            content = skill_md.read_text(encoding="utf-8-sig")
            in_frontmatter = False
            for line in content.splitlines():
                if line.strip() == "---":
                    if not in_frontmatter:
                        in_frontmatter = True
                        continue
                    else:
                        break
                if in_frontmatter and ":" in line:
                    k, v = line.split(":", 1)
                    key = k.strip()
                    val = v.strip().strip("'").strip('"')
                    val_cleaned = fix_mojibake(val)

                    if key == "triggers":
                        # Convert '[/implement, implement, /code]' or 'a, b' into a list of strings
                        cleaned_val = val_cleaned.strip("[]").strip()
                        skill_info[key] = [
                            t.strip().strip("'").strip('"')
                            for t in cleaned_val.split(",")
                            if t.strip()
                        ]
                    else:
                        skill_info[key] = val_cleaned
            skills.append(skill_info)
    return skills


def get_backends():
    backends = {}
    agents_json = AGENT_DIR / "config" / "agents.json"
    if agents_json.exists():
        with contextlib.suppress(Exception):
            backends = json.loads(agents_json.read_text(encoding="utf-8"))
    return backends


def get_health(quick=False):
    if quick:
        return {"status": "skipped", "message": "Health check skipped in quick mode"}

    health = {}
    controller = AGENT_DIR / "agent_controller.py"
    if controller.exists():
        try:
            output = run_cmd([sys.executable, str(controller), "--validate", "--json"])
            try:
                json_str = output[output.find("{") :] if "{" in output else output
                health = json.loads(json_str)
            except json.JSONDecodeError:
                health = {"raw_output": output}
        except Exception as e:
            health = {"error": str(e)}
    return health


def get_recent_wps():
    wps = []
    exec_log = COLLAB_DIR / "execution_log.md"
    if exec_log.exists():
        lines = exec_log.read_text(encoding="utf-8").splitlines()
        for line in lines:
            if line.startswith("### WP-"):
                wps.append(line.replace("### ", "").strip())
                if len(wps) >= 5:
                    break
    return wps


def get_memory_hits():
    memory_md = RUNTIME_DIR / "memory" / "MEMORY.md"
    if not memory_md.exists():
        return []
    entries = []
    for line in memory_md.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped.startswith("- ") or "observaciones)" in stripped:
            continue
        # Drop low-signal noise (tool call traces) and very short entries
        if stripped.startswith("- Tool ") or len(stripped) < 30:
            continue
        entries.append(fix_mojibake(stripped))
    return entries[:10]


def main():
    import argparse
    import datetime

    parser = argparse.ArgumentParser(description="Generate local project audit")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output JSON to stdout instead of MD generation",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Skip slow health check validation",
    )
    args = parser.parse_args()

    audit_data = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "version_info": get_versions(),
        "active_state": get_active_state(),
        "git_posture": get_git_posture(),
        "skills": get_skills(),
        "backends": get_backends(),
        "health": get_health(quick=args.quick),
        "recent_wps": get_recent_wps(),
        "memory_summary": get_memory_hits(),
    }

    # Version drift checking
    has_drift, _ = check_version_drift(audit_data["version_info"])
    audit_data["version_info"]["drift_detected"] = has_drift

    if args.json:
        print(json.dumps(audit_data, indent=2))
        return 0

    AUDIT_DIR.mkdir(parents=True, exist_ok=True)

    with open(AUDIT_DIR / "audit.json", "w", encoding="utf-8") as f:
        json.dump(audit_data, f, indent=2)

    md_lines = [
        "# Local Audit Report",
        f"*Generated at: {audit_data['generated_at']}*",
        "",
    ]

    if has_drift:
        md_lines.extend(
            [
                "> [!WARNING]",
                "> **Version Drift Detected!**",
                "> There is a mismatch between the declared versions in the project:",
            ]
        )
        for k, v in audit_data["version_info"].items():
            if k != "drift_detected":
                md_lines.append(f"> - **{k}**: `{v}`")
        md_lines.extend(["", ""])

    md_lines.extend(
        [
            "## Version & State",
            f"- **Project Version**: {audit_data['version_info'].get('project_md', 'Unknown')}",
            f"- **Active Plan**: {audit_data['active_state'].get('plan', 'None')}",
            f"- **Active Status**: {audit_data['active_state'].get('status', 'None')}",
            "",
            "## Git Posture",
            f"```text\n{audit_data['git_posture'].get('status', '')}\n```",
            "**Recent Commits:**",
            *[f"- {c}" for c in audit_data["git_posture"].get("recent_commits", [])],
            "",
            "## Capabilities (Skills)",
        ]
    )

    for s in audit_data["skills"]:
        name = s.get("name", s.get("path"))
        triggers = s.get("triggers", [])
        triggers_str = (
            ", ".join(triggers) if isinstance(triggers, list) else str(triggers)
        )
        desc = s.get("description", "")
        md_lines.append(f"- **{name}** (Triggers: `{triggers_str}`): {desc}")

    md_lines.extend(
        [
            "",
            "## Health Check",
        ]
    )

    # Format health checks
    if args.quick:
        md_lines.append("- *Health check validation skipped in quick mode*")
    else:
        errors = audit_data["health"].get("errors", {})
        warnings = audit_data["health"].get("warnings", {})

        if isinstance(errors, dict) and isinstance(warnings, dict):
            total_errors = sum(len(v) for v in errors.values())
            total_warnings = sum(len(v) for v in warnings.values())

            if total_errors == 0 and total_warnings == 0:
                md_lines.append("- All systems OK (0 errors, 0 warnings)")
            else:
                md_lines.append(f"- **Errors**: {total_errors}")
                md_lines.append(f"- **Warnings**: {total_warnings}")
        else:
            md_lines.append("- Could not parse health output correctly")

    md_lines.extend(
        [
            "",
            "## Recent Work Plans",
            *[f"- {wp}" for wp in audit_data["recent_wps"]],
            "",
            "## Memory Overview (Top entries)",
            *[f"> {m}" for m in audit_data["memory_summary"]],
        ]
    )

    audit_md = AUDIT_DIR / "AUDIT.md"
    with open(audit_md, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines) + "\n")

    print(f"[OK] Audit generated at {audit_md.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
