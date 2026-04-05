# GOV MCP Setup — Y* Bridge Labs Internal

## Mac mini (server side)

Server already running:
```
[GOV MCP] ready — 12 tools registered, transport=sse
[GOV MCP] SSE listening on 0.0.0.0:7922
```

## Windows (client side) — Claude Code

Add to `C:\Users\liuha\.claude\settings.json`:

```json
{
  "mcpServers": {
    "gov-mcp": {
      "type": "url",
      "url": "http://192.168.1.228:7922/sse"
    }
  }
}
```

Then restart Claude Code. Verify with: "list your MCP tools" — should show 12 gov_* tools.

## Windows (client side) — OpenClaw

Add to `~/.config/openclaw/openclaw.json`:

```json
{
  "mcp_servers": {
    "gov-mcp": {
      "transport": "sse",
      "url": "http://192.168.1.228:7922/sse"
    }
  }
}
```

## Generic MCP Client

```
MCP_SERVER_URL=http://192.168.1.228:7922/sse
```
