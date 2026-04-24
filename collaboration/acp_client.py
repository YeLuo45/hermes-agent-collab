"""
Direct AIAgent Client for Hermes Agent Team Collaboration.

Uses subprocess invocation of AIAgent directly, passing the API key explicitly
as ANTHROPIC_API_KEY (which is what AIAgent's resolve_anthropic_token() checks
for minimax-cn provider when api_key is not passed explicitly).

This bypasses the ACP adapter's asyncio/selector issues in sandboxed environments.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

_logger = logging.getLogger(__name__)

HERMES_AGENT_ROOT = Path.home() / ".hermes" / "hermes-agent"
VENV_PY = HERMES_AGENT_ROOT / "venv" / "bin" / "python"


@dataclass
class AgentResponse:
    """Response from the agent."""
    content: str
    stop_reason: str = "end_turn"
    session_id: Optional[str] = None


@dataclass
class DirectAgentClient:
    """
    Direct AIAgent client via subprocess.
    
    Passes the API key explicitly via ANTHROPIC_API_KEY env var, since
    AIAgent doesn't auto-read MINIMAX_CN_API_KEY for provider="minimax-cn".
    Also loads .env to ensure all credentials are available.
    """
    
    hermes_agent_root: Path = field(default_factory=lambda: HERMES_AGENT_ROOT)
    venv_python: Path = field(default_factory=lambda: VENV_PY)
    _session_id: Optional[str] = None
    
    def _build_env(self) -> dict:
        """Build environment with explicit API key for AIAgent."""
        env = {**os.environ}
        
        # AIAgent looks for these env vars:
        # - ANTHROPIC_API_KEY: used when provider is "minimax-cn" (explicitly skipped for resolve_anthropic_token)
        # - MINIMAX_CN_API_KEY: loaded from .env but NOT auto-used for minimax-cn provider
        # So we copy it to ANTHROPIC_API_KEY which AIAgent will use
        if "MINIMAX_CN_API_KEY" in env and "ANTHROPIC_API_KEY" not in env:
            env["ANTHROPIC_API_KEY"] = env["MINIMAX_CN_API_KEY"]
        
        # Also ensure .env is loaded for any other components
        dotenv_path = Path.home() / ".hermes" / ".env"
        if dotenv_path.exists():
            with open(dotenv_path) as f:
                for line in f:
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        key, _, value = line.partition("=")
                        env.setdefault(key.strip(), value.strip())
        
        return env
    
    def _run_sync(self, content: str, session_id: Optional[str] = None) -> AgentResponse:
        """
        Run AIAgent.chat() synchronously in a subprocess.
        Returns the response content.
        """
        import yaml
        from dotenv import load_dotenv
        
        # Load .env
        load_dotenv(Path.home() / ".hermes" / ".env")
        
        # Get config
        config_path = Path.home() / ".hermes" / "config.yaml"
        with open(config_path) as f:
            config = yaml.safe_load(f)
        model_cfg = config.get("model", {})
        
        # Get API key explicitly
        api_key = os.environ.get("MINIMAX_CN_API_KEY", "")
        
        # Build the script that calls AIAgent
        # Must pass api_key explicitly since AIAgent doesn't auto-read MINIMAX_CN_API_KEY for minimax-cn
        script = f"""
import sys, os, yaml, json
from pathlib import Path
from dotenv import load_dotenv

# Load .env
load_dotenv(Path.home() / ".hermes" / ".env")

# Set ANTHROPIC_API_KEY explicitly (what AIAgent checks for minimax-cn)
os.environ["ANTHROPIC_API_KEY"] = os.environ.get("MINIMAX_CN_API_KEY", "")

sys.path.insert(0, "{self.hermes_agent_root}")
from run_agent import AIAgent

config_path = Path.home() / ".hermes" / "config.yaml"
with open(config_path) as f:
    config = yaml.safe_load(f)
model_cfg = config.get("model", {{}})

api_key = os.environ.get("MINIMAX_CN_API_KEY", "")

ag = AIAgent(
    model=model_cfg.get("default", "MiniMax-M2.7"),
    base_url=model_cfg.get("base_url", ""),
    provider=model_cfg.get("provider", ""),
    api_key=api_key,  # Explicitly pass the API key
    platform="collab",
    quiet_mode=True,
    verbose_logging=False,
)

session_id = "{session_id or ''}"
if session_id:
    ag.session_id = session_id

try:
    result = ag.chat({json.dumps(content)})
    print(json.dumps({{"success": True, "content": result, "session_id": ag.session_id}}), flush=True)
except Exception as e:
    print(json.dumps({{"success": False, "error": str(e), "error_type": type(e).__name__}}), flush=True)
"""
        
        env = self._build_env()
        proc = subprocess.run(
            [str(self.venv_python), "-c", script],
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )
        
        if proc.returncode != 0:
            _logger.error("Agent subprocess failed: %s", proc.stderr[:500])
            return AgentResponse(content=f"Agent error: {proc.stderr[:200]}")
        
        try:
            result = json.loads(proc.stdout.strip())
            if result.get("success"):
                return AgentResponse(
                    content=result.get("content", ""),
                    session_id=result.get("session_id"),
                )
            else:
                return AgentResponse(content=f"Agent error: {result.get('error', 'unknown')}")
        except json.JSONDecodeError:
            _logger.error("Invalid JSON from agent: %s", proc.stdout[:200])
            return AgentResponse(content=f"Agent error: invalid response: {proc.stdout[:200]}")
    
    async def send_message(
        self,
        content: str,
        session_id: Optional[str] = None,
        timeout: float = 120.0,
    ) -> AgentResponse:
        """
        Send a message to the agent and get the response.
        
        Runs the subprocess synchronously in a thread pool to avoid blocking
        the asyncio event loop.
        """
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            self._run_sync,
            content,
            session_id or self._session_id,
        )
        if result.session_id:
            self._session_id = result.session_id
        return result
    
    async def close(self) -> None:
        """Close the client (no-op for subprocess model)."""
        self._session_id = None
        _logger.info("DirectAgentClient closed")


# Global client instance
_global_client: Optional[DirectAgentClient] = None


async def get_agent_client() -> DirectAgentClient:
    """Get or create the global agent client instance."""
    global _global_client
    if _global_client is None:
        _global_client = DirectAgentClient()
    return _global_client


async def close_agent_client() -> None:
    """Close the global agent client instance."""
    global _global_client
    if _global_client is not None:
        await _global_client.close()
        _global_client = None
