"""Skill System for Hermes Agent Team Collaboration.
Manages skills, categories, and skill matching.
"""

import json
import uuid
from pathlib import Path
from typing import Optional

try:
    from .models import Skill, SkillCategory
    from .storage import JsonFileStore
except ImportError:
    from collaboration.models import Skill, SkillCategory
    from collaboration.storage import JsonFileStore


class SkillSystem:
    """Manages skills and agent skill assignments."""

    def __init__(self, workspace_id: str = None):
        if workspace_id:
            from collaboration.storage import ensure_workspace_files
            ws_path = ensure_workspace_files(workspace_id)
            self._workspace_id = workspace_id
            self.store = JsonFileStore.for_skills(ws_path)
        else:
            from collaboration.storage import HERMES_HOME
            self._workspace_id = None
            self.base_path = HERMES_HOME / "collab"
            self.base_path.mkdir(parents=True, exist_ok=True)
            self.store = JsonFileStore.for_skills(self.base_path)

    def create_skill(
        self,
        name: str,
        category: SkillCategory,
        description: str = "",
        config: dict = None,
        version: str = "1.0.0"
    ) -> Skill:
        """Create a new skill."""
        skill_id = f"skill_{uuid.uuid4().hex[:12]}"
        skill = Skill(
            skill_id=skill_id,
            name=name,
            category=category,
            description=description,
            config=config or {},
            version=version
        )
        self.store.upsert(skill)
        return skill

    def get_skill(self, skill_id: str) -> Optional[Skill]:
        """Get skill by ID."""
        return self.store.get(skill_id)

    def update_skill(
        self,
        skill_id: str,
        name: str = None,
        description: str = None,
        config: dict = None,
        enabled: bool = None
    ) -> Optional[Skill]:
        """Update skill properties."""
        skill = self.get_skill(skill_id)
        if not skill:
            return None

        if name is not None:
            skill.name = name
        if description is not None:
            skill.description = description
        if config is not None:
            skill.config.update(config)
        if enabled is not None:
            skill.enabled = enabled

        from datetime import datetime
        skill.updated_at = datetime.utcnow().isoformat()
        self.store.upsert(skill)
        return skill

    def delete_skill(self, skill_id: str) -> bool:
        """Delete a skill."""
        return self.store.delete(skill_id)

    def enable_skill(self, skill_id: str) -> bool:
        """Enable a skill."""
        skill = self.get_skill(skill_id)
        if not skill:
            return False
        skill.enabled = True
        self.store.upsert(skill)
        return True

    def disable_skill(self, skill_id: str) -> bool:
        """Disable a skill."""
        skill = self.get_skill(skill_id)
        if not skill:
            return False
        skill.enabled = False
        self.store.upsert(skill)
        return True

    def list_skills(
        self,
        category: SkillCategory = None,
        enabled: bool = None
    ) -> list[Skill]:
        """List skills with optional filtering."""
        skills = self.store.list()
        result = []
        for skill in skills:
            if category and skill.category != category:
                continue
            if enabled is not None and skill.enabled != enabled:
                continue
            result.append(skill)
        return result

    def get_skills_by_category(self, category: SkillCategory) -> list[Skill]:
        """Get all skills in a category."""
        return self.list_skills(category=category, enabled=True)

    def get_enabled_skills(self) -> list[Skill]:
        """Get all enabled skills."""
        return self.list_skills(enabled=True)

    def search_skills(self, query: str, category: SkillCategory = None) -> list[Skill]:
        """Search skills by name or description."""
        skills = self.list_skills(category=category)
        query_lower = query.lower()
        return [
            skill for skill in skills
            if query_lower in skill.name.lower() or query_lower in skill.description.lower()
        ]

    def get_skill_categories(self) -> list[SkillCategory]:
        """Get all used skill categories."""
        skills = self.store.list()
        categories = set()
        for skill in skills:
            if skill.category:
                categories.add(skill.category)
        return list(categories)

    def import_skills(self, skills_data: list[dict]) -> list[Skill]:
        """Import multiple skills."""
        imported = []
        for data in skills_data:
            if "skill_id" not in data:
                continue
            skill = Skill.from_dict(data)
            self.store.upsert(skill)
            imported.append(skill)
        return imported

    def export_skills(self, skill_ids: list[str] = None) -> list[dict]:
        """Export skills as dicts."""
        if skill_ids:
            skills = [self.get_skill(sid) for sid in skill_ids]
            return [s.to_dict() for s in skills if s]
        else:
            skills = self.list_skills()
            return [s.to_dict() for s in skills]

    def get_skill_stats(self) -> dict:
        """Get skill statistics."""
        skills = self.store.list()
        categories = {}
        enabled_count = 0

        for skill in skills:
            cat = skill.category.value if hasattr(skill.category, 'value') else str(skill.category)
            categories[cat] = categories.get(cat, 0) + 1
            if skill.enabled:
                enabled_count += 1

        return {
            "total": len(skills),
            "enabled": enabled_count,
            "disabled": len(skills) - enabled_count,
            "by_category": categories
        }


def load_skills_from_directory(skills_dir: str = "~/.hermes/skills") -> list[dict]:
    """Load skill definitions from directory structure."""
    skills_dir = Path(skills_dir).expanduser()
    skills = []

    for skill_path in skills_dir.iterdir():
        if not skill_path.is_dir():
            continue

        manifest_path = skill_path / "manifest.json"
        if manifest_path.exists():
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    skill_data = json.load(f)
                    skills.append(skill_data)
            except (json.JSONDecodeError, IOError):
                continue

    return skills
