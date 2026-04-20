"""
Entry point for Hermes Agent Team Collaboration Backend.

Usage:
    python3 -m collaboration                  # CLI mode (shows help)
    python3 -m collaboration server            # Start REST API server
    python3 -m collaboration server --port 8080  # Start on custom port
    python3 -m collaboration workspace list    # CLI workspace commands
    python3 -m collaboration agent list        # CLI agent commands
    python3 -m collaboration task list         # CLI task commands
    python3 -m collaboration skill list        # CLI skill commands
    python3 -m collaboration monitor health    # CLI monitoring
"""

import sys
import argparse
from pathlib import Path

# Add parent directory (hermes-agent/) to path so 'collaboration' package can be found
sys.path.insert(0, str(Path(__file__).parent.parent))


def main():
    """Main entry point with command routing."""
    
    # Check first argument to decide which parser to use
    # If it's 'server', use the server subparser
    # Otherwise, pass through to cli.py which handles workspace/agent/task/skill/monitor
    if len(sys.argv) > 1 and sys.argv[1] == "server":
        parser = argparse.ArgumentParser(
            description="Hermes Agent Team Collaboration",
            formatter_class=argparse.RawDescriptionHelpFormatter
        )
        parser.add_argument(
            "--version",
            action="version",
            version="%(prog)s 1.0.0"
        )
        
        subparsers = parser.add_subparsers(dest="command", help="Command to execute")
        
        # Server subcommand
        server_parser = subparsers.add_parser("server", help="Start the collaboration server")
        server_parser.add_argument("--host", default="127.0.0.1", help="Host to bind")
        server_parser.add_argument("--port", type=int, default=9119, help="Port to bind")
        server_parser.add_argument("--reload", action="store_true", help="Enable auto-reload")
        server_parser.add_argument("--log-level", default="info", 
                                   choices=["debug", "info", "warning", "error"])
        
        args = parser.parse_args()
        
        if args.command == "server":
            from collaboration.server import main as server_main
            sys.argv = ["collab server", 
                       f"--host={args.host}",
                       f"--port={args.port}",
                       f"--log-level={args.log_level}"]
            if args.reload:
                sys.argv.append("--reload")
            server_main()
    else:
        # Run CLI mode - pass through to cli.py which handles
        # workspace, agent, task, skill, monitor subcommands
        from collaboration.cli import main as cli_main
        sys.argv[0] = "collab"  # Fix argv[0] for proper help output
        cli_main()


if __name__ == "__main__":
    main()
