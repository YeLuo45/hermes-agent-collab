"""
ACP Client for Hermes Agent Team Collaboration.

Spawns the Hermes ACP adapter as a subprocess and communicates via ACP protocol
over stdio, properly inheriting .env credentials and session state.

Usage:
    client = ACPClient()
    response = await client.send_message("Hello agent", session_id="default")
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

_logger = logging.getLogger(__name__)

# ACP library imports (installed in hermes-agent venv)
HERMES_AGENT_ROOT = Path.home() / ".hermes" / "hermes-agent"
VENV_PY = HERMES_AGENT_ROOT / "venv" / "bin" / "python"


@dataclass
class ACPMessage:
    """Represents a message in ACP protocol format."""
    role: str
    content: str
    name: Optional[str] = None


@dataclass 
class ACPResponse:
    """Represents a response from the ACP agent."""
    content: str
    stop_reason: str = "end_turn"
    session_id: Optional[str] = None


@dataclass
class ACPClient:
    """
    ACP client that communicates with Hermes Agent via the ACP protocol.
    
    Spawns the ACP adapter as a subprocess to ensure proper .env loading
    and uses stdio for communication (same as VS Code/Zed extensions).
    """
    
    hermes_agent_root: Path = field(default_factory=lambda: HERMES_AGENT_ROOT)
    venv_python: Path = field(default_factory=lambda: VENV_PY)
    _process: Optional[asyncio.subprocess.Process] = None
    _reader: Optional[asyncio.StreamReader] = None
    _writer: Optional[asyncio.StreamWriter] = None
    _connected: bool = False
    _session_id: Optional[str] = None
    
    async def connect(self, session_id: Optional[str] = None) -> str:
        """
        Start the ACP adapter subprocess and establish connection.
        
        Args:
            session_id: Optional session ID to resume. If not provided, a new session is created.
            
        Returns:
            The session ID used for this connection.
        """
        if self._connected:
            return self._session_id or ""
        
        self._session_id = session_id or str(uuid.uuid4())[:8]
        
        # Spawn the ACP adapter subprocess
        # The adapter handles .env loading internally via entry.py
        cmd = [
            str(self.venv_python),
            "-m", "acp_adapter.entry",
        ]
        
        _logger.info(f"Starting ACP adapter: {' '.join(cmd)}")
        
        self._process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=os.environ.copy(),  # Inherit full environment
        )
        
        self._reader = self._process.stdout
        self._writer = self._process.stdin
        
        # Wait for initialization
        await self._wait_for_ready()
        
        self._connected = True
        _logger.info(f"ACP client connected, session_id={self._session_id}")
        
        return self._session_id
    
    async def _wait_for_ready(self, timeout: float = 10.0) -> None:
        """Wait for the ACP adapter to be ready by reading until we get a JSON-RPC handshake."""
        import json
        
        # The ACP adapter sends JSON-RPC initialize request
        # We need to send an initialize response
        start = asyncio.get_event_loop().time()
        
        while (asyncio.get_event_loop().time() - start) < timeout:
            if self._reader is None:
                break
            line = await asyncio.wait_for(self._reader.readline(), timeout=2.0)
            if not line:
                # Process ended
                stderr = await self._process.stderr.read() if self._process and self._process.stderr else b""
                raise RuntimeError(f"ACP adapter process ended unexpectedly: {stderr.decode()}")
            
            try:
                msg = json.loads(line.decode().strip())
                if msg.get("method") == "initialize":
                    # Send initialize response
                    init_response = {
                        "jsonrpc": "2.0",
                        "id": msg.get("id"),
                        "result": {
                            "protocolVersion": 1,
                            "agentInfo": {"name": "collab-client", "version": "1.0"},
                            "authMethods": None,
                            "clientCapabilities": {
                                "sampling": None,
                                "roots": None,
                            }
                        }
                    }
                    await self._send_jsonrpc(init_response)
                    break
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
        
        # Send initialized notification
        await self._send_jsonrpc({
            "jsonrpc": "2.0",
            "method": "initialized",
            "params": {}
        })
    
    async def _send_jsonrpc(self, msg: dict) -> None:
        """Send a JSON-RPC message."""
        import json
        if self._writer is None:
            raise RuntimeError("Not connected")
        line = json.dumps(msg) + "\n"
        self._writer.write(line.encode())
        await self._writer.drain()
    
    async def _read_jsonrpc(self, timeout: float = 60.0) -> dict:
        """Read a JSON-RPC message with timeout."""
        import json
        if self._reader is None:
            raise RuntimeError("Not connected")
        line = await asyncio.wait_for(self._reader.readline(), timeout=timeout)
        if not line:
            raise RuntimeError("ACP adapter closed connection")
        return json.loads(line.decode().strip())
    
    async def send_message(
        self,
        content: str,
        session_id: Optional[str] = None,
        timeout: float = 60.0,
    ) -> ACPResponse:
        """
        Send a message to the Hermes agent and get the response.
        
        Args:
            content: The message content to send
            session_id: Session ID to use. Creates new if not provided.
            timeout: Maximum time to wait for response in seconds.
            
        Returns:
            ACPResponse with the agent's reply
        """
        await self.connect(session_id)
        
        import json
        
        # Create or resume session
        if session_id and session_id != self._session_id:
            # Load existing session
            request = {
                "jsonrpc": "2.0",
                "id": str(uuid.uuid4()),
                "method": "loadSession",
                "params": {
                    "sessionId": session_id,
                    "cwd": str(Path.cwd()),
                }
            }
        else:
            # Create new session
            request = {
                "jsonrpc": "2.0",
                "id": str(uuid.uuid4()),
                "method": "newSession",
                "params": {
                    "cwd": str(Path.cwd()),
                }
            }
        
        await self._send_jsonrpc(request)
        resp = await self._read_jsonrpc(timeout=timeout)
        
        if "result" in resp:
            self._session_id = resp["result"].get("sessionId", self._session_id)
        
        # Send the prompt
        prompt_request = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "prompt",
            "params": {
                "sessionId": self._session_id,
                "prompt": [
                    {
                        "type": "text",
                        "text": content
                    }
                ]
            }
        }
        
        await self._send_jsonrpc(prompt_request)
        
        # Read response(s) - may be multiple messages
        final_content = ""
        stop_reason = "end_turn"
        
        while True:
            resp = await self._read_jsonrpc(timeout=timeout)
            
            if resp.get("method") == "prompt":
                # This is a prompt result
                result = resp.get("result", {})
                stop_reason = result.get("stopReason", "end_turn")
                
                # Get text content from response
                message = result.get("message", {})
                content_blocks = message.get("content", [])
                for block in content_blocks:
                    if block.get("type") == "text":
                        final_content = block.get("text", "")
                        break
                break
            elif resp.get("method") == "error":
                raise RuntimeError(f"ACP error: {resp.get('error')}")
        
        return ACPResponse(
            content=final_content,
            stop_reason=stop_reason,
            session_id=self._session_id,
        )
    
    async def close(self) -> None:
        """Close the ACP connection and terminate the subprocess."""
        self._connected = False
        
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None
        
        if self._process:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self._process.kill()
            except Exception:
                pass
            self._process = None
        
        self._reader = None
        _logger.info("ACP client disconnected")


# Global client instance for reuse
_global_client: Optional[ACPClient] = None


async def get_acp_client() -> ACPClient:
    """Get or create the global ACP client instance."""
    global _global_client
    if _global_client is None:
        _global_client = ACPClient()
    return _global_client


async def close_acp_client() -> None:
    """Close the global ACP client instance."""
    global _global_client
    if _global_client is not None:
        await _global_client.close()
        _global_client = None
