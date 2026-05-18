"""
Operational Transformation engine for collaborative editing.
Provides OT for concurrent operations on the same resource.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

_log = __import__("logging").getLogger(__name__)


# ---------------------------------------------------------------------------
# Operation types
# ---------------------------------------------------------------------------

OP_INSERT = "insert"
OP_DELETE = "delete"
OP_REPLACE = "replace"


def _path_compare(p1: str, p2: str) -> int:
    """
    Compare two JSON paths.
    Returns -1 if p1 < p2, 0 if equal, 1 if p1 > p2.
    Path format: "tasks/0/subtasks/1" or "$.tasks[0].subtasks[1]"
    """
    # Normalize
    n1 = p1.replace("$.", "").replace("[", "/").replace("]", "").split("/")
    n2 = p2.replace("$.", "").replace("[", "/").replace("]", "").split("/")

    for p1_part, p2_part in zip(n1, n2):
        # Try numeric comparison
        try:
            i1, i2 = int(p1_part), int(p2_part)
            if i1 < i2:
                return -1
            elif i1 > i2:
                return 1
        except ValueError:
            # String comparison
            if p1_part < p2_part:
                return -1
            elif p1_part > p2_part:
                return 1
    # Longer path comes after
    if len(n1) < len(n2):
        return -1
    elif len(n1) > len(n2):
        return 1
    return 0


def transform_insert_vs_insert(op1: dict, op2: dict) -> tuple[dict, dict]:
    """Transform insert vs insert."""
    path1, path2 = op1.get("path", ""), op2.get("path", "")
    idx1 = path1.rsplit("/", 1)[-1]
    idx2 = path2.rsplit("/", 1)[-1]

    try:
        i1, i2 = int(idx1), int(idx2)
        if i1 >= i2:
            # op1 inserts at or after op2's position → shift op1
            op1["path"] = path1.rsplit("/", 1)[0] + "/" + str(i1 + 1)
    except ValueError:
        pass

    return op1, op2


def transform_insert_vs_delete(op1: dict, op2: dict) -> tuple[dict, dict]:
    """Transform insert vs delete."""
    # Insert doesn't need transformation against delete
    # (delete removes already-deleted content doesn't affect insert position)
    return op1, op2


def transform_delete_vs_insert(op1: dict, op2: dict) -> tuple[dict, dict]:
    """Transform delete vs insert (op1=delete, op2=insert)."""
    # No-op: delete doesn't care about concurrent inserts
    return op1, op2


def transform_delete_vs_delete(op1: dict, op2: dict) -> tuple[dict, dict]:
    """Transform delete vs delete."""
    # If both delete same path, eliminate op1
    if op1.get("path") == op2.get("path"):
        op1["_eliminated"] = True
    return op1, op2


def transform_replace_vs_any(op1: dict, op2: dict) -> tuple[dict, dict]:
    """Transform replace vs any op — replace wins (last-write-wins)."""
    # No transformation needed — replace is idempotent
    return op1, op2


def transform_any_vs_replace(op1: dict, op2: dict) -> tuple[dict, dict]:
    """Transform any op vs replace."""
    # If same path, op1 is superseded by op2's replace
    if op1.get("path") == op2.get("path"):
        op1["_superseded"] = True
    return op1, op2


def transform(op1: dict, op2: dict) -> tuple[dict, dict]:
    """
    Transform op1 against op2 so they can be applied in any order.
    Returns (transformed_op1, transformed_op2).
    """
    t1, t2 = op1.copy(), op2.copy()
    t1.pop("_eliminated", None)
    t1.pop("_superseded", None)
    t2.pop("_eliminated", None)
    t2.pop("_superseded", None)

    op_type_1 = t1.get("op_type", "replace")
    op_type_2 = t2.get("op_type", "replace")

    # Same path — replace wins, insert/delete eliminated
    if t1.get("path") == t2.get("path"):
        if op_type_1 == "replace":
            t2["_superseded"] = True
        elif op_type_2 == "replace":
            t1["_superseded"] = True
        return t1, t2

    # Pairwise OT based on op types
    if op_type_1 == OP_INSERT and op_type_2 == OP_INSERT:
        t1, t2 = transform_insert_vs_insert(t1, t2)
    elif op_type_1 == OP_INSERT and op_type_2 == OP_DELETE:
        t1, t2 = transform_insert_vs_delete(t1, t2)
    elif op_type_1 == OP_DELETE and op_type_2 == OP_INSERT:
        t1, t2 = transform_delete_vs_insert(t1, t2)
    elif op_type_1 == OP_DELETE and op_type_2 == OP_DELETE:
        t1, t2 = transform_delete_vs_delete(t1, t2)

    return t1, t2


# ---------------------------------------------------------------------------
# Operation log and history
# ---------------------------------------------------------------------------

@dataclass
class OperationRecord:
    op: dict
    transformed_by: list[dict] = field(default_factory=list)
    applied_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    server_version: int = 0


class OTEngine:
    """
    Operational Transformation engine.
    Maintains operation history and transforms incoming ops against concurrent ops.
    """

    def __init__(self, session_id: str):
        self._session_id = session_id
        self._history: list[OperationRecord] = []
        self._pending: dict[str, OperationRecord] = {}  # op_id → record
        self._lock = __import__("threading").Lock()

    def process(self, op: dict) -> dict:
        """
        Process an incoming operation.
        Returns the transformed operation ready to apply.
        """
        op_id = op.get("op_id", str(uuid.uuid4()))
        op = dict(op)
        op["op_id"] = op_id

        with self._lock:
            # Transform against all ops applied since client's version
            for record in self._history[-50:]:  # last 50
                if op.get("_eliminated") or op.get("_superseded"):
                    break
                old_op = record.op
                # Client version N → server has applied ops up to N+1
                # Transform incoming op against any server op that happened after client snapshot
                t_op, _ = transform(op, old_op)
                op = t_op

            # Check if eliminated
            if op.get("_eliminated"):
                _log.info("Op %s was eliminated by concurrent op", op_id)
                return {"_eliminated": True, "op_id": op_id}

            # Record
            rec = OperationRecord(
                op=op,
                applied_at=datetime.now(timezone.utc).isoformat(),
                server_version=len(self._history),
            )
            self._history.append(rec)

            return op

    def get_history_since(self, client_version: int) -> list[dict]:
        """Get ops since client version for sync."""
        return [rec.op for rec in self._history[client_version:]]

    def get_server_version(self) -> int:
        return len(self._history)

    def get_pending_count(self) -> int:
        return len(self._pending)


# ---------------------------------------------------------------------------
# Per-session OT engine registry
# ---------------------------------------------------------------------------

_engines: dict[str, OTEngine] = {}
_engines_lock = __import__("threading").Lock()


def get_ot_engine(session_id: str) -> OTEngine:
    with _engines_lock:
        if session_id not in _engines:
            _engines[session_id] = OTEngine(session_id)
        return _engines[session_id]


def clear_ot_engine(session_id: str) -> None:
    with _engines_lock:
        _engines.pop(session_id, None)
