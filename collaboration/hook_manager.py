"""
Hook Manager — re-exports HookEvent and ChannelAdapter from their canonical modules.

Canonical locations:
- HookEvent: collaboration.models.HookEvent
- ChannelAdapter: collaboration.events.ChannelAdapter
"""

from .events import ChannelAdapter
from .models import HookEvent, HookEventType

__all__ = ["ChannelAdapter", "HookEvent", "HookEventType"]
