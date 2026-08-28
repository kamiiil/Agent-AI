#!/usr/bin/env python3
"""Lekki webowy interfejs FitMentor bez dodatkowych zależności."""

from __future__ import annotations

import json
import mimetypes
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from body_tracking import get_body_measurements
from chat import DEFAULT_MODEL, SYSTEM_PROMPT, ask_fitmentor, load_api_key

BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "web"


class FitMentorHandler(BaseHTTPRequestHandler):
    server_version = "FitMentor/1.0"

    def _send_json(self, payload: object, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path) -> None:
        if not path.is_file() or WEB_DIR not in path.parents:
            self.send_error(404)
            return
        body = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/measurements":
            try:
                self._send_json(get_body_measurements(history_limit=12))
            except Exception as error:
                self._send_json({"error": str(error)}, 500)
            return

        relative = parsed.path.removeprefix("/") or "index.html"
        self._send_file(WEB_DIR / relative)

    def do_POST(self) -> None:  # noqa: N802
        if urlparse(self.path).path != "/api/chat":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length))
            prompt = str(payload.get("prompt", "")).strip()
            messages = payload.get("messages") or [{"role": "system", "content": SYSTEM_PROMPT}]
            if not prompt or not isinstance(messages, list):
                raise ValueError("Wiadomość nie może być pusta.")
            answer, tool_events = ask_fitmentor(
                load_api_key(),
                str(payload.get("model") or DEFAULT_MODEL),
                messages,
                prompt,
            )
            self._send_json({"answer": answer, "messages": messages, "tool_events": tool_events})
        except Exception as error:
            self._send_json({"error": str(error)}, 400)

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    host = os.getenv("FITMENTOR_HOST", "127.0.0.1")
    requested_port = int(os.getenv("FITMENTOR_PORT", "8000"))
    server = None
    for port in range(requested_port, requested_port + 11):
        try:
            server = ThreadingHTTPServer((host, port), FitMentorHandler)
            break
        except OSError as error:
            if error.errno != 98 or port == requested_port + 10:
                raise
    assert server is not None
    print(f"FitMentor GUI: http://{host}:{server.server_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nZamykanie GUI.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
