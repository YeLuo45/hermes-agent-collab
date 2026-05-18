"""
Async notification pipeline — Slack, Email, Webhook, Console channels.
"""

from __future__ import annotations

import asyncio
import json
import logging
import smtplib
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

import aiohttp

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Event
# ---------------------------------------------------------------------------

@dataclass
class NotificationEvent:
    """Standard notification event format."""
    type: str                           # e.g. "task.completed", "alert.error"
    title: str                          # Short summary
    body: str                           # Detailed message
    severity: str = "info"             # "info" | "warning" | "error" | "critical"
    source: str = "hermes-agent-collab"
    workspace_id: str | None = None
    metadata: dict = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Channel Interface
# ---------------------------------------------------------------------------

class NotificationChannel(ABC):
    """Abstract base class for notification channels."""

    name: str = "base"

    @abstractmethod
    async def send(self, event: NotificationEvent) -> bool:
        """Send notification. Returns True if sent successfully."""

    def supports_severity(self, severity: str) -> bool:
        """Check if this channel supports the given severity level. Override if needed."""
        return True

    async def close(self):
        """Cleanup resources. Override if the channel has open connections."""
        pass


# ---------------------------------------------------------------------------
# Console Channel
# ---------------------------------------------------------------------------

class ConsoleChannel(NotificationChannel):
    """Prints notifications to stdout. Useful for development."""

    name = "console"

    def __init__(self, severity_filter: list[str] | None = None):
        self._severity_filter = severity_filter or ["info", "warning", "error", "critical"]

    def supports_severity(self, severity: str) -> bool:
        return severity in self._severity_filter

    async def send(self, event: NotificationEvent) -> bool:
        if not self.supports_severity(event.severity):
            return True  # Silently skip
        timestamp = event.created_at
        severity = event.severity.upper()
        print(f"[{timestamp}] [{severity}] {event.title}")
        print(f"  Type: {event.type}")
        print(f"  Body: {event.body}")
        if event.workspace_id:
            print(f"  Workspace: {event.workspace_id}")
        if event.metadata:
            print(f"  Metadata: {json.dumps(event.metadata, indent=2)}")
        print()
        return True


# ---------------------------------------------------------------------------
# Slack Channel
# ---------------------------------------------------------------------------

class SlackChannel(NotificationChannel):
    """Sends notifications to Slack via Incoming Webhook."""

    name = "slack"

    def __init__(
        self,
        webhook_url: str,
        default_channel: str = "#general",
        severity_filter: list[str] | None = None,
        timeout: float = 10.0,
    ):
        self._webhook_url = webhook_url
        self._default_channel = default_channel
        self._severity_filter = severity_filter or ["warning", "error", "critical"]
        self._timeout = timeout
        self._session: aiohttp.ClientSession | None = None

    def supports_severity(self, severity: str) -> bool:
        return severity in self._severity_filter

    def _severity_emoji(self, severity: str) -> str:
        return {
            "info": ":information_source:",
            "warning": ":warning:",
            "error": ":x:",
            "critical": ":rotating_light:",
        }.get(severity, ":bell:")

    def _build_blocks(self, event: NotificationEvent) -> list[dict]:
        emoji = self._severity_emoji(event.severity)
        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"{emoji} {event.title}", "emoji": True},
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*{event.body}*"},
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": (
                            f"`{event.type}` | "
                            f"Source: `{event.source}` | "
                            f"Time: `{event.created_at}`"
                        ),
                    }
                ],
            },
        ]

        if event.workspace_id:
            blocks.append({
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f"Workspace: `{event.workspace_id}`"}],
            })

        if event.metadata:
            meta_text = " | ".join(f"`{k}`: {v}" for k, v in event.metadata.items())
            blocks.append({
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": meta_text}],
            })

        return blocks

    async def send(self, event: NotificationEvent) -> bool:
        if not self.supports_severity(event.severity):
            return True

        if not self._webhook_url or self._webhook_url.startswith("${"):
            _log.debug("Slack webhook URL not configured, skipping")
            return False

        if self._session is None:
            self._session = aiohttp.ClientSession()

        payload = {
            "channel": self._default_channel,
            "blocks": self._build_blocks(event),
            "text": f"[{event.severity.upper()}] {event.title}: {event.body}",
        }

        try:
            async with self._session.post(
                self._webhook_url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=self._timeout),
            ) as resp:
                if resp.status == 200:
                    _log.debug("Slack notification sent: %s", event.id)
                    return True
                body = await resp.text()
                _log.warning("Slack webhook error %d: %s", resp.status, body[:200])
                return False
        except asyncio.TimeoutError:
            _log.warning("Slack webhook timeout for event %s", event.id)
            return False
        except Exception as e:
            _log.error("Slack webhook exception for event %s: %s", event.id, e)
            return False

    async def close(self):
        if self._session:
            await self._session.close()
            self._session = None


# ---------------------------------------------------------------------------
# Email Channel
# ---------------------------------------------------------------------------

class EmailChannel(NotificationChannel):
    """Sends notifications via SMTP email."""

    name = "email"

    def __init__(
        self,
        smtp_host: str,
        smtp_port: int = 587,
        smtp_user: str = "",
        smtp_password: str = "",
        from_address: str = "hermes@noreply.com",
        to_addresses: list[str] | None = None,
        severity_filter: list[str] | None = None,
        use_tls: bool = True,
    ):
        self._smtp_host = smtp_host
        self._smtp_port = smtp_port
        self._smtp_user = smtp_user
        self._smtp_password = smtp_password
        self._from_address = from_address
        self._to_addresses = to_addresses or []
        self._severity_filter = severity_filter or ["error", "critical"]
        self._use_tls = use_tls

    def supports_severity(self, severity: str) -> bool:
        return severity in self._severity_filter

    def _build_html_body(self, event: NotificationEvent) -> str:
        meta_rows = ""
        if event.metadata:
            meta_rows = "\n".join(
                f"<tr><td><code>{k}</code></td><td>{v}</td></tr>"
                for k, v in event.metadata.items()
            )

        return f"""<!DOCTYPE html>
<html>
<head><style>
body {{ font-family: Arial, sans-serif; margin: 20px; }}
.header {{ padding: 10px; background: #f5f5f5; border-left: 4px solid; margin-bottom: 20px; }}
.info {{ border-color: #2196F3; }} .warning {{ border-color: #ff9800; }}
.error {{ border-color: #f44336; }} .critical {{ border-color: #b71c1c; }}
.severity {{ text-transform: uppercase; font-size: 12px; font-weight: bold; }}
h2 {{ margin: 0 0 10px; }} .meta-table {{ border-collapse: collapse; }}
.meta-table td {{ padding: 4px 12px; border-bottom: 1px solid #eee; }}
</style></head>
<body>
<div class="header {event.severity}">
  <span class="severity">[{event.severity.upper()}]</span>
  <h2>{event.title}</h2>
</div>
<p><strong>Type:</strong> {event.type}</p>
<p>{event.body}</p>
<p><strong>Time:</strong> {event.created_at}</p>
<p><strong>Source:</strong> {event.source}</p>
{"".join(f"<p><strong>Workspace:</strong> {event.workspace_id}</p>" if event.workspace_id else "")}
<table class="meta-table">
{meta_rows}
</table>
</body>
</html>"""

    async def send(self, event: NotificationEvent) -> bool:
        if not self.supports_severity(event.severity):
            return True

        if not self._smtp_host or self._smtp_host.startswith("${"):
            _log.debug("SMTP host not configured, skipping email")
            return False

        if not self._to_addresses:
            _log.warning("No recipient email addresses configured")
            return False

        try:
            # Run sync SMTP in thread pool to avoid blocking
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._send_sync, event)
            _log.debug("Email notification sent: %s", event.id)
            return True
        except Exception as e:
            _log.error("Email send error for event %s: %s", event.id, e)
            return False

    def _send_sync(self, event: NotificationEvent):
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"[{event.severity.upper()}] {event.title}"
        msg["From"] = self._from_address
        msg["To"] = ", ".join(self._to_addresses)

        plain = f"{event.title}\n\n{event.body}\n\nType: {event.type}\nTime: {event.created_at}\nSource: {event.source}"
        html = self._build_html_body(event)

        msg.attach(MIMEText(plain, "plain"))
        msg.attach(MIMEText(html, "html"))

        with smtplib.SMTP(self._smtp_host, self._smtp_port) as server:
            if self._use_tls:
                server.starttls()
            if self._smtp_user and self._smtp_password:
                server.login(self._smtp_user, self._smtp_password)
            server.sendmail(self._from_address, self._to_addresses, msg.as_string())


# ---------------------------------------------------------------------------
# Webhook Channel
# ---------------------------------------------------------------------------

class WebhookChannel(NotificationChannel):
    """Sends notifications to a generic HTTP endpoint."""

    name = "webhook"

    def __init__(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        severity_filter: list[str] | None = None,
        timeout: float = 10.0,
    ):
        self._url = url
        self._headers = headers or {}
        self._severity_filter = severity_filter or ["info", "warning", "error", "critical"]
        self._timeout = timeout
        self._session: aiohttp.ClientSession | None = None

    def supports_severity(self, severity: str) -> bool:
        return severity in self._severity_filter

    async def send(self, event: NotificationEvent) -> bool:
        if not self.supports_severity(event.severity):
            return True

        if not self._url or self._url.startswith("${"):
            _log.debug("Webhook URL not configured, skipping")
            return False

        if self._session is None:
            self._session = aiohttp.ClientSession()

        try:
            async with self._session.post(
                self._url,
                json=event.to_dict(),
                headers={"Content-Type": "application/json", **self._headers},
                timeout=aiohttp.ClientTimeout(total=self._timeout),
            ) as resp:
                success = resp.status < 400
                if not success:
                    body = await resp.text()
                    _log.warning("Webhook error %d: %s", resp.status, body[:200])
                return success
        except asyncio.TimeoutError:
            _log.warning("Webhook timeout for event %s", event.id)
            return False
        except Exception as e:
            _log.error("Webhook exception for event %s: %s", event.id, e)
            return False

    async def close(self):
        if self._session:
            await self._session.close()
            self._session = None


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class NotificationManager:
    """
    Manages notification channels and routes events to appropriate channels.
    Supports Slack, Email, Webhook, and Console channels.
    """

    def __init__(self):
        self._channels: dict[str, NotificationChannel] = {}
        self._lock = asyncio.Lock()

    async def register_channel(self, name: str, channel: NotificationChannel) -> None:
        """Register a notification channel."""
        async with self._lock:
            self._channels[name] = channel
        _log.info("Notification channel registered: %s", name)

    async def unregister_channel(self, name: str) -> bool:
        """Unregister and close a notification channel."""
        async with self._lock:
            channel = self._channels.pop(name, None)
        if channel:
            await channel.close()
            _log.info("Notification channel unregistered: %s", name)
            return True
        return False

    async def send(self, event: NotificationEvent) -> dict[str, bool]:
        """
        Send notification to all registered channels.
        Returns dict mapping channel name -> success (True/False).
        """
        async with self._lock:
            channels = list(self._channels.items())

        results = {}
        for name, channel in channels:
            try:
                results[name] = await channel.send(event)
            except Exception as e:
                _log.error("Channel %s error for event %s: %s", name, event.id, e)
                results[name] = False

        return results

    async def send_to_channel(self, channel_name: str, event: NotificationEvent) -> bool:
        """Send notification to a specific channel by name."""
        async with self._lock:
            channel = self._channels.get(channel_name)

        if channel is None:
            _log.warning("Channel not found: %s", channel_name)
            return False

        try:
            return await channel.send(event)
        except Exception as e:
            _log.error("Channel %s error for event %s: %s", channel_name, event.id, e)
            return False

    def list_channels(self) -> list[dict[str, Any]]:
        """List all registered channels with their types."""
        return [
            {
                "name": name,
                "type": channel.name,
                "supports_severity": channel.supports_severity.__func__(channel, "info"),
            }
            for name, channel in self._channels.items()
        ]

    async def close_all(self):
        """Close all channels."""
        async with self._lock:
            channels = list(self._channels.values())
            self._channels.clear()

        for channel in channels:
            await channel.close()


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def make_channel(config: dict[str, Any]) -> NotificationChannel:
    """
    Create a NotificationChannel from a config dict.

    Config format:
        {"type": "slack", "webhook_url": "...", ...}
        {"type": "email", "smtp_host": "...", ...}
        {"type": "webhook", "url": "...", ...}
        {"type": "console", "severity_filter": ["info", "error"]}
    """
    ctype = config.get("type", "console")

    if ctype == "slack":
        return SlackChannel(
            webhook_url=config.get("webhook_url", ""),
            default_channel=config.get("default_channel", "#general"),
            severity_filter=config.get("severity_filter"),
        )
    elif ctype == "email":
        return EmailChannel(
            smtp_host=config.get("smtp_host", ""),
            smtp_port=config.get("smtp_port", 587),
            smtp_user=config.get("smtp_user", ""),
            smtp_password=config.get("smtp_password", ""),
            from_address=config.get("from_address", "hermes@noreply.com"),
            to_addresses=config.get("to_addresses", []),
            severity_filter=config.get("severity_filter"),
        )
    elif ctype == "webhook":
        return WebhookChannel(
            url=config.get("url", ""),
            headers=config.get("headers", {}),
            severity_filter=config.get("severity_filter"),
        )
    elif ctype == "console":
        return ConsoleChannel(severity_filter=config.get("severity_filter"))
    else:
        raise ValueError(f"Unknown notification channel type: {ctype}")
