"""
CLI Interface for Hermes Agent Team Collaboration Backend.
Provides command-line interface for managing workspaces, agents, tasks, and skills.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Optional

try:
    from .models import AgentStatus, TaskStatus, Priority, SkillCategory
    from .workspace import WorkspaceManager
    from .agent_registry import AgentRegistry
    from .task_manager import TaskManager
    from .skill_system import SkillSystem
    from .monitor import RuntimeMonitor
except ImportError:
    from collaboration.models import AgentStatus, TaskStatus, Priority, SkillCategory
    from collaboration.workspace import WorkspaceManager
    from collaboration.agent_registry import AgentRegistry
    from collaboration.task_manager import TaskManager
    from collaboration.skill_system import SkillSystem
    from collaboration.monitor import RuntimeMonitor


class CollaborationCLI:
    """CLI interface for team collaboration."""
    
    def __init__(self, base_path: str = "~/.hermes"):
        self.base_path = Path(base_path).expanduser()
        self.workspace_mgr = WorkspaceManager(base_path)
        self.agent_registry = AgentRegistry(base_path)
        self.task_mgr = TaskManager(base_path)
        self.skill_system = SkillSystem(base_path)
        self.monitor = RuntimeMonitor(base_path)
    
    # Workspace commands
    def cmd_workspace_create(self, args):
        """Create a new workspace."""
        ws = self.workspace_mgr.create_workspace(
            name=args.name,
            owner_id=args.owner,
            description=args.description or ""
        )
        print(f"Created workspace: {ws.workspace_id}")
        print(f"  Name: {ws.name}")
        if hasattr(ws, 'owner_id') and ws.owner_id:
            print(f"  Owner: {ws.owner_id}")
        return ws
    
    def cmd_workspace_list(self, args):
        """List workspaces."""
        workspaces = self.workspace_mgr.list_workspaces(
            owner_id=args.owner,
            is_active=args.active_only
        )
        if not workspaces:
            print("No workspaces found.")
            return
        
        print(f"Workspaces ({len(workspaces)}):")
        for ws in workspaces:
            print(f"  {ws.workspace_id}: {ws.name}")
            if hasattr(ws, 'owner_id') and ws.owner_id:
                print(f"    Owner: {ws.owner_id}")
            agents = getattr(ws, 'agents', [])
            print(f"    Agents: {len(agents)}")
    
    def cmd_workspace_info(self, args):
        """Get workspace info."""
        ws = self.workspace_mgr.get_workspace(args.workspace_id)
        if not ws:
            print(f"Workspace not found: {args.workspace_id}")
            return
        
        print(f"Workspace: {ws.workspace_id}")
        print(f"  Name: {ws.name}")
        print(f"  Description: {ws.description}")
        if hasattr(ws, 'owner_id') and ws.owner_id:
            print(f"  Owner: {ws.owner_id}")
        if hasattr(ws, 'is_active'):
            print(f"  Active: {ws.is_active}")
        print(f"  Agents: {getattr(ws, 'agents', [])}")
        print(f"  Created: {ws.created_at}")
    
    def cmd_workspace_delete(self, args):
        """Delete workspace."""
        success = self.workspace_mgr.delete_workspace(
            args.workspace_id,
            force=args.force
        )
        if success:
            print(f"Deleted workspace: {args.workspace_id}")
        else:
            print(f"Failed to delete workspace (may not be empty): {args.workspace_id}")
    
    # Agent commands
    def cmd_agent_register(self, args):
        """Register a new agent."""
        profile = self.agent_registry.register_agent(
            name=args.name,
            role=args.role,
            description=args.description or "",
            skills=args.skills.split(",") if args.skills else [],
            workspace_id=args.workspace
        )
        print(f"Registered agent: {profile.agent_id}")
        print(f"  Name: {profile.name}")
        print(f"  Role: {profile.role}")
        return profile
    
    def cmd_agent_list(self, args):
        """List agents."""
        agents = self.agent_registry.list_agents(
            workspace_id=args.workspace,
            status=args.status,
            role=args.role
        )
        if not agents:
            print("No agents found.")
            return
        
        print(f"Agents ({len(agents)}):")
        for agent in agents:
            status_icon = "🟢" if agent.status == AgentStatus.ONLINE else "🔴"
            print(f"  {status_icon} {agent.agent_id}: {agent.name} ({agent.role})")
            if agent.current_task_id:
                print(f"      Task: {agent.current_task_id}")
    
    def cmd_agent_info(self, args):
        """Get agent info."""
        agent = self.agent_registry.get_agent(args.agent_id)
        if not agent:
            print(f"Agent not found: {args.agent_id}")
            return
        
        print(f"Agent: {agent.agent_id}")
        print(f"  Name: {agent.name}")
        print(f"  Role: {agent.role}")
        print(f"  Description: {agent.description}")
        print(f"  Status: {agent.status.value}")
        print(f"  Workspace: {agent.workspace_id}")
        print(f"  Skills: {agent.skills}")
        print(f"  Current Task: {agent.current_task_id}")
        print(f"  Created: {agent.created_at}")
    
    def cmd_agent_status(self, args):
        """Update agent status."""
        status = AgentStatus(args.status)
        success = self.agent_registry.update_status(args.agent_id, status)
        if success:
            print(f"Updated agent status: {args.agent_id} -> {status.value}")
        else:
            print(f"Failed to update agent status: {args.agent_id}")
    
    # Task commands
    def cmd_task_create(self, args):
        """Create a new task."""
        priority = Priority(args.priority) if args.priority else Priority.MEDIUM
        task = self.task_mgr.create_task(
            title=args.title,
            description=args.description or "",
            workspace_id=args.workspace,
            owner_id=args.owner,
            assignee_id=args.assignee,
            priority=priority,
            skills_required=args.skills.split(",") if args.skills else []
        )
        print(f"Created task: {task.task_id}")
        print(f"  Title: {task.title}")
        print(f"  Priority: {task.priority.value}")
        return task
    
    def cmd_task_list(self, args):
        """List tasks."""
        tasks = self.task_mgr.list_tasks(
            workspace_id=args.workspace,
            status=args.status,
            priority=args.priority,
            assignee_id=args.assignee
        )
        if not tasks:
            print("No tasks found.")
            return
        
        print(f"Tasks ({len(tasks)}):")
        for task in tasks:
            status_icon = {
                TaskStatus.PENDING: "⏳",
                TaskStatus.IN_PROGRESS: "🔄",
                TaskStatus.BLOCKED: "🚫",
                TaskStatus.COMPLETED: "✅",
                TaskStatus.FAILED: "❌",
                TaskStatus.CANCELLED: "➖"
            }.get(task.status, "❓")
            print(f"  {status_icon} {task.task_id}: {task.title}")
            print(f"      Priority: {task.priority.value}, Status: {task.status.value}")
            if task.assignee_id:
                print(f"      Assignee: {task.assignee_id}")
    
    def cmd_task_info(self, args):
        """Get task info."""
        task = self.task_mgr.get_task(args.task_id)
        if not task:
            print(f"Task not found: {args.task_id}")
            return
        
        print(f"Task: {task.task_id}")
        print(f"  Title: {task.title}")
        print(f"  Description: {task.description}")
        print(f"  Status: {task.status.value}")
        print(f"  Priority: {task.priority.value}")
        print(f"  Owner: {task.owner_id}")
        print(f"  Assignee: {task.assignee_id}")
        print(f"  Workspace: {task.workspace_id}")
        print(f"  Skills Required: {task.skills_required}")
        print(f"  Blocked By: {task.blocked_by}")
        if task.started_at:
            print(f"  Started: {task.started_at}")
        if task.completed_at:
            print(f"  Completed: {task.completed_at}")
    
    def cmd_task_update(self, args):
        """Update task status."""
        if args.action == "start":
            task = self.task_mgr.start_task(args.task_id, args.agent_id)
            print(f"Started task: {args.task_id}")
        elif args.action == "complete":
            result = json.loads(args.result) if args.result else None
            task = self.task_mgr.complete_task(args.task_id, result)
            print(f"Completed task: {args.task_id}")
        elif args.action == "fail":
            task = self.task_mgr.fail_task(args.task_id, args.error or "Unknown error")
            print(f"Failed task: {args.task_id}")
        elif args.action == "block":
            blockers = args.blockers.split(",") if args.blockers else []
            task = self.task_mgr.block_task(args.task_id, blockers)
            print(f"Blocked task: {args.task_id}")
        elif args.action == "unblock":
            task = self.task_mgr.unblock_task(args.task_id)
            print(f"Unblocked task: {args.task_id}")
        
        if not task:
            print(f"Failed to update task: {args.task_id}")
    
    # Skill commands
    def cmd_skill_create(self, args):
        """Create a new skill."""
        category = SkillCategory(args.category)
        skill = self.skill_system.create_skill(
            name=args.name,
            category=category,
            description=args.description or ""
        )
        print(f"Created skill: {skill.skill_id}")
        print(f"  Name: {skill.name}")
        print(f"  Category: {skill.category.value}")
        return skill
    
    def cmd_skill_list(self, args):
        """List skills."""
        skills = self.skill_system.list_skills(
            category=SkillCategory(args.category) if args.category else None,
            enabled=args.enabled_only
        )
        if not skills:
            print("No skills found.")
            return
        
        print(f"Skills ({len(skills)}):")
        for skill in skills:
            status = "✓" if skill.enabled else "✗"
            print(f"  {status} {skill.skill_id}: {skill.name} [{skill.category.value}]")
    
    # Monitor commands
    def cmd_monitor_health(self, args):
        """Get system health."""
        health = self.monitor.get_system_health()
        print(f"System Health: {health['status'].upper()}")
        print(f"  Connected Agents: {health['connected_agents']}")
        print(f"  Events (5min): {health['events_last_5min']}")
        print(f"  Errors (5min): {health['error_count_last_5min']}")
        print(f"  Total Events: {health['total_events']}")
    
    def cmd_monitor_events(self, args):
        """Get recent events."""
        events = self.monitor.get_events(
            event_type=args.type,
            limit=args.limit
        )
        if not events:
            print("No events found.")
            return
        
        print(f"Events ({len(events)}):")
        for event in events:
            print(f"  [{event['timestamp']}] {event['type']}")
            print(f"    Source: {event['source_id']}")
            if event.get('target_id'):
                print(f"    Target: {event['target_id']}")
    
    def cmd_monitor_stats(self, args):
        """Get workspace stats."""
        if args.workspace_id:
            stats = self.task_mgr.get_task_stats(args.workspace_id)
            print(f"Task Statistics for {args.workspace_id}:")
            print(f"  Total: {stats['total']}")
            print(f"  By Status: {stats['by_status']}")
            print(f"  By Priority: {stats['by_priority']}")
            print(f"  Completion Rate: {stats['completion_rate']:.2%}")
        else:
            skill_stats = self.skill_system.get_skill_stats()
            print("Skill Statistics:")
            print(f"  Total: {skill_stats['total']}")
            print(f"  Enabled: {skill_stats['enabled']}")
            print(f"  By Category: {skill_stats['by_category']}")


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Hermes Agent Team Collaboration CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")
    
    # Workspace subcommands
    ws_parser = subparsers.add_parser("workspace", help="Workspace management")
    ws_sub = ws_parser.add_subparsers(dest="action")
    
    ws_create = ws_sub.add_parser("create", help="Create workspace")
    ws_create.add_argument("--name", required=True, help="Workspace name")
    ws_create.add_argument("--owner", required=True, help="Owner agent ID")
    ws_create.add_argument("--description", help="Description")
    
    ws_list = ws_sub.add_parser("list", help="List workspaces")
    ws_list.add_argument("--owner", help="Filter by owner")
    ws_list.add_argument("--active-only", action="store_true", default=True)
    
    ws_info = ws_sub.add_parser("info", help="Get workspace info")
    ws_info.add_argument("workspace_id", help="Workspace ID")
    
    ws_delete = ws_sub.add_parser("delete", help="Delete workspace")
    ws_delete.add_argument("workspace_id", help="Workspace ID")
    ws_delete.add_argument("--force", action="store_true", help="Force delete")
    
    # Agent subcommands
    agent_parser = subparsers.add_parser("agent", help="Agent management")
    agent_sub = agent_parser.add_subparsers(dest="action")
    
    agent_register = agent_sub.add_parser("register", help="Register agent")
    agent_register.add_argument("--name", required=True, help="Agent name")
    agent_register.add_argument("--role", required=True, help="Agent role")
    agent_register.add_argument("--description", help="Description")
    agent_register.add_argument("--skills", help="Comma-separated skill IDs")
    agent_register.add_argument("--workspace", help="Workspace ID")
    
    agent_list = agent_sub.add_parser("list", help="List agents")
    agent_list.add_argument("--workspace", help="Filter by workspace")
    agent_list.add_argument("--status", help="Filter by status")
    agent_list.add_argument("--role", help="Filter by role")
    
    agent_info = agent_sub.add_parser("info", help="Get agent info")
    agent_info.add_argument("agent_id", help="Agent ID")
    
    agent_status = agent_sub.add_parser("status", help="Update agent status")
    agent_status.add_argument("agent_id", help="Agent ID")
    agent_status.add_argument("status", choices=["online", "offline", "busy", "away", "error"])
    
    # Task subcommands
    task_parser = subparsers.add_parser("task", help="Task management")
    task_sub = task_parser.add_subparsers(dest="action")
    
    task_create = task_sub.add_parser("create", help="Create task")
    task_create.add_argument("--title", required=True, help="Task title")
    task_create.add_argument("--description", help="Description")
    task_create.add_argument("--workspace", required=True, help="Workspace ID")
    task_create.add_argument("--owner", help="Owner agent ID")
    task_create.add_argument("--assignee", help="Assignee agent ID")
    task_create.add_argument("--priority", choices=["low", "medium", "high", "urgent", "critical"])
    task_create.add_argument("--skills", help="Comma-separated required skill IDs")
    
    task_list = task_sub.add_parser("list", help="List tasks")
    task_list.add_argument("--workspace", help="Filter by workspace")
    task_list.add_argument("--status", help="Filter by status")
    task_list.add_argument("--priority", help="Filter by priority")
    task_list.add_argument("--assignee", help="Filter by assignee")
    
    task_info = task_sub.add_parser("info", help="Get task info")
    task_info.add_argument("task_id", help="Task ID")
    
    task_update = task_sub.add_parser("update", help="Update task")
    task_update.add_argument("task_id", help="Task ID")
    task_update.add_argument("action", choices=["start", "complete", "fail", "block", "unblock"])
    task_update.add_argument("--agent-id", help="Agent ID (for start)")
    task_update.add_argument("--result", help="Result JSON (for complete)")
    task_update.add_argument("--error", help="Error message (for fail)")
    task_update.add_argument("--blockers", help="Comma-separated blocking task IDs")
    
    # Skill subcommands
    skill_parser = subparsers.add_parser("skill", help="Skill management")
    skill_sub = skill_parser.add_subparsers(dest="action")
    
    skill_create = skill_sub.add_parser("create", help="Create skill")
    skill_create.add_argument("--name", required=True, help="Skill name")
    skill_create.add_argument("--category", required=True, help="Category")
    skill_create.add_argument("--description", help="Description")
    
    skill_list = skill_sub.add_parser("list", help="List skills")
    skill_list.add_argument("--category", help="Filter by category")
    skill_list.add_argument("--enabled-only", action="store_true")
    
    # Monitor subcommands
    monitor_parser = subparsers.add_parser("monitor", help="Monitoring")
    monitor_sub = monitor_parser.add_subparsers(dest="action")
    
    monitor_health = monitor_sub.add_parser("health", help="System health")
    monitor_events = monitor_sub.add_parser("events", help="Recent events")
    monitor_events.add_argument("--type", help="Event type filter")
    monitor_events.add_argument("--limit", type=int, default=50)
    
    monitor_stats = monitor_sub.add_parser("stats", help="Statistics")
    monitor_stats.add_argument("--workspace-id", help="Workspace ID")
    
    # Server subcommand
    server_parser = subparsers.add_parser("server", help="Server management")
    server_sub = server_parser.add_subparsers(dest="action")
    
    server_start = server_sub.add_parser("start", help="Start WebSocket server")
    server_start.add_argument("--host", default="localhost")
    server_start.add_argument("--port", type=int, default=8765)
    
    server_stop = server_sub.add_parser("stop", help="Stop WebSocket server")
    
    # Parse and execute
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    cli = CollaborationCLI()
    
    # Route commands
    if args.command == "workspace":
        if args.action == "create":
            cli.cmd_workspace_create(args)
        elif args.action == "list":
            cli.cmd_workspace_list(args)
        elif args.action == "info":
            cli.cmd_workspace_info(args)
        elif args.action == "delete":
            cli.cmd_workspace_delete(args)
        else:
            ws_parser.print_help()
    
    elif args.command == "agent":
        if args.action == "register":
            cli.cmd_agent_register(args)
        elif args.action == "list":
            cli.cmd_agent_list(args)
        elif args.action == "info":
            cli.cmd_agent_info(args)
        elif args.action == "status":
            cli.cmd_agent_status(args)
        else:
            agent_parser.print_help()
    
    elif args.command == "task":
        if args.action == "create":
            cli.cmd_task_create(args)
        elif args.action == "list":
            cli.cmd_task_list(args)
        elif args.action == "info":
            cli.cmd_task_info(args)
        elif args.action == "update":
            cli.cmd_task_update(args)
        else:
            task_parser.print_help()
    
    elif args.command == "skill":
        if args.action == "create":
            cli.cmd_skill_create(args)
        elif args.action == "list":
            cli.cmd_skill_list(args)
        else:
            skill_parser.print_help()
    
    elif args.command == "monitor":
        if args.action == "health":
            cli.cmd_monitor_health(args)
        elif args.action == "events":
            cli.cmd_monitor_events(args)
        elif args.action == "stats":
            cli.cmd_monitor_stats(args)
        else:
            monitor_parser.print_help()
    
    elif args.command == "server":
        if args.action == "start":
            print(f"Starting server on {args.host}:{args.port}...")
            cli.ws_server = CollaborationServer(host=args.host, port=args.port)
            asyncio.run(cli.ws_server.start())
        elif args.action == "stop":
            if cli.ws_server:
                asyncio.run(cli.ws_server.stop())
        else:
            server_parser.print_help()
    
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
