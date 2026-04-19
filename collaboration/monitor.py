"""
Runtime Monitor for Hermes Agent Team Collaboration.
Provides unified monitoring, metrics, and health tracking.
"""

import asyncio
import json
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Callable, Awaitable

try:
    from .models import AgentStatus, TaskStatus
    from .storage import JsonFileStore
except ImportError:
    from collaboration.models import AgentStatus, TaskStatus
    from collaboration.storage import JsonFileStore


@dataclass
class MetricPoint:
    """A single metric data point."""
    timestamp: str
    value: float
    labels: dict = field(default_factory=dict)


@dataclass
class AgentMetrics:
    """Metrics for a single agent."""
    agent_id: str
    messages_sent: int = 0
    messages_received: int = 0
    tasks_completed: int = 0
    tasks_failed: int = 0
    uptime_seconds: float = 0
    last_activity: str = None
    cpu_usage: float = 0.0
    memory_usage: float = 0.0


@dataclass
class WorkspaceMetrics:
    """Metrics for a workspace."""
    workspace_id: str
    total_agents: int = 0
    active_agents: int = 0
    total_tasks: int = 0
    pending_tasks: int = 0
    in_progress_tasks: int = 0
    completed_tasks: int = 0
    blocked_tasks: int = 0
    completion_rate: float = 0.0
    avg_task_duration_seconds: float = 0.0


class RuntimeMonitor:
    """Unified runtime monitoring for collaboration system."""
    
    def __init__(
        self,
        base_path: str = "~/.hermes/collab",
        retention_hours: int = 24
    ):
        self.base_path = Path(base_path).expanduser()
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.retention_hours = retention_hours
        
        # Metric storage
        self._metrics: dict[str, list[MetricPoint]] = defaultdict(list)
        
        # Agent metrics cache
        self._agent_metrics: dict[str, AgentMetrics] = {}
        
        # Event history
        self._events: list[dict] = []
        
        # Alert handlers
        self._alert_handlers: list[Callable] = []
        
        # Health check interval (seconds)
        self._health_check_interval = 60
        
        # Monitor task
        self._monitor_task: Optional[asyncio.Task] = None
        
        # Store for persistence
        self.store = JSONFileStore(self.base_path / "monitor")
        
        # Load persisted metrics
        self._load_metrics()
    
    def _load_metrics(self):
        """Load metrics from disk."""
        try:
            events = self.store.list("events")
            self._events = events[-1000:]  # Keep last 1000 events
        except Exception:
            self._events = []
    
    def _save_events(self):
        """Persist events to disk."""
        try:
            # Clear and rewrite
            import os
            events_file = self.base_path / "monitor" / "events.json"
            if events_file.exists():
                os.remove(events_file)
            self.store._write_collection("events", {e["event_id"]: e for e in self._events})
        except Exception:
            pass
    
    def record_event(
        self,
        event_type: str,
        source_id: str,
        target_id: str = None,
        metadata: dict = None
    ):
        """Record a system event."""
        event = {
            "event_id": f"evt_{uuid.uuid4().hex[:12]}",
            "type": event_type,
            "source_id": source_id,
            "target_id": target_id,
            "metadata": metadata or {},
            "timestamp": datetime.utcnow().isoformat()
        }
        self._events.append(event)
        
        # Trim old events
        cutoff = datetime.utcnow() - timedelta(hours=self.retention_hours)
        self._events = [
            e for e in self._events
            if datetime.fromisoformat(e["timestamp"]) > cutoff
        ]
        
        # Persist periodically
        if len(self._events) % 100 == 0:
            self._save_events()
        
        return event["event_id"]
    
    def record_metric(
        self,
        metric_name: str,
        value: float,
        labels: dict = None
    ):
        """Record a metric value."""
        point = MetricPoint(
            timestamp=datetime.utcnow().isoformat(),
            value=value,
            labels=labels or {}
        )
        self._metrics[metric_name].append(point)
        
        # Trim old metrics
        cutoff = datetime.utcnow() - timedelta(hours=self.retention_hours)
        self._metrics[metric_name] = [
            p for p in self._metrics[metric_name]
            if datetime.fromisoformat(p.timestamp) > cutoff
        ]
    
    def get_metrics(
        self,
        metric_name: str,
        since: datetime = None,
        until: datetime = None
    ) -> list[MetricPoint]:
        """Get metric values in a time range."""
        points = self._metrics.get(metric_name, [])
        
        if since:
            points = [p for p in points if datetime.fromisoformat(p.timestamp) >= since]
        if until:
            points = [p for p in points if datetime.fromisoformat(p.timestamp) <= until]
        
        return points
    
    def get_agent_metrics(self, agent_id: str) -> AgentMetrics:
        """Get metrics for an agent."""
        if agent_id not in self._agent_metrics:
            self._agent_metrics[agent_id] = AgentMetrics(agent_id=agent_id)
        return self._agent_metrics[agent_id]
    
    def update_agent_metrics(
        self,
        agent_id: str,
        messages_sent: int = None,
        messages_received: int = None,
        tasks_completed: int = None,
        tasks_failed: int = None,
        cpu_usage: float = None,
        memory_usage: float = None
    ):
        """Update agent metrics."""
        metrics = self.get_agent_metrics(agent_id)
        
        if messages_sent is not None:
            metrics.messages_sent = messages_sent
        if messages_received is not None:
            metrics.messages_received = messages_received
        if tasks_completed is not None:
            metrics.tasks_completed = tasks_completed
        if tasks_failed is not None:
            metrics.tasks_failed = tasks_failed
        if cpu_usage is not None:
            metrics.cpu_usage = cpu_usage
        if memory_usage is not None:
            metrics.memory_usage = memory_usage
        
        metrics.last_activity = datetime.utcnow().isoformat()
        self._agent_metrics[agent_id] = metrics
        
        # Record as metric
        self.record_metric(
            "agent.tasks_completed",
            float(metrics.tasks_completed),
            {"agent_id": agent_id}
        )
    
    def get_workspace_metrics(
        self,
        workspace_id: str,
        task_manager = None
    ) -> WorkspaceMetrics:
        """Get metrics for a workspace."""
        metrics = WorkspaceMetrics(workspace_id=workspace_id)
        
        if task_manager:
            tasks = task_manager.list_tasks(workspace_id=workspace_id)
            metrics.total_tasks = len(tasks)
            metrics.pending_tasks = len([t for t in tasks if t.status == TaskStatus.PENDING])
            metrics.in_progress_tasks = len([t for t in tasks if t.status == TaskStatus.IN_PROGRESS])
            metrics.completed_tasks = len([t for t in tasks if t.status == TaskStatus.COMPLETED])
            metrics.blocked_tasks = len([t for t in tasks if t.status == TaskStatus.BLOCKED])
            
            if metrics.total_tasks > 0:
                metrics.completion_rate = metrics.completed_tasks / metrics.total_tasks
            
            # Calculate average task duration
            completed_with_duration = [
                t for t in tasks
                if t.status == TaskStatus.COMPLETED and t.started_at and t.completed_at
            ]
            if completed_with_duration:
                total_duration = sum(
                    (
                        datetime.fromisoformat(t.completed_at) -
                        datetime.fromisoformat(t.started_at)
                    ).total_seconds()
                    for t in completed_with_duration
                )
                metrics.avg_task_duration_seconds = total_duration / len(completed_with_duration)
        
        return metrics
    
    def get_events(
        self,
        event_type: str = None,
        source_id: str = None,
        since: datetime = None,
        limit: int = 100
    ) -> list[dict]:
        """Get events with optional filtering."""
        events = self._events
        
        if event_type:
            events = [e for e in events if e["type"] == event_type]
        if source_id:
            events = [e for e in events if e["source_id"] == source_id]
        if since:
            events = [
                e for e in events
                if datetime.fromisoformat(e["timestamp"]) >= since
            ]
        
        return events[-limit:]
    
    def get_system_health(self) -> dict:
        """Get overall system health status."""
        now = datetime.utcnow()
        recent_events = [
            e for e in self._events
            if datetime.fromisoformat(e["timestamp"]) > now - timedelta(minutes=5)
        ]
        
        # Count error events
        error_count = len([e for e in recent_events if e["type"] == "error"])
        
        # Determine health status
        if error_count > 10:
            health = "critical"
        elif error_count > 5:
            health = "degraded"
        elif error_count > 0:
            health = "warning"
        else:
            health = "healthy"
        
        return {
            "status": health,
            "timestamp": now.isoformat(),
            "connected_agents": len(self._agent_metrics),
            "events_last_5min": len(recent_events),
            "error_count_last_5min": error_count,
            "total_events": len(self._events)
        }
    
    def get_agent_status_summary(self) -> dict:
        """Get summary of agent statuses."""
        summary = {
            "total": len(self._agent_metrics),
            "online": 0,
            "offline": 0,
            "busy": 0,
            "away": 0,
            "error": 0
        }
        
        for metrics in self._agent_metrics.values():
            status = metrics.last_activity  # Simplified
            if metrics.last_activity:
                last_active = datetime.fromisoformat(metrics.last_activity)
                if now - last_active > timedelta(minutes=5):
                    summary["away"] += 1
                else:
                    summary["online"] += 1
            else:
                summary["offline"] += 1
        
        return summary
    
    def add_alert_handler(self, handler: Callable[[dict], Awaitable[None]]):
        """Add an alert handler."""
        self._alert_handlers.append(handler)
    
    async def trigger_alert(self, alert_type: str, message: str, severity: str = "info"):
        """Trigger an alert."""
        alert = {
            "alert_id": f"alert_{uuid.uuid4().hex[:12]}",
            "type": alert_type,
            "message": message,
            "severity": severity,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        for handler in self._alert_handlers:
            try:
                await handler(alert)
            except Exception:
                pass
        
        self.record_event(
            event_type=f"alert_{alert_type}",
            source_id="monitor",
            metadata=alert
        )
    
    async def start_monitoring(self):
        """Start background monitoring task."""
        if self._monitor_task:
            return
        
        self._monitor_task = asyncio.create_task(self._monitor_loop())
    
    async def stop_monitoring(self):
        """Stop background monitoring task."""
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            self._monitor_task = None
    
    async def _monitor_loop(self):
        """Background monitoring loop."""
        while True:
            try:
                await asyncio.sleep(self._health_check_interval)
                
                # Record system metrics
                health = self.get_system_health()
                self.record_metric(
                    "system.health.score",
                    1.0 if health["status"] == "healthy" else 0.5,
                    {"status": health["status"]}
                )
                
                self.record_metric(
                    "system.connected_agents",
                    float(health["connected_agents"])
                )
                
            except asyncio.CancelledError:
                break
            except Exception:
                pass
    
    def export_metrics(self, format: str = "json") -> str:
        """Export all metrics."""
        if format == "json":
            data = {
                "metrics": {
                    name: [
                        {"timestamp": p.timestamp, "value": p.value, "labels": p.labels}
                        for p in points
                    ]
                    for name, points in self._metrics.items()
                },
                "events": self._events[-100:],  # Last 100 events
                "exported_at": datetime.utcnow().isoformat()
            }
            return json.dumps(data, indent=2)
        return ""
