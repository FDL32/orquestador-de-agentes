from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "launch_agent_terminals.ps1"


def test_launcher_uses_dynamic_executable_resolution() -> None:
    content = SCRIPT_PATH.read_text(encoding="utf-8")

    assert "Resolve-HostShellExecutable" in content
    # El backend del Manager se resuelve dinamicamente desde agents.json
    # (la antigua Resolve-ManagerExecutable hardcodeaba codex y era codigo muerto).
    assert "Get-BackendFromConfig -Role 'MANAGER'" in content
    assert "Resolve-KiloExecutable" in content
    assert "Repair-StartupBridgeState" in content
    assert "BridgeStateCorrupt" in content
    assert "openai.chatgpt-26.506.31421" not in content
    assert "kilocode.kilo-code-7.2.52" not in content
    assert "$PSHOME 'powershell.exe'" not in content


def test_launcher_strict_launch_parameter() -> None:
    content = SCRIPT_PATH.read_text(encoding="utf-8")

    assert "[switch]$StrictLaunch = $true" in content
    assert "if ($StrictLaunch) {" in content
    assert "Assert-StartupAlignment" in content
    assert "Stop-ProjectAgentProcesses" in content
    assert "Cerrando sesion vieja del proyecto" in content


def test_launcher_reports_per_window() -> None:
    content = SCRIPT_PATH.read_text(encoding="utf-8")

    assert 'Write-Host "Supervisor: lanzado con ticket_supervisor.py --reactive"' in content
    assert 'Write-Host "Review Bridge: lanzado' in content
    assert 'Write-Host "Arranque terminal-driven completado para $ProjectRoot"' in content


def test_launcher_cleans_previous_project_sessions() -> None:
    content = SCRIPT_PATH.read_text(encoding="utf-8")

    assert "ticket_supervisor\\.py" in content
    assert "manager_review_bridge\\.py" in content
    assert "kilo\\.exe\\s+run\\s+--auto" in content
    assert "builder_lock\\.txt" in content
    assert "Limpieza previa: sesiones viejas del proyecto cerradas antes del nuevo arranque" in content


def test_launcher_uses_startup_templates() -> None:
    content = SCRIPT_PATH.read_text(encoding="utf-8")

    assert "Get-TemplateContent" in content
    assert "Fill-TemplateVariables" in content
    assert "templates/startup/" in content
    assert "GetTempFileName()" not in content
    # WP-2026-078: temp prompt file machinery removed (bridge builds prompt inline)
    assert "New-ManagerPromptFile" not in content
    assert "Start-DeferredFileCleanup" not in content
    assert "--manager-prompt-file" not in content

    # Check that manager_legacy template exists and contains variables
    from pathlib import Path
    PROJECT_ROOT = Path(__file__).resolve().parents[1]
    manager_template = PROJECT_ROOT / "templates" / "startup" / "manager_legacy.md"
    assert manager_template.exists()
    manager_content = manager_template.read_text(encoding="utf-8")
    assert "{{ticket_id}}" in manager_content
    assert "{{work_plan}}" in manager_content
    assert "{{close_command}}" in manager_content
    assert "{{role}}" in manager_content
    assert "{{backend}}" in manager_content
    assert "{{role}}" in manager_content
    assert "{{backend}}" in manager_content


def test_launcher_multi_root_precedence() -> None:
    """WP-2026-125: el launcher resuelve el workspace destino con precedencia canonica."""
    content = SCRIPT_PATH.read_text(encoding="utf-8")

    # Funcion de resolucion de destino externo
    assert "function Resolve-DestinationRoot" in content
    assert "motor_destination_link.json" in content
    assert "destination_root" in content

    # Precedencia: --project-root > AGENT_PROJECT_ROOT > motor_destination_link.json > fallback
    assert "AGENT_PROJECT_ROOT" in content
    assert "GetEnvironmentVariable('AGENT_PROJECT_ROOT')" in content

    # Mensajes de diagnostico de resolucion
    assert "ProjectRoot resuelto desde AGENT_PROJECT_ROOT" in content
    assert "ProjectRoot resuelto desde motor_destination_link.json" in content
    assert "ProjectRoot resuelto desde fallback local" in content
