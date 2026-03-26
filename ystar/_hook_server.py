"""
ystar-hook — OpenClaw PreToolUse hook 处理服务

让 OpenClaw 可以通过以下方式调用 Y*：

  a) 子进程模式（stdin/stdout，推荐）：
     hooks:
       PreToolUse:
         - matcher: "*"
           hooks:
             - command: ystar-hook

  b) HTTP 服务模式：
     ystar-hook --serve --port 7777

用法：
  ystar-hook               从 stdin 读取 hook payload，输出决策到 stdout
  ystar-hook --serve       启动 HTTP 服务（POST /hook）
  ystar-hook --agents-md   指定规则文件路径
"""
from __future__ import annotations

import json
import os
import sys


def _load_policy(agents_md: str | None = None):
    """加载 Policy，LLM 不可用时回退到正则。"""
    from ystar import Policy
    # 跳过交互式确认（命令行服务模式）
    p = Policy.from_agents_md(path=agents_md, confirm=False)
    return p


def _handle_stdin(policy) -> None:
    """从 stdin 读取 JSON hook payload，输出决策到 stdout。"""
    from ystar.adapters.hook import check_hook
    try:
        payload = json.loads(sys.stdin.read())
        response = check_hook(payload, policy)
        print(json.dumps(response))
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"Invalid JSON: {e}"}))
        sys.exit(1)
    except Exception as e:
        # 失败安全：遇到未知错误允许执行（不阻断 Agent）
        print(json.dumps({}))
        sys.stderr.write(f"[ystar-hook] warning: {e}\n")


def _serve(policy, port: int = 7777) -> None:
    """启动 HTTP 服务，接收 OpenClaw hook POST 请求。"""
    from http.server import BaseHTTPRequestHandler, HTTPServer
    import threading
    from ystar.adapters.hook import check_hook

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length  = int(self.headers.get("Content-Length", 0))
            body    = self.rfile.read(length)
            try:
                payload  = json.loads(body)
                response = check_hook(payload, policy)
            except Exception as e:
                response = {}   # fail open
                sys.stderr.write(f"[ystar-hook] {e}\n")

            out = json.dumps(response).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def do_GET(self):
            if self.path == "/health":
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"status":"ok","service":"ystar-hook"}')
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, *_):
            pass   # 静默

    sys.stderr.write(f"[ystar-hook] HTTP server on port {port}\n")
    sys.stderr.write(f"[ystar-hook] POST http://localhost:{port}/hook\n")
    sys.stderr.write(f"[ystar-hook] GET  http://localhost:{port}/health\n")
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(
        prog="ystar-hook",
        description="Y* OpenClaw hook processor",
    )
    parser.add_argument("--agents-md", default=None,
                        help="AGENTS.md path (default: auto-detect)")
    parser.add_argument("--serve", action="store_true",
                        help="Start HTTP server instead of stdin mode")
    parser.add_argument("--port", type=int, default=7777,
                        help="HTTP server port (default: 7777)")
    args = parser.parse_args()

    import warnings
    warnings.filterwarnings("ignore")
    policy = _load_policy(args.agents_md)

    if args.serve:
        _serve(policy, args.port)
    else:
        _handle_stdin(policy)


if __name__ == "__main__":
    main()
