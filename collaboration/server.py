#!/usr/bin/env python3
"""
Hermes Agent Team Collaboration Server.
Serves both the REST API and the Web UI dashboard.

Usage:
    python -m collab.server                    # Start on default port 9119
    python -m collab.server --port 8080      # Custom port
    python -m collab.server --host 0.0.0.0    # Public binding
    python -m collab.server --web-only        # Serve only the web UI (no API)
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Add parent directory (hermes-agent/) to path so 'collab' package can be found
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
import uvicorn

# Import collaboration modules
from collaboration import (
    WorkspaceManager, AgentRegistry, TaskManager, 
    SkillSystem, RuntimeMonitor, __version__
)
from collaboration.collab_api import router as collab_router

_log = logging.getLogger(__name__)

# Base paths
COLLAB_BASE = Path("~/.hermes/collab").expanduser()
COLLAB_BASE.mkdir(parents=True, exist_ok=True)

# Web UI dist path
WEB_DIST = Path(__file__).parent.parent / "hermes-collab-web" / "dist"
FALLBACK_WEB_DIST = Path("/home/hermes/hermes-collab-web/dist")


def get_web_dist() -> Path:
    """Find the web UI dist directory."""
    if WEB_DIST.exists():
        return WEB_DIST
    if FALLBACK_WEB_DIST.exists():
        return FALLBACK_WEB_DIST
    return None


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Hermes Agent Collaboration API",
        version=__version__,
        description="REST API for team collaboration features"
    )
    
    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Mount static files for web UI if available
    web_dist = get_web_dist()
    if web_dist and web_dist.exists():
        app.mount("/assets", StaticFiles(directory=str(web_dist / "assets")), name="assets")
    
    # Include collaboration API router
    app.include_router(collab_router)
    
    # SPA fallback for web UI routes (only non-API paths)
    if web_dist and web_dist.exists():
        @app.get("/{full_path:path}")
        async def serve_spa(full_path: str):
            # Don't intercept API calls - let collab_router handle them
            if full_path.startswith("api/"):
                from fastapi.responses import JSONResponse
                return JSONResponse({"detail": "Not Found"}, status_code=404)
            file_path = web_dist / full_path
            if full_path and file_path.exists() and file_path.is_file():
                return FileResponse(file_path)
            return FileResponse(str(web_dist / "index.html"))
    
    # Root redirect to web UI
    @app.get("/")
    async def root():
        if web_dist and web_dist.exists():
            return FileResponse(str(web_dist / "index.html"))
        return {
            "service": "Hermes Agent Collaboration API",
            "version": __version__,
            "endpoints": {
                "workspaces": "/api/collab/workspaces",
                "agents": "/api/collab/agents",
                "tasks": "/api/collab/tasks",
                "skills": "/api/collab/skills",
                "monitor": "/api/collab/monitor",
                "websocket": "/api/collab/ws"
            }
        }
    
    # Health check
    @app.get("/health")
    async def health():
        return {"status": "healthy", "version": __version__}
    
    return app


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Hermes Agent Team Collaboration Server"
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host to bind to (default: 127.0.0.1)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=9119,
        help="Port to bind to (default: 9119)"
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload for development"
    )
    parser.add_argument(
        "--log-level",
        default="info",
        choices=["debug", "info", "warning", "error"],
        help="Log level"
    )
    
    args = parser.parse_args()
    
    # Configure logging
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    # Check for web UI
    web_dist = get_web_dist()
    if web_dist and web_dist.exists():
        _log.info(f"Serving web UI from: {web_dist}")
    else:
        _log.warning("Web UI not found - serving API only")
        _log.warning("Build with: cd hermes-collab-web && npm run build")
    
    # Create and run app
    app = create_app()
    
    _log.info(f"Starting Hermes Collaboration Server on {args.host}:{args.port}")
    _log.info("Endpoints:")
    _log.info("  - REST API: /api/collab/*")
    _log.info("  - WebSocket: /api/collab/ws")
    if web_dist and web_dist.exists():
        _log.info("  - Web UI: / (or /index.html)")
    
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=args.log_level
    )


if __name__ == "__main__":
    main()
