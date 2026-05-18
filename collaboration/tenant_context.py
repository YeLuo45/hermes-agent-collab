"""
Tenant isolation context and middleware.
Provides thread-local workspace context and cross-tenant access protection.
"""

from __future__ import annotations

import threading
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Optional

from fastapi import Request, HTTPException


# Context variable for tenant context (modern alternative to threading.local)
_tenant_context_var: ContextVar["TenantContext | None"] = ContextVar(
    "tenant_context", default=None
)


@dataclass
class TenantContext:
    """Immutable tenant context carried through the request lifecycle."""
    workspace_id: str
    user_id: Optional[str] = None
    is_admin: bool = False
    meta: dict = field(default_factory=dict)

    @property
    def tenant_id(self) -> str:
        return self.workspace_id


def get_current_tenant() -> TenantContext:
    """Get the current tenant context. Raises if not set."""
    ctx = _tenant_context_var.get()
    if ctx is None:
        raise RuntimeError("Tenant context not set — must be called within a request")
    return ctx


def set_tenant_context(ctx: TenantContext) -> None:
    """Set the current tenant context (typically called by middleware)."""
    _tenant_context_var.set(ctx)


def clear_tenant_context() -> None:
    """Clear the tenant context (typically called after request completes)."""
    _tenant_context_var.set(None)


class TenantIsolationMiddleware:
    """
    FastAPI middleware that:
    1. Extracts workspace_id from path or header
    2. Sets TenantContext for the request lifecycle
    3. Validates cross-tenant access attempts
    """

    HEADER_WORKSPACE = "X-Workspace-ID"
    HEADER_TENANT_ADMIN = "X-Tenant-Admin"
    HEADER_USER_ID = "X-User-ID"

    def __init__(self, app, allow_admin_override: bool = False):
        self.app = app
        self.allow_admin_override = allow_admin_override

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)

        # Extract workspace_id from path param or header
        workspace_id = request.path_params.get("workspace_id")
        if not workspace_id:
            workspace_id = request.headers.get(self.HEADER_WORKSPACE, "")

        user_id = request.headers.get(self.HEADER_USER_ID)
        is_admin = (
            self.allow_admin_override
            and request.headers.get(self.HEADER_TENANT_ADMIN, "").lower()
            in ("true", "1", "yes")
        )

        if workspace_id:
            ctx = TenantContext(
                workspace_id=workspace_id,
                user_id=user_id,
                is_admin=is_admin,
            )
            set_tenant_context(ctx)
        else:
            # No workspace context for routes that don't need it (e.g. health)
            set_tenant_context(None)

        try:
            await self.app(scope, receive, send)
        finally:
            clear_tenant_context()


def require_workspace_access(workspace_id: str) -> None:
    """
    Verify the current request has access to the specified workspace.
    Raises HTTPException 403 if access denied.
    """
    ctx = _tenant_context_var.get()
    if ctx is None:
        # No context means public route — allow
        return
    if ctx.is_admin:
        return
    if ctx.workspace_id != workspace_id:
        raise HTTPException(
            status_code=403,
            detail=f"Access denied to workspace {workspace_id}",
        )


def require_admin() -> None:
    """Verify the current request has admin privileges. Raises HTTPException 403."""
    ctx = _tenant_context_var.get()
    if ctx is None or not ctx.is_admin:
        raise HTTPException(
            status_code=403,
            detail="Admin access required",
        )
