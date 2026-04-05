#!/bin/bash
# Y*gov hook client — sends payload to persistent daemon via Unix socket.
# Startup: <5ms (no Python interpreter needed).
# Fallback: if daemon not running, spawns _hook_entry.py (slow path, ~1.4s).

SOCK="${YSTAR_HOOK_SOCK:-/tmp/ystar_hook.sock}"
PAYLOAD=$(cat)

if [ -S "$SOCK" ]; then
    # Fast path: daemon running, use socat or python socket
    if command -v socat &>/dev/null; then
        echo "$PAYLOAD" | socat - UNIX-CONNECT:"$SOCK"
    else
        # Fallback: minimal python socket client (still fast, no ystar import)
        python3.11 -c "
import socket,sys,json
s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
s.connect('$SOCK')
s.sendall(sys.stdin.buffer.read())
s.shutdown(socket.SHUT_WR)
d=b''
while True:
    c=s.recv(65536)
    if not c:break
    d+=c
s.close()
sys.stdout.write(d.decode())
" <<< "$PAYLOAD"
    fi
else
    # Slow path: daemon not running, fall back to full process spawn
    echo "$PAYLOAD" | python3.11 "$(dirname "$0")/_hook_entry.py"
fi
