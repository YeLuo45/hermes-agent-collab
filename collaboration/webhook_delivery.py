"""Webhook delivery task with HMAC signing and retry logic — Direction T."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Module-level config (set by init_webhook_delivery)
_config: dict[str, Any] = {
    "max_retries": 3,
    "timeout": 10.0,
    "delivery_limit": 50,
}


def init_webhook_delivery(max_retries: int = 3, timeout: float = 10.0, delivery_limit: int = 50) -> None:
    global _config
    _config["max_retries"] = max_retries
    _config["timeout"] = timeout
    _config["delivery_limit"] = delivery_limit


def _generate_signature(secret: str, timestamp: str, payload: str) -> str:
    """Generate HMAC-SHA256 signature for a webhook payload."""
    message = f"{timestamp}.{payload}"
    signature = hmac.new(
        secret.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"sha256={signature}"


class WebhookDeliveryTask:
    """
    Handles delivery of a single webhook event to a subscription URL.
    Includes HMAC-SHA256 signing and exponential-backoff retry.
    """

    def __init__(
        self,
        subscription: Any,  # WebhookSubscription
        event_type: str,
        payload: dict,
    ):
        self._sub = subscription
        self._event_type = event_type
        self._payload = payload
        self._delivery_id = str(uuid.uuid4())
        self._max_retries = _config["max_retries"]
        self._timeout = _config["timeout"]

    async def deliver_with_retry(self) -> dict:
        """
        Attempt delivery with exponential-backoff retry.
        Returns dict with keys: status, http_status, response_body, error, attempts
        """
        payload_str = json.dumps(self._payload, default=str, indent=None)
        attempts = 0
        last_error = None
        last_status = None
        last_response_body = None

        for attempt in range(1, self._max_retries + 1):
            attempts = attempt
            try:
                result = await self._deliver_once(payload_str)
                last_status = result.get("http_status")
                last_response_body = result.get("response_body")

                if 200 <= last_status < 300:
                    return {
                        "status": "success",
                        "http_status": last_status,
                        "response_body": last_response_body,
                        "attempts": attempts,
                    }

                last_error = f"HTTP {last_status}"

                # Don't retry 4xx client errors (except 429)
                if 400 <= last_status < 500 and last_status != 429:
                    break

            except asyncio.TimeoutError:
                last_error = "Timeout"
            except Exception as exc:
                last_error = str(exc)

            # Exponential backoff before retry
            if attempt < self._max_retries:
                delay = self._sub.retry_delay * (2 ** (attempt - 1))
                delay = min(delay, 60.0)  # cap at 60s
                logger.debug(
                    "Webhook %s delivery attempt %d/%d failed: %s. Retrying in %.1fs",
                    self._sub.id, attempt, self._max_retries, last_error, delay
                )
                await asyncio.sleep(delay)

        return {
            "status": "failed",
            "http_status": last_status,
            "response_body": last_response_body,
            "error": last_error,
            "attempts": attempts,
        }

    async def _deliver_once(self, payload_str: str) -> dict:
        """Perform a single HTTP POST delivery."""
        timestamp = str(int(time.time()))

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "hermes-collab-webhook/1.0",
            "X-Webhook-Event": self._event_type,
            "X-Webhook-Delivery-ID": self._delivery_id,
            "X-Webhook-Timestamp": timestamp,
            "X-Webhook-Signature": _generate_signature(
                self._sub.secret, timestamp, payload_str
            ),
        }

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                self._sub.url,
                content=payload_str,
                headers=headers,
            )
            response_body = response.text[:1000]  # truncate

            return {
                "http_status": response.status_code,
                "response_body": response_body,
            }


async def test_webhook(sub: Any, test_payload: dict | None = None) -> dict:
    """
    Send a test webhook to a subscription URL.
    Returns the same result dict as deliver_with_retry.
    """
    payload = test_payload or {
        "test": True,
        "event": "webhook.test",
        "message": "This is a test webhook delivery from hermes-agent-collab",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    task = WebhookDeliveryTask(
        subscription=sub,
        event_type="webhook.test",
        payload=payload,
    )
    return await task.deliver_with_retry()
