"""Exceptions for hermes-agent-collab SDK."""


class HermesCollabError(Exception):
    """Base exception for all hermes-agent-collab errors."""
    pass


class AuthError(HermesCollabError):
    """Authentication or authorization failure."""
    pass


class NotFoundError(HermesCollabError):
    """Resource not found (404)."""
    pass


class ValidationError(HermesCollabError):
    """Request validation failed (422)."""
    pass


class NetworkError(HermesCollabError):
    """Network connectivity issue."""
    pass


class WebSocketError(HermesCollabError):
    """WebSocket connection or protocol error."""
    pass
