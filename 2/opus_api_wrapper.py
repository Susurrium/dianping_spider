#!/usr/bin/env python3
"""Anthropic-format API wrapper around `kiro-cli chat` (claude-opus-4.8).

Run:   python3 opus_api_wrapper.py
Use:   base_url = http://127.0.0.1:8787   api_key = $WRAPPER_API_KEY (default: sk-local)

Exposes POST /v1/messages (streaming + non-streaming) and GET /v1/models.
"""
import json, os, re, subprocess, time, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = os.environ.get("WRAPPER_HOST", "127.0.0.1")   # keep on localhost; 0.0.0.0 would expose the CLI
PORT = int(os.environ.get("WRAPPER_PORT", "8787"))
API_KEY = os.environ.get("WRAPPER_API_KEY", "sk-local")
DEFAULT_MODEL = os.environ.get("WRAPPER_MODEL", "claude-opus-4.8")
KNOWN = {"auto", "claude-opus-4.8", "claude-opus-4.7", "claude-opus-4.6", "claude-sonnet-4.6",
         "claude-opus-4.5", "claude-sonnet-4.5", "claude-sonnet-4", "claude-haiku-4.5"}

_ANSI = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")


def _blocks_to_text(content):
    if isinstance(content, str):
        return content
    return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")


def build_prompt(body):
    parts = []
    sys = body.get("system")
    if sys:
        parts.append("System:\n" + _blocks_to_text(sys))
    for m in body.get("messages", []):
        role = "Human" if m.get("role") == "user" else "Assistant"
        parts.append(f"{role}:\n{_blocks_to_text(m.get('content', ''))}")
    parts.append("Assistant:")
    return "\n\n".join(parts)


def clean_output(stdout):
    # In piped mode the answer is the whole stdout (with ANSI + a leading "> " marker);
    # warnings and the credits footer are emitted on stderr, so we ignore stderr.
    text = _ANSI.sub("", stdout)
    return re.sub(r"^\s*>\s?", "", text).strip()


def call_cli(prompt, model):
    model = model if model in KNOWN else DEFAULT_MODEL
    proc = subprocess.run(
        ["kiro-cli", "chat", "--no-interactive", "--trust-tools=", "--model", model],
        input=prompt, capture_output=True, text=True, timeout=600,
    )
    return clean_output(proc.stdout)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def _json(self, code, obj):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _auth_ok(self):
        key = self.headers.get("x-api-key") or self.headers.get("Authorization", "").removeprefix("Bearer ")
        return key == API_KEY

    def _path(self):
        return self.path.split("?", 1)[0].rstrip("/")

    def do_GET(self):
        if self._path() == "/v1/models":
            self._json(200, {"data": [{"type": "model", "id": m} for m in sorted(KNOWN)]})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        if self._path() != "/v1/messages":
            return self._json(404, {"type": "error", "error": {"type": "not_found_error", "message": "unknown path"}})
        if not self._auth_ok():
            return self._json(401, {"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}})
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0) or 0)) or b"{}")
        except json.JSONDecodeError:
            return self._json(400, {"type": "error", "error": {"type": "invalid_request_error", "message": "bad JSON"}})

        model = body.get("model", DEFAULT_MODEL)
        prompt = build_prompt(body)
        try:
            answer = call_cli(prompt, model)
        except subprocess.TimeoutExpired:
            return self._json(504, {"type": "error", "error": {"type": "timeout", "message": "kiro-cli timed out"}})
        except Exception as e:  # noqa: BLE001
            return self._json(500, {"type": "error", "error": {"type": "api_error", "message": str(e)}})

        msg_id = "msg_" + uuid.uuid4().hex
        usage = {"input_tokens": max(1, len(prompt) // 4), "output_tokens": max(1, len(answer) // 4)}

        if body.get("stream"):
            self._stream(msg_id, model, answer, usage)
        else:
            self._json(200, {
                "id": msg_id, "type": "message", "role": "assistant", "model": model,
                "content": [{"type": "text", "text": answer}],
                "stop_reason": "end_turn", "stop_sequence": None, "usage": usage,
            })

    def _sse(self, event, data):
        self.wfile.write(f"event: {event}\ndata: {json.dumps(data)}\n\n".encode())
        self.wfile.flush()

    def _stream(self, msg_id, model, answer, usage):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self._sse("message_start", {"type": "message_start", "message": {
            "id": msg_id, "type": "message", "role": "assistant", "model": model,
            "content": [], "stop_reason": None, "stop_sequence": None,
            "usage": {"input_tokens": usage["input_tokens"], "output_tokens": 0}}})
        self._sse("content_block_start", {"type": "content_block_start", "index": 0,
                                          "content_block": {"type": "text", "text": ""}})
        self._sse("content_block_delta", {"type": "content_block_delta", "index": 0,
                                          "delta": {"type": "text_delta", "text": answer}})
        self._sse("content_block_stop", {"type": "content_block_stop", "index": 0})
        self._sse("message_delta", {"type": "message_delta",
                                    "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                                    "usage": {"output_tokens": usage["output_tokens"]}})
        self._sse("message_stop", {"type": "message_stop"})


if __name__ == "__main__":
    print(f"Anthropic-compatible wrapper -> claude-opus-4.8 via kiro-cli")
    print(f"  base_url: http://{HOST}:{PORT}    (Anthropic: http://{HOST}:{PORT}/v1)")
    print(f"  api_key : {API_KEY}   (set WRAPPER_API_KEY to change)")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
