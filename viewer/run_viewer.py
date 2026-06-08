#!/usr/bin/env python3
"""
Build papers_data.json from Excel and serve static viewer.

Usage:
  python3 run_viewer.py
"""

from __future__ import annotations

import argparse
import errno
import http.server
import json
import socketserver
from pathlib import Path
import socket
import sys

from build_data import main as build_data_main

PORT = 8765
HOST = "0.0.0.0"
VIEWER_DIR = Path(__file__).resolve().parent
FAVORITES_FILE = VIEWER_DIR / "favorites.json"


def get_local_ip() -> str:
    """Best-effort local IP for LAN hint."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def load_favorites() -> list[str]:
    if not FAVORITES_FILE.exists():
        return []
    try:
        data = json.loads(FAVORITES_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, list):
        return []
    result = []
    seen = set()
    for item in data:
        text = str(item).strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def save_favorites(favorites: list[str]) -> None:
    FAVORITES_FILE.write_text(
        json.dumps(favorites, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve local/LAN viewer")
    parser.add_argument("--host", default=HOST, help="Bind host, default: 0.0.0.0")
    parser.add_argument("--port", type=int, default=PORT, help="Bind port, default: 8765")
    args = parser.parse_args()

    build_data_main()

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(VIEWER_DIR), **kwargs)

        def _send_json(self, payload: object, status: int = 200) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if self.path == "/api/favorites":
                self._send_json({"favorites": load_favorites()})
                return
            super().do_GET()

        def do_POST(self) -> None:
            if self.path != "/api/favorites":
                self.send_error(404, "Not Found")
                return

            content_length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(content_length)
            try:
                payload = json.loads(raw.decode("utf-8") or "{}")
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._send_json({"error": "Invalid JSON"}, status=400)
                return

            favorites = payload.get("favorites")
            if not isinstance(favorites, list):
                self._send_json({"error": "favorites must be a list"}, status=400)
                return

            cleaned = []
            seen = set()
            for item in favorites:
                text = str(item).strip()
                if text and text not in seen:
                    seen.add(text)
                    cleaned.append(text)

            save_favorites(cleaned)
            self._send_json({"favorites": cleaned})

    class Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True

    try:
        with Server((args.host, args.port), Handler) as httpd:
            local_ip = get_local_ip()
            print(f"[OK] Viewer running at http://127.0.0.1:{args.port}")
            print(f"[OK] LAN access: http://{local_ip}:{args.port}")
            print(f"[OK] Favorites file: {FAVORITES_FILE}")
            print("[INFO] Press Ctrl+C to stop")
            httpd.serve_forever()
    except OSError as e:
        if e.errno == errno.EADDRINUSE:
            print(f"[ERROR] Port {args.port} is already in use.")
            print("[HINT] Stop existing process or start with another port, e.g.")
            print("       python3 run_viewer.py --port 8766")
            sys.exit(1)
        raise


if __name__ == "__main__":
    main()
