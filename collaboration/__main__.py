"""
Entry point for Hermes Agent Team Collaboration Backend.

Usage:
    python -m collab                        # CLI mode (shows help)
    python -m collab server                 # Start REST API server
    python -m collab server --port 8080    # Start on custom port
    python -m collab workspace list         # CLI workspace commands
    python -m collab agent list             # CLI agent commands
    python -m collab task list              # CLI task commands
    python -m collab skill list             # CLI skill commands
    python -m collab monitor health          # CLI monitoring
"""

import sys
import argparse
from pathlib import Path

# Add parent directory (hermes-agent/) to path so 'collab' package can be found
sys.path.insert(0, str(Path(__file__).parent.parent))


def main():
    """Main entry point with command routing."""
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
    
    # No subcommand - show CLI help
    args = parser.parse_args()
    
    if args.command == "server":
        # Import here to avoid circular imports
        from collaboration.server import main as server_main
        # Parse remaining args for server
        sys.argv = ["collab server", 
                   f"--host={args.host}",
                   f"--port={args.port}",
                   f"--log-level={args.log_level}"]
        if args.reload:
            sys.argv.append("--reload")
        server_main()
    else:
        # Run CLI mode
        from collaboration.cli import main as cli_main
        cli_main()


if __name__ == "__main__":
    main()
