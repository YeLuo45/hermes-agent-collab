#!/usr/bin/env python3
"""hermes-collab CLI — terminal interface for hermes-agent-collab.

Usage:
    hermes-collab agents list
    hermes-collab agents register --name <name> --role <role> --skills <csv>
    hermes-collab tasks create --title <title> [--priority high] [--complexity normal]
    hermes-collab tasks list [--status pending]
    hermes-collab orchestrations create --title <title> [--complexity normal]
    hermes-collab orchestrations start <orch_id>
    hermes-collab events stream [--types agent.registered,task.completed]
    hermes-collab workspaces list
    hermes-collab workspaces create --id <id> --name <name>
    hermes-collab auth create-key --name <name> [--workspace default] [--scopes read,write]
    hermes-collab auth list-keys
    hermes-collab health
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Optional

from rich.console import Console
from rich.table import Table
from rich.live import Live
from rich.syntax import Syntax
from rich.panel import Panel
from rich import box

try:
    from hermes_agent_collab import HermesCollab, Config
except ImportError:
    # Try running from source tree
    import pathlib
    src_root = pathlib.Path(__file__).parent
    sys.path.insert(0, str(src_root))
    from hermes_agent_collab import HermesCollab, Config


console = Console()


def _get_client() -> HermesCollab:
    api_key = os.environ.get("HERMES_COLLAB_API_KEY", "")
    base_url = os.environ.get("HERMES_COLLAB_BASE_URL", "http://localhost:8000/api/collab/v1")
    config = Config(api_key=api_key, base_url=base_url)
    return HermesCollab(config)


def cmd_health(client: HermesCollab, args):
    health = client.health()
    console.print(Panel(
        f"[green]Status:[/green] {health.status}\n"
        f"[blue]Version:[/blue] {health.version}\n"
        f"[yellow]Uptime:[/yellow] {health.uptime_seconds:.1f}s",
        title="Health Check",
        border_style="green",
    ))


def cmd_agents_list(client: HermesCollab, args):
    agents = client.agents.list()
    table = Table(title=f"Agents ({len(agents)})", box=box.ROUNDED)
    table.add_column("Status", style="green", no_wrap=True)
    table.add_column("Name", style="cyan")
    table.add_column("Role", style="yellow")
    table.add_column("Skills", style="dim")
    table.add_column("Agent ID", style="dim")
    for a in agents:
        status_color = "green" if a.status == "online" else "red"
        table.add_row(
            f"[{status_color}]●[/{status_color}] {a.status}",
            a.name or "—",
            a.role or "—",
            ", ".join(a.skills[:3]) or "—",
            a.agent_id,
        )
    console.print(table)


def cmd_agents_register(client: HermesCollab, args):
    skills = args.skills.split(",") if args.skills else []
    agent = client.agents.register(name=args.name, role=args.role or "executor", skills=skills)
    console.print(f"[green]✓[/green] Registered agent [cyan]{agent.name}[/cyan] ({agent.agent_id})")


def cmd_tasks_list(client: HermesCollab, args):
    tasks = client.tasks.list(status=args.status)
    table = Table(title=f"Tasks ({len(tasks)})", box=box.ROUNDED)
    table.add_column("Status", style="yellow", no_wrap=True)
    table.add_column("Title")
    table.add_column("Priority", style="red")
    table.add_column("ID", style="dim")
    for t in tasks:
        status_color = {"pending": "yellow", "in_progress": "blue", "completed": "green", "failed": "red"}.get(t.status, "dim")
        table.add_row(
            f"[{status_color}]{t.status}[/{status_color}]",
            t.title,
            t.priority,
            t.task_id,
        )
    console.print(table)


def cmd_tasks_create(client: HermesCollab, args):
    task = client.tasks.create(title=args.title, priority=args.priority or "medium", complexity=args.complexity)
    console.print(f"[green]✓[/green] Created task [cyan]{task.title}[/cyan] ({task.task_id})")


def cmd_orchestrations_list(client: HermesCollab, args):
    orchs = client.orchestrations.list()
    table = Table(title=f"Orchestrations ({len(orchs)})", box=box.ROUNDED)
    table.add_column("Phase", style="yellow")
    table.add_column("Title")
    table.add_column("Complexity", style="dim")
    table.add_column("ID", style="dim")
    for o in orchs:
        table.add_row(o.phase, o.title, o.complexity or "—", o.orchestration_id)
    console.print(table)


def cmd_orchestrations_create(client: HermesCollab, args):
    orch = client.orchestrations.create(title=args.title, complexity=args.complexity or "normal")
    console.print(f"[green]✓[/green] Created orchestration [cyan]{orch.title}[/cyan] ({orch.orchestration_id})")


def cmd_orchestrations_start(client: HermesCollab, args):
    orch = client.orchestrations.start(args.orchestration_id)
    console.print(f"[green]✓[/green] Started orchestration [cyan]{orch.orchestration_id}[/cyan] (phase={orch.phase})")


def cmd_events_stream(client: HermesCollab, args):
    event_types = args.types.split(",") if args.types else None
    console.print("[dim]Connecting to event stream... (Ctrl+C to stop)[/dim]")
    try:
        for event in client.events.stream(event_types=event_types):
            etype = event.event_type or "unknown"
            ts = event.timestamp[:19] if event.timestamp else "—"
            payload_preview = json.dumps(event.payload)[:80]
            color = _event_color(etype)
            console.print(f"[dim]{ts}[/dim] [{color}]{etype}[/{color}] {payload_preview}")
    except KeyboardInterrupt:
        console.print("\n[dim]Stream stopped.[/dim]")


def _event_color(etype: str) -> str:
    if etype.startswith("agent"):
        return "cyan"
    if etype.startswith("task"):
        return "yellow"
    if etype.startswith("orchestration") or etype.startswith("orch"):
        return "magenta"
    if etype.startswith("skill"):
        return "green"
    return "dim"


def cmd_workspaces_list(client: HermesCollab, args):
    workspaces = client.workspaces.list()
    table = Table(title=f"Workspaces ({len(workspaces)})", box=box.ROUNDED)
    table.add_column("ID", style="cyan")
    table.add_column("Name", style="white")
    table.add_column("Created", style="dim")
    for ws in workspaces:
        table.add_row(ws.workspace_id, ws.name, ws.created_at[:10])
    console.print(table)


def cmd_workspaces_create(client: HermesCollab, args):
    ws = client.workspaces.create(workspace_id=args.workspace_id, name=args.name, description=args.description or "")
    console.print(f"[green]✓[/green] Created workspace [cyan]{ws.workspace_id}[/cyan] ({ws.name})")


def cmd_auth_create_key(client: HermesCollab, args):
    scopes = args.scopes.split(",") if args.scopes else ["read"]
    resp = client.auth.create_key(name=args.name, workspace_id=args.workspace or "default", scopes=scopes)
    console.print(f"[green]✓[/green] Created API key [cyan]{resp.name}[/cyan]")
    console.print(f"  [yellow]key_id:[/yellow] {resp.key_id}")
    console.print(f"  [yellow]key_secret:[/yellow] {resp.key_secret}")
    console.print(f"  [dim]Store the secret now — it will not be shown again.[/dim]")


def cmd_auth_list_keys(client: HermesCollab, args):
    keys = client.auth.list_keys(workspace_id=args.workspace or "default")
    table = Table(title=f"API Keys ({len(keys)})", box=box.ROUNDED)
    table.add_column("Name", style="cyan")
    table.add_column("Key ID", style="dim")
    table.add_column("Scopes", style="yellow")
    table.add_column("Active", style="green")
    table.add_column("Last Used", style="dim")
    for k in keys:
        table.add_row(k.name, k.key_id, ", ".join(k.scopes), str(k.is_active), k.last_used_at or "never")
    console.print(table)


def main():
    parser = argparse.ArgumentParser(prog="hermes-collab", description="hermes-agent-collab CLI")
    sub = parser.add_subparsers(dest="command")

    # health
    sub.add_parser("health", help="Check API health")

    # agents
    agents = sub.add_parser("agents", help="Agent management")
    agents_sub = agents.add_subparsers(dest="subcommand")

    a_list = agents_sub.add_parser("list", help="List agents")
    a_list.set_defaults(fn=cmd_agents_list)

    a_reg = agents_sub.add_parser("register", help="Register an agent")
    a_reg.add_argument("--name", required=True)
    a_reg.add_argument("--role", default="executor")
    a_reg.add_argument("--skills", help="Comma-separated skills")
    a_reg.set_defaults(fn=cmd_agents_register)

    # tasks
    tasks = sub.add_parser("tasks", help="Task management")
    tasks_sub = tasks.add_subparsers(dest="subcommand")

    t_list = tasks_sub.add_parser("list", help="List tasks")
    t_list.add_argument("--status", help="Filter by status (pending/in_progress/completed/failed)")
    t_list.set_defaults(fn=cmd_tasks_list)

    t_create = tasks_sub.add_parser("create", help="Create a task")
    t_create.add_argument("--title", required=True)
    t_create.add_argument("--priority", default="medium")
    t_create.add_argument("--complexity", help="simple/normal/complex")
    t_create.set_defaults(fn=cmd_tasks_create)

    # orchestrations
    orchs = sub.add_parser("orchestrations", help="Orchestration management")
    orchs_sub = orchs.add_subparsers(dest="subcommand")

    o_list = orchs_sub.add_parser("list", help="List orchestrations")
    o_list.set_defaults(fn=cmd_orchestrations_list)

    o_create = orchs_sub.add_parser("create", help="Create an orchestration")
    o_create.add_argument("--title", required=True)
    o_create.add_argument("--complexity", default="normal")
    o_create.set_defaults(fn=cmd_orchestrations_create)

    o_start = orchs_sub.add_parser("start", help="Start an orchestration")
    o_start.add_argument("orchestration_id")
    o_start.set_defaults(fn=cmd_orchestrations_start)

    # events
    events = sub.add_parser("events", help="Event stream")
    events_sub = events.add_subparsers(dest="subcommand")

    e_stream = events_sub.add_parser("stream", help="Stream live events")
    e_stream.add_argument("--types", help="Comma-separated event types to filter")
    e_stream.set_defaults(fn=cmd_events_stream)

    # workspaces
    workspaces = sub.add_parser("workspaces", help="Workspace management")
    workspaces_sub = workspaces.add_subparsers(dest="subcommand")

    ws_list = workspaces_sub.add_parser("list", help="List workspaces")
    ws_list.set_defaults(fn=cmd_workspaces_list)

    ws_create = workspaces_sub.add_parser("create", help="Create a workspace")
    ws_create.add_argument("--id", dest="workspace_id", required=True)
    ws_create.add_argument("--name", required=True)
    ws_create.add_argument("--description", default="")
    ws_create.set_defaults(fn=cmd_workspaces_create)

    # auth
    auth = sub.add_parser("auth", help="API key management")
    auth_sub = auth.add_subparsers(dest="subcommand")

    ak_create = auth_sub.add_parser("create-key", help="Create an API key")
    ak_create.add_argument("--name", required=True)
    ak_create.add_argument("--workspace", default="default")
    ak_create.add_argument("--scopes", default="read,write", help="Comma-separated scopes")
    ak_create.set_defaults(fn=cmd_auth_create_key)

    ak_list = auth_sub.add_parser("list-keys", help="List API keys")
    ak_list.add_argument("--workspace", default="default")
    ak_list.set_defaults(fn=cmd_auth_list_keys)

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    fn = args.__dict__.pop("fn", None)
    if not fn:
        parser.print_help()
        sys.exit(1)

    # Remove subcommand arg used for routing
    args.__dict__.pop("subcommand", None)

    try:
        client = _get_client()
        fn(client, args)
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
