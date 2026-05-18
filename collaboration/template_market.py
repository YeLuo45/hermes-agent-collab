"""
Workflow template market — publish, discover, install, and rate reusable workflow templates.
"""

from __future__ import annotations

import json
import uuid
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_log = __import__("logging").getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class Author:
    type: str   # "agent" | "user"
    id: str
    name: str = ""


@dataclass
class TemplateStats:
    installs: int = 0
    rating_sum: float = 0.0
    rating_count: int = 0

    @property
    def rating(self) -> float:
        if self.rating_count == 0:
            return 0.0
        return round(self.rating_sum / self.rating_count, 1)


@dataclass
class WorkflowTemplate:
    """A publishable workflow template."""
    name: str
    workflow: dict[str, Any]
    category: str = "custom"
    description: str = ""
    version: str = "1.0.0"
    min_app_version: str = "1.0.0"
    author: Author | None = None
    template_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    input_schema: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    stats: TemplateStats = field(default_factory=TemplateStats)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    is_published: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "template_id": self.template_id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "version": self.version,
            "min_app_version": self.min_app_version,
            "author": {"type": self.author.type, "id": self.author.id, "name": self.author.name} if self.author else None,
            "workflow": self.workflow,
            "input_schema": self.input_schema,
            "tags": self.tags,
            "stats": {
                "installs": self.stats.installs,
                "rating": self.stats.rating,
                "rating_count": self.stats.rating_count,
            },
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "is_published": self.is_published,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkflowTemplate:
        author = None
        if data.get("author"):
            a = data["author"]
            author = Author(type=a["type"], id=a["id"], name=a.get("name", ""))
        stats_data = data.get("stats", {})
        stats = TemplateStats(
            installs=stats_data.get("installs", 0),
            rating_sum=stats_data.get("rating_sum", stats_data.get("rating", 0) * stats_data.get("rating_count", 0)),
            rating_count=stats_data.get("rating_count", 0),
        )
        return cls(
            template_id=data.get("template_id", str(uuid.uuid4())),
            name=data["name"],
            description=data.get("description", ""),
            category=data.get("category", "custom"),
            version=data.get("version", "1.0.0"),
            min_app_version=data.get("min_app_version", "1.0.0"),
            author=author,
            workflow=data.get("workflow", {}),
            input_schema=data.get("input_schema", {}),
            tags=data.get("tags", []),
            stats=stats,
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
            updated_at=data.get("updated_at", datetime.now(timezone.utc).isoformat()),
            is_published=data.get("is_published", False),
        )


@dataclass
class TemplateListing:
    """Summary view of a template for list display."""
    template_id: str
    name: str
    description: str
    category: str
    version: str
    author_name: str
    tags: list[str]
    installs: int
    rating: float
    created_at: str


# ---------------------------------------------------------------------------
# Category registry
# ---------------------------------------------------------------------------

VALID_CATEGORIES = [
    "development",
    "testing",
    "deployment",
    "monitoring",
    "data-processing",
    "automation",
    "security",
    "custom",
]


# ---------------------------------------------------------------------------
# Template Market
# ---------------------------------------------------------------------------

class TemplateMarket:
    """
    Local template market for publishing, discovering, and installing workflow templates.

    Storage: ~/.hermes/collab/templates/
    - index.json          — template metadata index
    - {template_id}.json — full template data

    Usage:
        market = TemplateMarket()

        # Publish
        tmpl = WorkflowTemplate(
            name="Code Review",
            workflow={"steps": [...]},
            category="development",
            author=Author(type="user", id="u1", name="Alice"),
        )
        market.publish(tmpl)

        # Discover
        results = market.discover(category="development", tags=["pr"], query="review", page=1)

        # Install
        wf_id = market.install("template-id", workspace_id="ws1")
    """

    DEFAULT_MARKET_DIR = Path("~/.hermes/collab/templates").expanduser()

    def __init__(self, market_dir: str | Path | None = None):
        self._dir = Path(market_dir or self.DEFAULT_MARKET_DIR)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self._dir / "index.json"
        self._lock = threading.Lock()
        self._load_index()

    # ---- Index management ----

    def _load_index(self) -> None:
        if self._index_path.exists():
            try:
                with open(self._index_path) as f:
                    self._index: dict[str, dict[str, Any]] = json.load(f)
            except (json.JSONDecodeError, OSError):
                self._index = {}
        else:
            self._index = {}

    def _save_index(self) -> None:
        with self._lock:
            with open(self._index_path, "w") as f:
                json.dump(self._index, f, indent=2)

    def _template_path(self, template_id: str) -> Path:
        return self._dir / f"{template_id}.json"

    # ---- CRUD ----

    def publish(self, template: WorkflowTemplate) -> str:
        """
        Publish a workflow template to the market.

        Returns the template_id.
        """
        template.is_published = True
        template.updated_at = datetime.now(timezone.utc).isoformat()

        # Save full template
        tmpl_path = self._template_path(template.template_id)
        with open(tmpl_path, "w") as f:
            json.dump(template.to_dict(), f, indent=2)

        # Update index
        self._index[template.template_id] = {
            "template_id": template.template_id,
            "name": template.name,
            "description": template.description,
            "category": template.category,
            "version": template.version,
            "author_name": template.author.name if template.author else "",
            "tags": template.tags,
            "stats": {
                "installs": template.stats.installs,
                "rating": template.stats.rating,
            },
            "created_at": template.created_at,
            "updated_at": template.updated_at,
            "is_published": True,
        }
        self._save_index()

        _log.info("Template published: %s (%s)", template.name, template.template_id)
        return template.template_id

    def get(self, template_id: str) -> WorkflowTemplate | None:
        """Get a template by ID."""
        tmpl_path = self._template_path(template_id)
        if not tmpl_path.exists():
            return None
        try:
            with open(tmpl_path) as f:
                data = json.load(f)
            return WorkflowTemplate.from_dict(data)
        except (json.JSONDecodeError, OSError):
            return None

    def update(self, template: WorkflowTemplate) -> None:
        """Update an existing template."""
        template.updated_at = datetime.now(timezone.utc).isoformat()
        tmpl_path = self._template_path(template.template_id)
        with open(tmpl_path, "w") as f:
            json.dump(template.to_dict(), f, indent=2)
        if template.template_id in self._index:
            self._index[template.template_id]["version"] = template.version
            self._index[template.template_id]["updated_at"] = template.updated_at
        self._save_index()

    def unpublish(self, template_id: str) -> bool:
        """Remove a template from the market (soft delete)."""
        if template_id not in self._index:
            return False
        del self._index[template_id]
        self._save_index()
        _log.info("Template unpublished: %s", template_id)
        return True

    # ---- Discovery ----

    def discover(
        self,
        category: str | None = None,
        tags: list[str] | None = None,
        query: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> list[TemplateListing]:
        """
        Discover templates with filters.

        Args:
            category: Filter by category (exact match)
            tags: Filter by tags (all must match)
            query: Full-text search in name + description
            page: Page number (1-indexed)
            page_size: Results per page (default 20)

        Returns:
            List of TemplateListing sorted by installs descending
        """
        results: list[TemplateListing] = []

        for tid, meta in self._index.items():
            if not meta.get("is_published", False):
                continue

            # Category filter
            if category and meta.get("category") != category:
                continue

            # Tags filter
            if tags:
                template_tags = set(meta.get("tags", []))
                if not all(t in template_tags for t in tags):
                    continue

            # Text query
            if query:
                q = query.lower()
                name = meta.get("name", "").lower()
                desc = meta.get("description", "").lower()
                if q not in name and q not in desc:
                    continue

            stats = meta.get("stats", {})
            results.append(TemplateListing(
                template_id=tid,
                name=meta.get("name", ""),
                description=meta.get("description", ""),
                category=meta.get("category", "custom"),
                version=meta.get("version", "1.0.0"),
                author_name=meta.get("author_name", ""),
                tags=meta.get("tags", []),
                installs=stats.get("installs", 0),
                rating=stats.get("rating", 0.0),
                created_at=meta.get("created_at", ""),
            ))

        # Sort by installs descending
        results.sort(key=lambda x: x.installs, reverse=True)

        # Paginate
        start = (page - 1) * page_size
        end = start + page_size
        return results[start:end]

    def list_categories(self) -> list[dict[str, Any]]:
        """List all categories with template counts."""
        counts: dict[str, int] = {cat: 0 for cat in VALID_CATEGORIES}
        for meta in self._index.values():
            if meta.get("is_published"):
                cat = meta.get("category", "custom")
                if cat in counts:
                    counts[cat] += 1
                else:
                    counts.setdefault(cat, 0)
                    counts[cat] = counts.get(cat, 0) + 1

        return [
            {"id": cat, "count": counts[cat]}
            for cat in VALID_CATEGORIES
            if counts[cat] > 0
        ]

    # ---- Install ----

    def install(
        self,
        template_id: str,
        workspace_id: str,
        workspace_dir: Path | None = None,
    ) -> str:
        """
        Install a template into a workspace as a new workflow.

        Args:
            template_id: ID of the template to install
            workspace_id: Target workspace ID
            workspace_dir: Override workspace data directory

        Returns:
            The new workflow_id
        """
        template = self.get(template_id)
        if template is None:
            raise ValueError(f"Template not found: {template_id}")

        # Create workflow from template
        workflow_id = str(uuid.uuid4())
        new_workflow = {
            "workflow_id": workflow_id,
            "template_id": template_id,
            "name": f"{template.name} (copy)",
            "version": template.version,
            "status": "active",
            "steps": template.workflow.get("steps", []),
            "parallel_stages": template.workflow.get("parallel_stages", []),
            "conditional_branches": template.workflow.get("conditional_branches", {}),
            "input_schema": template.input_schema,
            "created_from_template": template_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        # Save to workspace workflows dir
        if workspace_dir is None:
            workspace_dir = Path("~/.hermes/collab").expanduser() / workspace_id
        wf_dir = workspace_dir / "workflows"
        wf_dir.mkdir(parents=True, exist_ok=True)
        wf_path = wf_dir / f"{workflow_id}.json"
        with open(wf_path, "w") as f:
            json.dump(new_workflow, f, indent=2)

        # Update install count
        template.stats.installs += 1
        self.update(template)

        _log.info("Template %s installed as workflow %s in workspace %s",
                  template_id, workflow_id, workspace_id)
        return workflow_id

    # ---- Rating ----

    def rate(self, template_id: str, user_id: str, rating: float) -> None:
        """
        Rate a template (1.0 - 5.0).
        Each user can only rate once (latest rating replaces previous).
        """
        if not (1.0 <= rating <= 5.0):
            raise ValueError("Rating must be between 1.0 and 5.0")

        template = self.get(template_id)
        if template is None:
            raise ValueError(f"Template not found: {template_id}")

        # Load or create ratings index
        ratings_path = self._dir / f"{template_id}_ratings.json"
        try:
            with open(ratings_path) as f:
                ratings: dict[str, float] = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            ratings = {}

        old_rating = ratings.get(user_id)
        ratings[user_id] = rating

        with open(ratings_path, "w") as f:
            json.dump(ratings, f)

        # Update stats
        if old_rating is not None:
            template.stats.rating_sum = template.stats.rating_sum - old_rating + rating
        else:
            template.stats.rating_count += 1
            template.stats.rating_sum += rating

        self.update(template)
        _log.info("Template %s rated %.1f by user %s", template_id, rating, user_id)

    # ---- Remote template import ----

    def install_from_url(self, url: str, workspace_id: str) -> str:
        """
        Install a template from a remote HTTP URL.
        The URL should point to a JSON file with a valid template structure.
        """
        import urllib.request

        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.load(resp)
        except Exception as e:
            raise ValueError(f"Failed to fetch template from URL: {e}")

        # Validate basic structure
        if "name" not in data or "workflow" not in data:
            raise ValueError("Remote template must have 'name' and 'workflow' fields")

        template = WorkflowTemplate.from_dict(data)
        template.is_published = False  # Don't re-publish remote template
        return self.install(template.template_id, workspace_id)

    # ---- Stats ----

    def get_stats(self, template_id: str) -> dict[str, Any] | None:
        """Get template stats."""
        template = self.get(template_id)
        if template is None:
            return None
        return {
            "template_id": template_id,
            "installs": template.stats.installs,
            "rating": template.stats.rating,
            "rating_count": template.stats.rating_count,
        }

    def total_templates(self) -> int:
        return len([m for m in self._index.values() if m.get("is_published")])
