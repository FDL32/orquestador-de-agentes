import re
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


def test_launcher_reprojects_canonical_state_after_preflight_reconcile() -> None:
    content = SCRIPT_PATH.read_text(encoding="utf-8")

    assert "function Invoke-PostPreflightProjectionSync" in content
    assert "function Sync-StartupProjectionsIfNeeded" in content
    assert "ticket_supervisor.py" in content
    assert "--once --no-auto-sync" in content
    assert "AGENT_PROJECT_ROOT" in content
    assert (
        "@('RECONCILE', 'CLEANUP_LOCAL') -contains $preflightDecision.decision"
        in content
    )
    assert "Invoke-PostPreflightProjectionSync -ProjectRoot $ProjectRoot" in content
    assert (
        "[launcher] Proyecciones stale detectadas; reproyectando antes del launch estricto..."
        in content
    )
    assert (
        "$alignment = Sync-StartupProjectionsIfNeeded -ProjectRoot $ProjectRoot"
        in content
    )
    assert "if ($null -ne $previousProjectRoot)" in content
    assert "SetEnvironmentVariable('AGENT_PROJECT_ROOT', $null, 'Process')" in content


def test_launcher_reports_per_window() -> None:
    content = SCRIPT_PATH.read_text(encoding="utf-8")

    assert (
        'Write-Host "Supervisor: lanzado con ticket_supervisor.py --reactive"'
        in content
    )
    assert 'Write-Host "Review Bridge: lanzado' in content
    assert (
        'Write-Host "Arranque terminal-driven completado para $ProjectRoot"' in content
    )


def test_launcher_cleans_previous_project_sessions() -> None:
    content = SCRIPT_PATH.read_text(encoding="utf-8")

    assert "ticket_supervisor\\.py" in content
    assert "manager_review_bridge\\.py" in content
    assert "kilo\\.exe\\s+run\\s+--auto" in content
    assert "builder_lock\\.txt" in content
    assert (
        "Limpieza previa: sesiones viejas del proyecto cerradas antes del nuevo arranque"
        in content
    )


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

    project_root = Path(__file__).resolve().parents[1]
    manager_template = project_root / "templates" / "startup" / "manager_legacy.md"
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

    # Precedencia: --project-root > AGENT_PROJECT_ROOT > motor_destination_link.json > fallback  # noqa: ERA001
    assert "AGENT_PROJECT_ROOT" in content
    assert "GetEnvironmentVariable('AGENT_PROJECT_ROOT')" in content

    # Mensajes de diagnostico de resolucion
    assert "ProjectRoot resuelto desde AGENT_PROJECT_ROOT" in content
    assert "ProjectRoot resuelto desde motor_destination_link.json" in content
    assert "ProjectRoot resuelto desde fallback local" in content


def test_launcher_resume_builder_waits_for_supervisor_exit() -> None:
    """WP-2026-160: -ResumeBuilder debe esperar a que el supervisor viejo libere el lock."""
    content = SCRIPT_PATH.read_text(encoding="utf-8")

    # Funcion de espera del supervisor
    assert "function Wait-SupervisorExit" in content
    assert "supervisor_lock.txt" in content
    assert "TimeoutSeconds" in content

    # Rama -ResumeBuilder con espera
    assert "Resume mode: waiting for stale supervisor exit" in content
    assert "Wait-SupervisorExit -ProjectRoot" in content
    assert "Cannot guarantee fresh supervisor" in content

    # El launcher arranca supervisor fresco en ResumeBuilder, condicionado a -not $OnlyBuilder
    assert "Will launch fresh supervisor before Builder" in content
    # WT-2026-200: -OnlyBuilder manda sobre supervisor; migrado de $LaunchSupervisor = $true
    # WT-2026-201: assert semantico resistente a espaciado
    assert re.search(r"\$LaunchSupervisor\s*=\s*-not\s*\$OnlyBuilder", content), (
        "La asignacion $LaunchSupervisor = -not $OnlyBuilder debe existir "
        "para que -OnlyBuilder mande sobre el supervisor en resume"
    )


def test_launcher_resume_builder_fail_closed_on_timeout() -> None:
    """WP-2026-160: -ResumeBuilder debe fallar cerrado si el supervisor no sale a tiempo."""
    content = SCRIPT_PATH.read_text(encoding="utf-8")

    # Fail-closed con exit code no cero
    assert "exit 1" in content
    assert "stale supervisor did not exit within timeout" in content


def test_launcher_resume_builder_sets_restart_reason_env() -> None:
    """WP-2026-160: -ResumeBuilder debe exportar SUPERVISOR_RESTART_REASON para que el supervisor fresco emita SUPERVISOR_RESTARTED."""
    content = SCRIPT_PATH.read_text(encoding="utf-8")

    assert "SUPERVISOR_RESTART_REASON" in content
    assert '"resume-builder"' in content


def test_launcher_external_controller_resolution() -> None:
    """WP-2026-176: El launcher resuelve el motor root desde motor_destination_link.json del workspace."""
    content = SCRIPT_PATH.read_text(encoding="utf-8")

    assert "resolvedMotorRoot" in content
    assert "workspaceMotorLink" in content
    assert "motor_destination_link.json" in content
    assert "useExternalController" in content
    assert "Motor controller externo" in content


def test_launcher_external_controller_close_command() -> None:
    """WP-2026-176: El closeCommand incluye --project-root cuando usa controller externo."""
    content = SCRIPT_PATH.read_text(encoding="utf-8")

    assert (
        "resolvedMotorRoot\\.agent\\agent_controller.py --pre-handoff --project-root"
        in content
    )
    assert (
        "resolvedMotorRoot\\.agent\\agent_controller.py --mark-ready --json --force --project-root"
        in content
    )
    assert "--bootstrap-ticket --json --project-root $ProjectRoot" in content


def test_launcher_skip_supervisor_wait_flag_exists() -> None:
    """Hotfix WP-2026-160: -SkipSupervisorWait debe existir como parametro y saltarse Wait-SupervisorExit en el relanzado interno."""
    content = SCRIPT_PATH.read_text(encoding="utf-8")

    assert "SkipSupervisorWait" in content
    assert "SkipSupervisorWait: internal requeue relaunch" in content
    assert "$SkipSupervisorWait" in content


def test_builder_templates_do_not_inject_close_command() -> None:
    """Regression: launcher owns closeout; templates must never re-inject {{close_command}}.

    CL-07: the try/finally in Add-BuilderCloseout is the single source of
    truth for Builder closeout. If {{close_command}} reappears in a template,
    the AI would try to run the close command AND the finally block would run
    it again, producing double closeout (or a stuck ticket on crash).
    """
    template_dir = PROJECT_ROOT / "templates" / "startup"
    active_builder_templates = list(template_dir.glob("builder_*.md"))
    assert active_builder_templates, f"No builder templates found in {template_dir}"

    for template_path in active_builder_templates:
        content = template_path.read_text(encoding="utf-8")
        assert "{{close_command}}" not in content, (
            f"{template_path.name} still contains {{{{close_command}}}}. "
            "CL-07: the launcher try/finally owns closeout; remove this injection."
        )


# ============================================================================
# WT-2026-200: Launcher/supervisor - resume sin supervisor fresco
# ============================================================================


def test_onlybuilder_resume_does_not_launch_supervisor() -> None:
    """WT-2026-200: -OnlyBuilder + -ResumeBuilder must NOT launch a fresh supervisor.

    The assignment $LaunchSupervisor = -not $OnlyBuilder ensures that
    when -OnlyBuilder is active, no supervisor is spawned even in resume mode.
    """
    content = SCRIPT_PATH.read_text(encoding="utf-8")

    # Core fix: the assignment must be conditional on -not $OnlyBuilder
    assert "$LaunchSupervisor = -not $OnlyBuilder" in content, (
        "Line 1151 must use conditional assignment so OnlyBuilder blocks supervisor"
    )

    # The OnlyBuilder guard at line 95 must remain intact
    assert "if ($OnlyBuilder) {" in content
    assert "$LaunchSupervisor = $false" in content


def test_builder_session_reuse_stays_intact_without_second_supervisor() -> None:
    """WT-2026-200: Builder session reuse must work without a second supervisor.

    The -ResumeBuilder path must still read builder_session.json and reuse
    the session ID even when -OnlyBuilder prevents supervisor launch.
    """
    content = SCRIPT_PATH.read_text(encoding="utf-8")

    # builder_session.json reading must still be present
    assert "builder_session.json" in content
    assert "$sessionData.ticket_id -eq $ticketId" in content
    assert "falling back to clean session" in content

    # Session reuse should not depend on supervisor state
    assert "--session" in content


def test_bootstrap_rejected_only_when_a_real_second_supervisor_exists() -> None:
    """WT-2026-200: Stale supervisor wait must remain for legitimately concurrent instances.

    The Wait-SupervisorExit logic must still be present for cases where a
    real stale supervisor exists (not triggered by -OnlyBuilder -ResumeBuilder).
    """
    content = SCRIPT_PATH.read_text(encoding="utf-8")

    # Stale supervisor wait must still be present
    assert "Wait-SupervisorExit" in content
    assert "supervisor_lock.txt" in content
    assert "TimeoutSeconds" in content
    assert "Cannot guarantee fresh supervisor" in content
    assert "stale supervisor did not exit within timeout" in content


def test_resume_builder_without_onlybuilder_preserves_supervisor_launch() -> None:
    """WT-2026-200: -ResumeBuilder sin -OnlyBuilder arranca supervisor fresco.

    When -OnlyBuilder is absent, the resume path must still launch a fresh
    supervisor (preserving the WP-2026-160 behavior).
    """
    content = SCRIPT_PATH.read_text(encoding="utf-8")

    # -not $OnlyBuilder is $true when $OnlyBuilder is absent → supervisor launches
    assert "$LaunchSupervisor = -not $OnlyBuilder" in content

    # The message about launching fresh supervisor must remain
    assert "Will launch fresh supervisor before Builder" in content

    # SUPERVISOR_RESTART_REASON must still be set for fresh supervisor
    assert "SUPERVISOR_RESTART_REASON" in content
    assert '"resume-builder"' in content


def test_normal_launch_without_flags_still_launches_supervisor() -> None:
    """WT-2026-200: Normal launch (no -ResumeBuilder) must still launch supervisor.

    The default parameter value of $LaunchSupervisor = $true must remain,
    so a normal `launch_agent_terminals.ps1` call starts supervisor.
    """
    content = SCRIPT_PATH.read_text(encoding="utf-8")

    # Default parameter must be $true
    assert "[switch]$LaunchSupervisor = $true" in content, (
        "Default parameter must be $true for normal launch"
    )

    # The supervisor launch gate must still exist
    assert "if ($LaunchSupervisor) {" in content
    assert "Start-AgentWindow -Title 'Supervisor'" in content
    assert "Supervisor: lanzado con ticket_supervisor.py --reactive" in content
