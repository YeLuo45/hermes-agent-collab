"""Webhook subscription manager — Direction T."""

from __future__ import annotations

import asyncio
import fnmatch
import hashlib
import hmac
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


class WebhookSubscription:
    """A single webhook subscription."""

    def __init__(
        self,
        webhook_id: str,
        url: str,
        events: list[str],
        secret: str,
        workspace_id: str | None = None,
        enabled: bool = True,
        retry_count: int = 3,
        retry_delay: float = 1.0,
        active: bool = True,
        created_at: str | None = None,
        last_triggered_at: str | None = None,
        last_success_at: str | None = None,
        last_failure_at: str | None = None,
        last_error: str | None = None,
    ):
        self.id = webhook_id
        self.url = url
        self.events = events
        self.secret = secret
        self.workspace_id = workspace_id
        self.enabled = enabled
        self.retry_count = retry_count
        self.retry_delay = retry_delay
        self.active = active
        self.created_at = created_at or datetime.now(timezone.utc).isoformat()
        self.last_triggered_at = last_triggered_at
        self.last_success_at = last_success_at
        self.last_failure_at = last_failure_at
        self.last_error = last_error

    def matches_event(self, event_type: str, workspace_id: str | None) -> bool:
        """Check if this subscription matches the given event."""
        if not self.enabled:
            return False
        if self.workspace_id is not None and self.workspace_id != workspace_id:
            return False
        for pattern in self.events:
            if pattern == "*" or pattern == event_type:
                return True
            if "*" in pattern and fnmatch.fnmatch(event_type, pattern):
                return True
        return False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "url": self.url,
            "events": self.events,
            "secret": self.secret,
            "workspace_id": self.workspace_id,
            "enabled": self.enabled,
            "retry_count": self.retry_count,
            "retry_delay": self.retry_delay,
            "active": self.active,
            "created_at": self.created_at,
            "last_triggered_at": self.last_triggered_at,
            "last_success_at": self.last_success_at,
            "last_failure_at": self.last_failure_at,
            "last_error": self.last_error,
        }

    @classmethod
    def from_dict(cls, d: dict) -> WebhookSubscription:
        return cls(
            webhook_id=d["id"],
            url=d["url"],
            events=d["events"],
            secret=d["secret"],
            workspace_id=d.get("workspace_id"),
            enabled=d.get("enabled", True),
            retry_count=d.get("retry_count", 3),
            retry_delay=d.get("retry_delay", 1.0),
            active=d.get("active", True),
            created_at=d.get("created_at"),
            last_triggered_at=d.get("last_triggered_at"),
            last_success_at=d.get("last_success_at"),
            last_failure_at=d.get("last_failure_at"),
            last_error=d.get("last_error"),
        )


class WebhookDelivery:
    """Record of a single webhook delivery attempt."""

    def __init__(
        self,
        delivery_id: str,
        webhook_id: str,
        event_type: str,
        payload: dict,
        status: str = "pending",
        http_status: int | None = None,
        response_body: str | None = None,
        error: str | None = None,
        attempts: int = 0,
        created_at: str | None = None,
        delivered_at: str | None = None,
    ):
        self.id = delivery_id
        self.webhook_id = webhook_id
        self.event_type = event_type
        self.payload = payload
        self.status = status
        self.http_status = http_status
        self.response_body = response_body
        self.error = error
        self.attempts = attempts
        self.created_at = created_at or datetime.now(timezone.utc).isoformat()
        self.delivered_at = delivered_at

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "webhook_id": self.webhook_id,
            "event_type": self.event_type,
            "payload": self.payload,
            "status": self.status,
            "http_status": self.http_status,
            "response_body": self.response_body,
            "error": self.error,
            "attempts": self.attempts,
            "created_at": self.created_at,
            "delivered_at": self.delivered_at,
        }


class WebhookManager:
    """
    Manages webhook subscriptions and delivery.
    Stores subscriptions in JsonFileStore, deliveries in memory (TTL 7 days).
    """

    MAX_CONSECUTIVE_FAILURES = 10

    def __init__(self, storage_path: str | None = None):
        import uuid as _uuid
        self._subs: dict[str, WebhookSubscription] = {}
        self._deliveries: dict[str, list[WebhookDelivery]] = {}  # webhook_id → deliveries
        self._storage_path = storage_path
        self._lock = asyncio.Lock()
        self._load()

    # ---- Subscription CRUD ----

    async def subscribe(
        self,
        url: str,
        events: list[str],
        secret: str | None = None,
        workspace_id: str | None = None,
        retry_count: int = 3,
        retry_delay: float = 1.0,
    ) -> WebhookSubscription:
        """Create a new webhook subscription."""
        async with self._lock:
            webhook_id = str(uuid.uuid4())
            secret = secret or uuid.uuid4().hex[:32]
            sub = WebhookSubscription(
                webhook_id=webhook_id,
                url=url,
                events=events,
                secret=secret,
                workspace_id=workspace_id,
                retry_count=retry_count,
                retry_delay=retry_delay,
            )
            self._subs[webhook_id] = sub
            self._deliveries[webhook_id] = []
            self._save()
            logger.info("Created webhook subscription: %s -> %s", webhook_id, url)
            return sub

    async def unsubscribe(self, webhook_id: str) -> bool:
        """Delete a subscription. Returns True if found."""
        async with self._lock:
            if webhook_id in self._subs:
                del self._subs[webhook_id]
                self._deliveries.pop(webhook_id, None)
                self._save()
                return True
            return False

    async def get_subscription(self, webhook_id: str) -> WebhookSubscription | None:
        return self._subs.get(webhook_id)

    async def list_subscriptions(
        self,
        workspace_id: str | None = None,
        event_type: str | None = None,
    ) -> list[WebhookSubscription]:
        """List subscriptions, optionally filtered."""
        subs = list(self._subs.values())
        if workspace_id is not None:
            subs = [s for s in subs if s.workspace_id == workspace_id or s.workspace_id is None]
        if event_type is not None:
            subs = [s for s in subs if s.matches_event(event_type, workspace_id)]
        return subs

    async def update_subscription(
        self,
        webhook_id: str,
        url: str | None = None,
        events: list[str] | None = None,
        enabled: bool | None = None,
    ) -> WebhookSubscription | None:
        """Update an existing subscription."""
        async with self._lock:
            sub = self._subs.get(webhook_id)
            if sub is None:
                return None
            if url is not None:
                sub.url = url
            if events is not None:
                sub.events = events
            if enabled is not None:
                sub.enabled = enabled
            self._save()
            return sub

    # ---- Trigger / Delivery ----

    async def trigger(self, event_type: str, payload: dict, workspace_id: str | None = None) -> list[dict]:
        """
        Trigger all matching subscriptions for an event.
        Returns a list of delivery results.
        """
        from collaboration.webhook_delivery import WebhookDeliveryTask

        matching = [
            sub for sub in self._subs.values()
            if sub.matches_event(event_type, workspace_id)
        ]

        if not matching:
            return []

        results = []
        for sub in matching:
            task = WebhookDeliveryTask(
                subscription=sub,
                event_type=event_type,
                payload=payload,
            )
            result = await task.deliver_with_retry()
            results.append({
                "webhook_id": sub.id,
                "url": sub.url,
                "status": result["status"],
                "http_status": result.get("http_status"),
                "error": result.get("error"),
            })

            # Update subscription stats
            sub.last_triggered_at = datetime.now(timezone.utc).isoformat()
            if result["status"] == "success":
                sub.last_success_at = datetime.now(timezone.utc).isoformat()
                sub.last_error = None
            else:
                sub.last_failure_at = datetime.now(timezone.utc).isoformat()
                sub.last_error = result.get("error")

            # Record delivery
            delivery = WebhookDelivery(
                delivery_id=str(uuid.uuid4()),
                webhook_id=sub.id,
                event_type=event_type,
                payload=payload,
                status=result["status"],
                http_status=result.get("http_status"),
                response_body=result.get("response_body"),
                error=result.get("error"),
                attempts=result.get("attempts", 1),
                delivered_at=datetime.now(timezone.utc).isoformat(),
            )
            self._deliveries.setdefault(sub.id, []).insert(0, delivery)
            # Keep only last 100 deliveries per webhook
            if len(self._deliveries[sub.id]) > 100:
                self._deliveries[sub.id] = self._deliveries[sub.id][:100]

            # Disable after MAX_CONSECUTIVE_FAILURES
            if result["status"] != "success":
                failure_count = sum(
                    1 for d in self._deliveries.get(sub.id, [])[:self.MAX_CONSECUTIVE_FAILURES]
                    if d.status != "success"
                )
                if failure_count >= self.MAX_CONSECUTIVE_FAILURES:
                    sub.active = False
                    logger.warning("Webhook %s disabled after %d consecutive failures", sub.id, failure_count)

            self._save()

        return results

    async def get_deliveries(self, webhook_id: str, limit: int = 50) -> list[WebhookDelivery]:
        """Get delivery history for a webhook."""
        return self._deliveries.get(webhook_id, [])[:limit]

    # ---- Persistence ----

    def _load(self) -> None:
        if self._storage_path is None:
            return
        try:
            with open(self._storage_path, "r") as f:
                data = json.load(f)
            subs_data = data.get("subscriptions", {})
            self._subs = {
                k: WebhookSubscription.from_dict(v)
                for k, v in subs_data.items()
            }
            logger.info("Loaded %d webhook subscriptions", len(self._subs))
        except FileNotFoundError:
            pass
        except Exception as exc:
            logger.warning("Failed to load webhook subscriptions: %s", exc)

    def _save(self) -> None:
        if self._storage_path is None:
            return
        try:
            data = {"subscriptions": {k: v.to_dict() for k, v in self._subs.items()}}
            with open(self._storage_path, "w") as f:
                json.dump(data, f, indent=2, default=str)
        except Exception as exc:
            logger.warning("Failed to save webhook subscriptions: %s", exc)


# Singleton
_manager: WebhookManager | None = None


def get_webhook_manager() -> WebhookManager:
    global _manager
    if _manager is None:
        _manager = WebhookManager()
    return _manager


def init_webhook_manager(storage_path: str | None = None) -> WebhookManager:
    global _manager
    _manager = WebhookManager(storage_path=storage_path)
    return _manager
