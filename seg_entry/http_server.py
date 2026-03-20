from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .errors import SegEntryError
from .gpu import build_gpu_status_payload
from .service import SegmentationService


class SegEntryRequestHandler(BaseHTTPRequestHandler):
    service = SegmentationService()

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._send_json(HTTPStatus.OK, {"status": "ok"})
            return

        if self.path == "/models":
            self._send_json(HTTPStatus.OK, {"models": self.service.describe_models()})
            return

        if self.path == "/runtime/gpus":
            try:
                payload = build_gpu_status_payload()
                self._send_json(HTTPStatus.OK, payload)
            except SegEntryError as exc:
                self._send_json(exc.status, {"status": "failed", "error": exc.to_dict()})
            return

        self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/segmentations":
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
            return

        content_length = int(self.headers.get("Content-Length", "0") or "0")
        raw_body = self.rfile.read(content_length)
        try:
            payload = json.loads(raw_body.decode("utf-8") or "{}")
        except json.JSONDecodeError as exc:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {"error": "Invalid JSON body", "details": str(exc)},
            )
            return

        result = self.service.execute(payload)
        self._send_json(result.status_code, result.response.to_dict())

    def log_message(self, fmt: str, *args) -> None:
        return

    def _send_json(self, status_code: int, payload: dict) -> None:
        encoded = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def run_server(host: str = "0.0.0.0", port: int = 8010) -> None:
    server = ThreadingHTTPServer((host, port), SegEntryRequestHandler)
    try:
        server.serve_forever()
    finally:
        server.server_close()
