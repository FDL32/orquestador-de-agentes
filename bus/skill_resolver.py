"""
Skill Resolver - Role-based skill filtering and validation.

WP-2026-127: Implements skill filtering by role allowlist,
early validation of skill references, and separation of
discovery (discover_skills.py) from routing/permissions.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from .exceptions import (
    EmptySkillCatalogError,
    SkillAccessDeniedError,
    SkillNotFoundError,
)


class SkillResolver:
    """Resolves and filters skills by role allowlist.

    Before: All roles could access all discovered skills.
    During: Each role has an allowlist; skills are filtered before prompt building.
    After: Roles only see skills they are permitted to use.

    Attributes:
        project_root: Root path of the project.
        role_allowlists: Mapping of role -> list of allowed skill names/triggers.
        discovered_skills: Cache of discovered skills from discover_skills.py.
    """

    def __init__(
        self,
        project_root: Path,
        role_allowlists: dict[str, list[str]] | None = None,
    ):
        self.project_root = Path(project_root)
        self.role_allowlists = role_allowlists or self._load_default_allowlists()
        self._discovered_skills: dict[str, dict[str, Any]] | None = None

    def _load_default_allowlists(self) -> dict[str, list[str]]:
        """Load default role allowlists from agents.json or use fallback.

        Fallback allowlists (if agents.json doesn't define skill_allowlists):
        - BUILDER: All implementation and testing skills
        - MANAGER: All review and audit skills
        - SUPERVISOR: All orchestration skills
        """
        config_path = self.project_root / ".agent" / "config" / "agents.json"
        if config_path.exists():
            try:
                config = json.loads(config_path.read_text(encoding="utf-8"))
                allowlists = config.get("skill_allowlists", {})
                if allowlists:
                    return allowlists
            except (json.JSONDecodeError, OSError):
                pass

        # Fallback defaults
        return {
            "BUILDER": [
                "/impl",
                "/implement",
                "/tdd",
                "/test",
                "/debug",
                "/refactor",
                "/fix",
            ],
            "MANAGER": [
                "/review",
                "/audit",
                "/validate",
                "/inspect",
                "/compare",
            ],
            "SUPERVISOR": [
                "/orchestrate",
                "/schedule",
                "/archive",
                "/report",
            ],
        }

    def _discover_skills(self) -> dict[str, dict[str, Any]]:
        """Discover skills using discover_skills.py module.

        Before: Empty catalogs were returned silently.
        During: Validates that at least one skill was discovered.
        After: Raises EmptySkillCatalogError if no skills found.

        Returns:
            Dictionary of skill_name -> skill_info (path, triggers, etc.)

        Raises:
            EmptySkillCatalogError: If no skills were discovered.
        """
        if self._discovered_skills is not None:
            return self._discovered_skills

        try:
            from scripts.discover_skills import discover_skills

            result = discover_skills()
            # Build a map by skill name
            skills_map = {}
            for skill in result.get("skills", []):
                skills_map[skill["name"]] = skill
            self._discovered_skills = skills_map

            # WP-2026-128: Treat empty catalog as infrastructure error
            if not skills_map:
                raise EmptySkillCatalogError(
                    project_root=self.project_root,
                    skills_dir=self.project_root / "skills",
                )

            return skills_map
        except ImportError:
            raise EmptySkillCatalogError(
                project_root=self.project_root, skills_dir=self.project_root / "skills"
            ) from None

    def get_allowed_skills(self, role: str) -> list[dict[str, Any]]:
        """Get list of skills allowed for a role.

        Before: All discovered skills were returned regardless of role.
        During: Filters discovered skills by role allowlist (name or trigger match).
        After: Returns only skills whose name or any trigger is in the allowlist.

        Args:
            role: Role name (e.g., "BUILDER", "MANAGER", "SUPERVISOR").

        Returns:
            List of skill info dicts for allowed skills.
        """
        allowlist = self.role_allowlists.get(role, [])
        if not allowlist:
            return []

        skills = self._discover_skills()
        allowed = []

        for skill_name, skill_info in skills.items():
            # Check if skill name is in allowlist
            if skill_name in allowlist:
                allowed.append(skill_info)
                continue
            # Check if any trigger is in allowlist
            triggers = skill_info.get("triggers", [])
            if any(trigger in allowlist for trigger in triggers):
                allowed.append(skill_info)

        return allowed

    def get_allowed_triggers(self, role: str) -> dict[str, str]:
        """Get trigger -> skill_path mapping for allowed skills.

        Before: Trigger map included all skills.
        During: Filters trigger map to only include allowed skills for role.
        After: Returns trigger map that only resolves to permitted skills.

        Args:
            role: Role name.

        Returns:
            Dictionary of trigger -> skill_path for allowed skills.
        """
        allowed_skills = self.get_allowed_skills(role)
        trigger_map = {}

        for skill_info in allowed_skills:
            skill_path = skill_info.get("path", "")
            skill_file = skill_info.get("skill_file", "")
            triggers = skill_info.get("triggers", [])

            for trigger in triggers:
                # Prefer skill_file if available (more specific path)
                trigger_map[trigger] = skill_file if skill_file else skill_path

        return trigger_map

    def validate_skill_access(
        self, skill_name: str, role: str, raise_on_denied: bool = True
    ) -> bool:
        """Validate that a role can access a skill.

        Before: No validation of skill access by role.
        During: Checks if skill is in role's allowlist.
        After: Returns True if access allowed, raises or returns False if denied.

        Args:
            skill_name: Name or trigger of the skill to validate.
            role: Role requesting access.
            raise_on_denied: If True, raises SkillAccessDeniedError on denial.

        Returns:
            True if access is allowed.

        Raises:
            SkillAccessDeniedError: If access denied and raise_on_denied=True.
        """
        allowed_skills = self.get_allowed_skills(role)
        allowed_names = {s["name"] for s in allowed_skills}
        allowed_triggers = set()
        for s in allowed_skills:
            allowed_triggers.update(s.get("triggers", []))

        if skill_name in allowed_names or skill_name in allowed_triggers:
            return True

        if raise_on_denied:
            allowlist = self.role_allowlists.get(role, [])
            raise SkillAccessDeniedError(
                skill_name=skill_name,
                role=role,
                allowlist=allowlist,
            )
        return False

    def resolve_skill(
        self, skill_name: str, role: str | None = None
    ) -> dict[str, Any] | None:
        """Resolve a skill by name or trigger, optionally validating role access.

        Before: Skills resolved without role checking.
        During: Can optionally validate that role has access to the skill.
        After: Returns skill info or None if not found/denied.

        Args:
            skill_name: Name or trigger of the skill to resolve.
            role: Optional role to validate access for.

        Returns:
            Skill info dict if found and allowed, None otherwise.

        Raises:
            SkillNotFoundError: If skill not found in catalog.
            SkillAccessDeniedError: If role doesn't have access (when role provided).
        """
        skills = self._discover_skills()

        # Try to find by name first
        if skill_name in skills:
            skill_info = skills[skill_name]
            if role:
                self.validate_skill_access(skill_name, role, raise_on_denied=True)
            return skill_info

        # Try to find by trigger
        for s_name, s_info in skills.items():
            if skill_name in s_info.get("triggers", []):
                if role:
                    self.validate_skill_access(s_name, role, raise_on_denied=True)
                return s_info

        # Not found
        raise SkillNotFoundError(skill_name=skill_name, role=role)

    def filter_skills_for_prompt(
        self,
        role: str,
        include_metadata: bool = True,
    ) -> str:
        """Build a skill list string for inclusion in prompts.

        Before: Prompts included all available skills.
        During: Builds skill list filtered by role allowlist.
        After: Returns formatted skill list for prompt injection.

        Args:
            role: Role to filter skills for.
            include_metadata: Whether to include skill descriptions.

        Returns:
            Formatted string listing allowed skills.
        """
        allowed = self.get_allowed_skills(role)
        if not allowed:
            return "No skills available for this role."

        lines = ["Available skills for this role:"]
        for skill in allowed:
            name = skill.get("name", "Unknown")
            triggers = skill.get("triggers", [])
            trigger_str = ", ".join(triggers) if triggers else "N/A"
            if include_metadata:
                desc = skill.get("description", "")
                lines.append(f"  - {name} (triggers: {trigger_str})")
                if desc:
                    lines.append(f"    {desc}")
            else:
                lines.append(f"  - {name} ({trigger_str})")

        return "\n".join(lines)

    def validate_allowlists_against_catalog(self) -> list[str]:
        """Validate that all skills in allowlists exist in the discovered catalog.

        Before: Allowlists could reference non-existent skills silently.
        During: Cross-references each allowlist entry against discovered skills
                by name and trigger. Collects warnings for missing references.
        After: Returns list of warning strings for missing skill references.

        Returns:
            List of warning messages for skills in allowlists that don't exist.
            Empty list if all allowlist entries are valid.
        """
        warnings = []
        skills = self._discover_skills()
        all_skill_names = set(skills.keys())
        all_triggers = set()
        for skill_info in skills.values():
            all_triggers.update(skill_info.get("triggers", []))

        for role, allowlist in self.role_allowlists.items():
            missing = [
                f"skill_allowlists[{role}] references non-existent skill/trigger: '{entry}'"
                for entry in allowlist
                if entry not in all_skill_names and entry not in all_triggers
            ]
            warnings.extend(missing)

        return warnings


def create_resolver(
    project_root: Path,
    config_path: Path | None = None,
    validate: bool = True,
) -> SkillResolver:
    """Factory function to create a SkillResolver with config from agents.json.

    Before: Factory created resolver without validation.
    During: Optionally validates allowlists against catalog and raises on empty catalog.
    After: Returns validated resolver or raises EmptySkillCatalogError.

    Args:
        project_root: Root path of the project.
        config_path: Optional path to agents.json.
        validate: If True, validates allowlists and raises on empty catalog.

    Returns:
        Configured SkillResolver instance.

    Raises:
        EmptySkillCatalogError: If validate=True and no skills discovered.
    """
    if config_path is None:
        config_path = project_root / ".agent" / "config" / "agents.json"

    allowlists = None
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
            allowlists = config.get("skill_allowlists")
        except (json.JSONDecodeError, OSError):
            pass

    resolver = SkillResolver(project_root=project_root, role_allowlists=allowlists)

    if validate:
        # This will raise EmptySkillCatalogError if catalog is empty
        resolver._discover_skills()
        # Collect warnings for missing allowlist references (non-blocking)
        warnings = resolver.validate_allowlists_against_catalog()
        for warning in warnings:
            print(f"[skill-resolver] WARNING: {warning}", file=sys.stderr)

    return resolver
