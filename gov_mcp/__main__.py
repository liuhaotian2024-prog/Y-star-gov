"""Entry point: python -m gov_mcp [options]."""

import argparse
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="GOV MCP — Y*gov as a standard MCP server")
    parser.add_argument("--agents-md", type=str, required=True, help="Path to AGENTS.md governance file")
    parser.add_argument("--transport", choices=["stdio", "sse"], default="stdio", help="MCP transport (default: stdio)")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="SSE host (only with --transport sse)")
    parser.add_argument("--port", type=int, default=0, help="SSE port (required with --transport sse)")
    args = parser.parse_args()

    agents_md_path = Path(args.agents_md).resolve()
    if not agents_md_path.is_file():
        print(f"Error: {agents_md_path} does not exist", file=sys.stderr)
        sys.exit(1)

    from gov_mcp.server import create_server

    server = create_server(agents_md_path)

    tools = [t.name for t in server._tool_manager._tools.values()]
    print(f"[GOV MCP] ready — {len(tools)} tools registered, transport={args.transport}", file=sys.stderr)
    print(f"[GOV MCP] contract loaded from {agents_md_path}", file=sys.stderr)

    if args.transport == "stdio":
        server.run(transport="stdio")
    else:
        if args.port == 0:
            print("Error: --port is required with --transport sse", file=sys.stderr)
            sys.exit(1)
        server.run(transport="sse", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
