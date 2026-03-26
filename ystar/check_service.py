#!/usr/bin/env python3
"""
Y* Check Service — production-ready sidecar, zero runtime dependencies

Exposes Y* constraint checking, learning, and delegation validation
over HTTP so any language can integrate with Y*.

Endpoints:
  POST /v1/check               → check params against a contract
  POST /v1/learn               → learn from CIEU call history
  POST /v1/delegation/validate → validate a delegation chain
  GET  /v1/health              → liveness probe
  GET  /v1/ready               → readiness probe

Production features (v0.21.0):
  ✓ API-key auth          (X-Api-Key header; disable with --no-auth for dev)
  ✓ Request IDs           (X-Request-ID echoed; UUID generated if absent)
  ✓ Structured JSON logs  (timestamp, level, request_id, method, path, status, latency_ms)
  ✓ /v1/metrics endpoint  (counters: requests_total, violations_total, errors_total)
  ✓ /v1/health + /v1/ready probes
  ✓ Max request body size (default 1 MB)
  ✓ Per-request timeout   (default 10 s)
  ✓ CORS headers          (configurable --cors-origin)

Usage:
  python3 check_service.py [--port 8421] [--host 0.0.0.0] \
      [--api-key SECRET] [--no-auth] [--max-body 1048576]

Example:
  curl -X POST http://localhost:8421/v1/check \
    -H "Content-Type: application/json" \
    -H "X-Api-Key: SECRET" \
    -d '{"contract":{"deny":["evil"],"value_range":{"amount":{"max":1000}}},
         "params":{"amount":500}}'
"""
import sys, os, json, time, argparse, logging, uuid, threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from io import BytesIO

# ── Package location ──────────────────────────────────────────────────────────
# This file lives at ystar/check_service.py.  When run directly, we need the
# project root (parent of ystar/) on the path so that "from ystar import ..."
# works.  When imported as ystar.check_service (via pip install), the package is
# already importable and the sys.path tweak is harmless.
_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_HERE)   # parent of the ystar/ package dir
for _p in (_PROJECT_ROOT, _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ystar import IntentContract, check, DelegationChain
from ystar import __version__ as YSTAR_VERSION

# ── Structured logger ─────────────────────────────────────────────────────────
_log = logging.getLogger("ystar.service")

def _setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        '{"time":"%(asctime)s","level":"%(levelname)s",'
        '"logger":"%(name)s","message":%(message)s}',
        datefmt="%Y-%m-%dT%H:%M:%S"
    ))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

# ── Metrics (lock-free counters) ──────────────────────────────────────────────
class _Metrics:
    def __init__(self):
        self._lock = threading.Lock()
        self.requests_total   = 0
        self.violations_total = 0
        self.errors_total     = 0
        self.start_time       = time.time()

    def inc(self, field: str, n: int = 1):
        with self._lock:
            setattr(self, field, getattr(self, field) + n)

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "requests_total":   self.requests_total,
                "violations_total": self.violations_total,
                "errors_total":     self.errors_total,
                "uptime_seconds":   round(time.time() - self.start_time, 1),
                "ystar_version":    YSTAR_VERSION,
            }

_metrics = _Metrics()

# ── Config (set at startup) ───────────────────────────────────────────────────
_config: dict = {
    "api_key":      None,   # None = auth disabled
    "max_body":     1 << 20,  # 1 MB
    "cors_origin":  "*",
    "timeout":      10.0,
}

# ── Handler ───────────────────────────────────────────────────────────────────
# ── Template key reference (served at GET /v1/template-keys) ──────────────────
_TEMPLATE_KEY_REFERENCE = {
    "description": "Fill-in-the-blanks keys for POST /v1/from-template",
    "layer1_basic": {
        "can_write_to":    {"type": "list[str]", "example": ["./workspace/dev/"],
                            "desc": "Paths the entity is allowed to write"},
        "can_call":        {"type": "list[str]", "example": ["api.hubspot.com"],
                            "desc": "Domains/URLs the entity is allowed to call"},
        "cannot_touch":    {"type": "list[str]", "example": [".env", "production"],
                            "desc": "Strings that must never appear in any parameter"},
        "cannot_run":      {"type": "list[str]", "example": ["rm -rf", "DELETE FROM"],
                            "desc": "Command prefixes that are blocked"},
        "field_NAME_deny": {"type": "list[str]", "example": {"field_env_deny": ["prod", "live"]},
                            "desc": "Block specific values for a named parameter"},
        "XYZ_limit":       {"type": "number",    "example": {"amount_limit": 10000},
                            "desc": "Maximum value for parameter XYZ"},
        "XYZ_min":         {"type": "number",    "example": {"amount_min": 1},
                            "desc": "Minimum value for parameter XYZ"},
    },
    "layer2_advanced": {
        "max_calls_per_hour":   {"type": "int",    "example": 100,
                                 "desc": "Rate limit: max calls per hour"},
        "max_calls_per_minute": {"type": "int",    "example": 20,
                                 "desc": "Rate limit: max calls per minute"},
        "min_interval_seconds": {"type": "float",  "example": 5,
                                 "desc": "Minimum seconds between calls"},
        "aggregate_param":      {"type": "str",    "example": "amount",
                                 "desc": "Parameter name to aggregate"},
        "aggregate_daily_max":  {"type": "float",  "example": 50000,
                                 "desc": "Max cumulative value per day"},
        "required_roles":       {"type": "list[str]", "example": ["finance", "approver"],
                                 "desc": "Roles required to perform this action"},
        "deny_env":             {"type": "list[str]", "example": ["production", "prod"],
                                 "desc": "Environments where this action is blocked"},
        "allowed_hours":        {"type": "str",    "example": "09:30-17:00",
                                 "desc": "Time window when action is allowed (HH:MM-HH:MM)"},
    },
    "example_request": {
        "template": {
            "can_write_to":  ["./workspace/dev/"],
            "cannot_touch":  [".env", "production"],
            "cannot_run":    ["rm -rf", "git push --force"],
            "amount_limit":  10000,
            "amount_min":    1,
        },
        "params": {
            "file_path": "./workspace/dev/main.py",
            "amount": 500,
        }
    }
}


class YStarHandler(BaseHTTPRequestHandler):

    # ── Logging ───────────────────────────────────────────────────────────────
    def log_message(self, fmt, *args):
        pass  # suppress default Apache-style logs; we emit structured logs ourselves

    def _log_request(self, status: int, latency_ms: float, request_id: str,
                     extra: dict = None):
        msg = {
            "request_id": request_id,
            "method": self.command,
            "path": self.path,
            "status": status,
            "latency_ms": round(latency_ms, 3),
        }
        if extra:
            msg.update(extra)
        level = logging.WARNING if status >= 400 else logging.INFO
        _log.log(level, json.dumps(msg))

    # ── Response helpers ──────────────────────────────────────────────────────
    def _send_json(self, status: int, body: dict, request_id: str,
                   extra_headers: dict = None):
        payload = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("X-Request-ID", request_id)
        cors = _config.get("cors_origin", "*")
        if cors:
            self.send_header("Access-Control-Allow-Origin", cors)
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(payload)

    def _read_body(self) -> bytes | None:
        length = int(self.headers.get("Content-Length", 0))
        if length > _config["max_body"]:
            return None
        return self.rfile.read(length)

    def _auth_ok(self) -> bool:
        key = _config.get("api_key")
        if key is None:
            return True
        return self.headers.get("X-Api-Key", "") == key

    def _request_id(self) -> str:
        rid = self.headers.get("X-Request-ID", "")
        return rid if rid else str(uuid.uuid4())

    # ── Route dispatch ────────────────────────────────────────────────────────
    def do_GET(self):
        t0  = time.time()
        rid = self._request_id()
        _metrics.inc("requests_total")

        if self.path == "/v1/health":
            body = {"status": "ok", "version": YSTAR_VERSION}
            self._send_json(200, body, rid)
            self._log_request(200, (time.time()-t0)*1000, rid)

        elif self.path == "/v1/ready":
            body = {"status": "ready", "version": YSTAR_VERSION}
            self._send_json(200, body, rid)
            self._log_request(200, (time.time()-t0)*1000, rid)

        elif self.path == "/v1/metrics":
            if not self._auth_ok():
                self._send_json(401, {"error": "Unauthorized"}, rid)
                _metrics.inc("errors_total")
                self._log_request(401, (time.time()-t0)*1000, rid)
                return
            self._send_json(200, _metrics.snapshot(), rid)
            self._log_request(200, (time.time()-t0)*1000, rid)

        elif self.path in ("/", "/builder"):
            # Serve the Policy Builder UI — zero-friction visual config
            self._send_builder_ui(rid)
            self._log_request(200, (time.time()-t0)*1000, rid)

        elif self.path == "/v1/template-keys":
            # Return the fill-in-the-blanks key reference (no auth required)
            self._send_json(200, _TEMPLATE_KEY_REFERENCE, rid)
            self._log_request(200, (time.time()-t0)*1000, rid)

        else:
            self._send_json(404, {"error": f"Not found: {self.path}"}, rid)
            self._log_request(404, (time.time()-t0)*1000, rid)

    def do_OPTIONS(self):
        """CORS pre-flight."""
        rid = self._request_id()
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", _config.get("cors_origin", "*"))
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers",
                         "Content-Type, X-Api-Key, X-Request-ID")
        self.send_header("X-Request-ID", rid)
        self.end_headers()

    def do_POST(self):
        t0  = time.time()
        rid = self._request_id()
        _metrics.inc("requests_total")

        # Auth
        if not self._auth_ok():
            self._send_json(401, {"error": "Unauthorized — X-Api-Key required"}, rid)
            _metrics.inc("errors_total")
            self._log_request(401, (time.time()-t0)*1000, rid)
            return

        # Body
        raw = self._read_body()
        if raw is None:
            self._send_json(413, {"error": "Request body too large"}, rid)
            _metrics.inc("errors_total")
            self._log_request(413, (time.time()-t0)*1000, rid)
            return

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            self._send_json(400, {"error": f"Invalid JSON: {e}"}, rid)
            _metrics.inc("errors_total")
            self._log_request(400, (time.time()-t0)*1000, rid)
            return

        # Route
        try:
            if self.path == "/v1/check":
                resp, status = self._handle_check(data)
            elif self.path == "/v1/learn":
                resp, status = self._handle_learn(data)
            elif self.path == "/v1/delegation/validate":
                resp, status = self._handle_delegation_validate(data)
            elif self.path == "/v1/from-template":
                resp, status = self._handle_from_template(data)
            else:
                resp, status = {"error": f"Not found: {self.path}"}, 404

        except Exception as e:
            _metrics.inc("errors_total")
            resp   = {"error": str(e), "type": type(e).__name__}
            status = 500
            _log.exception(json.dumps({"request_id": rid, "error": str(e)}))

        latency_ms = (time.time() - t0) * 1000
        resp["request_id"]  = rid
        resp["latency_ms"]  = round(latency_ms, 3)
        self._send_json(status, resp, rid)
        self._log_request(status, latency_ms, rid)

    # ── Handlers ──────────────────────────────────────────────────────────────

    def _handle_check(self, data: dict) -> tuple[dict, int]:
        """
        POST /v1/check
        Body: {
            "contract": { ... IntentContract dict ... },
            "params":   { ... },
            "result":   { ... }   (optional, for postcondition checks)
        }
        """
        contract_d = data.get("contract")
        params     = data.get("params", {})
        result     = data.get("result", {})

        if contract_d is None:
            return {"error": "Missing 'contract' field"}, 400

        contract   = IntentContract.from_dict(contract_d)
        cr         = check(params, result, contract)

        violations = [
            {
                "dimension":  v.dimension,
                "field":      v.field,
                "message":    v.message,
                "actual":     str(v.actual),
                "constraint": v.constraint,
                "severity":   v.severity,
            }
            for v in cr.violations
        ]

        if not cr.passed:
            _metrics.inc("violations_total", len(violations))

        return {
            "passed":     cr.passed,
            "violations": violations,
        }, 200

    def _handle_learn(self, data: dict) -> tuple[dict, int]:
        """
        POST /v1/learn
        Body: { "history": [ { CallRecord dict }, ... ] }
        """
        from ystar import learn, CallRecord
        history_raw = data.get("history", [])
        if not isinstance(history_raw, list):
            return {"error": "'history' must be a list"}, 400

        history = [CallRecord.from_dict(r) for r in history_raw]
        result  = learn(history)

        additions = []
        for dim, values in vars(result.contract_additions).items():
            if values and not dim.startswith("_") and dim != "name" and dim != "hash":
                additions.append({"dimension": dim, "values": values
                                  if not isinstance(values, dict)
                                  else values})

        return {
            "contract_additions":  additions,
            "rules_added":         len(additions),
            "incidents":           len(result.incidents),
            "candidates":          len(result.candidates),
            "diagnosis":           result.diagnosis,
            "quality_score":       result.quality.quality_score if result.quality else None,
            "fp_tolerance":        (result.objective.fp_tolerance
                                    if result.objective else None),
        }, 200

    def _handle_delegation_validate(self, data: dict) -> tuple[dict, int]:
        """
        POST /v1/delegation/validate
        Body: { "chain": [ { DelegationContract dict }, ... ] }
        """
        from ystar import DelegationChain, DelegationContract

        links_raw = data.get("chain", [])
        if not isinstance(links_raw, list):
            return {"error": "'chain' must be a list"}, 400

        chain = DelegationChain()
        for link_d in links_raw:
            chain.append(DelegationContract.from_dict(link_d))

        errors = chain.validate()
        return {
            "valid":          len(errors) == 0,
            "errors":         errors,
            "depth":          chain.depth,
            "origin":         chain.origin,
            "principal":      chain.origin,
            "terminal_actor": chain.terminal_actor,
            "terminal":       chain.terminal_actor,
        }, 200


# ── Server startup ────────────────────────────────────────────────────────────
    # ── Builder UI ────────────────────────────────────────────────────────────
    def _send_builder_ui(self, rid: str) -> None:
        """Serve the Policy Builder HTML — zero-friction visual config interface."""
        import pathlib
        builder_path = pathlib.Path(__file__).parent / "policy-builder.html"
        if builder_path.exists():
            html = builder_path.read_bytes()
        else:
            html = (
                b"<html><body><h2>Y* Policy Builder</h2>"
                b"<p><code>policy-builder.html</code> not found. "
                b"Reinstall: <code>pip install --upgrade ystar</code></p>"
                b"<p>Or use the Python API: "
                b"<code>from ystar import Policy, from_template</code></p>"
                b"</body></html>"
            )
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html)))
        self.send_header("X-Request-ID", rid)
        self.end_headers()
        self.wfile.write(html)

    # ── /v1/from-template ─────────────────────────────────────────────────────
    def _handle_from_template(self, data: dict) -> tuple[dict, int]:
        """
        Fill-in-the-blanks check endpoint — bridges HTTP and Python template API.

        Accepts friendly template keys (same as from_template() in Python) and
        runs a check against the provided params. No contract schema needed.

        Body::

            {
                "template": {
                    "can_write_to":  ["./workspace/dev/"],
                    "cannot_touch":  [".env", "production"],
                    "amount_limit":  10000,
                    "amount_min":    1
                },
                "params": {
                    "file_path": "./workspace/dev/main.py",
                    "amount": 500
                }
            }

        Returns same shape as /v1/check.
        """
        from .template import from_template as _ft
        tpl    = data.get("template")
        params = data.get("params", {})
        result_val = data.get("result", {})

        if not isinstance(tpl, dict):
            return {"error": "Missing or invalid 'template' (must be dict)"}, 400

        template_result = _ft(tpl)
        contract = template_result.contract
        cr = check(params, result_val, contract)

        viols = [
            {"dimension": v.dimension, "field": v.field,
             "message": v.message, "severity": v.severity}
            for v in cr.violations
            if v.dimension != "phantom_variable"
        ]
        return {
            "passed":     len(viols) == 0,
            "violations": viols,
            "summary":    cr.summary() if hasattr(cr, "summary") else (
                "ok" if not viols else viols[0]["message"]
            ),
        }, 200


def _make_server(host: str, port: int) -> HTTPServer:
    server = HTTPServer((host, port), YStarHandler)
    server.timeout = _config["timeout"]
    return server


def main():
    parser = argparse.ArgumentParser(description="Y* Check Service")
    parser.add_argument("--host",       default="127.0.0.1",
                        help="Bind address (default: 127.0.0.1)")
    parser.add_argument("--port",       default=8421, type=int,
                        help="Port (default: 8421)")
    parser.add_argument("--api-key",    default=None,
                        help="Required X-Api-Key value; omit to disable auth")
    parser.add_argument("--no-auth",    action="store_true",
                        help="Disable API-key auth (development only)")
    parser.add_argument("--max-body",   default=1 << 20, type=int,
                        help="Max request body bytes (default: 1 MB)")
    parser.add_argument("--cors-origin",default="*",
                        help="Access-Control-Allow-Origin (default: *)")
    parser.add_argument("--log-level",  default="INFO",
                        choices=["DEBUG","INFO","WARNING","ERROR"])
    args = parser.parse_args()

    _setup_logging(args.log_level)

    _config["api_key"]     = None if args.no_auth else args.api_key
    _config["max_body"]    = args.max_body
    _config["cors_origin"] = args.cors_origin

    server = _make_server(args.host, args.port)

    _log.info(json.dumps({
        "event":   "startup",
        "host":    args.host,
        "port":    args.port,
        "auth":    "disabled" if _config["api_key"] is None else "api-key",
        "version": YSTAR_VERSION,
    }))

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        _log.info(json.dumps({"event": "shutdown"}))
        server.server_close()


if __name__ == "__main__":
    main()
