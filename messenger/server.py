from __future__ import annotations

import argparse
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .store import MessageStore


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = PROJECT_ROOT / "data" / "messages.db"
DEFAULT_INDEX = PROJECT_ROOT / "static" / "index.html"


def _handler_factory(store: MessageStore, index_path: Path):
    class MessengerHandler(BaseHTTPRequestHandler):
        server_version = "EmmaJaeminMessenger/0.1"

        def log_message(self, fmt, *args):
            return

        def _send_json(self, payload, status=HTTPStatus.OK):
            encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(encoded)

        def _send_html(self):
            if not index_path.exists():
                self.send_error(HTTPStatus.NOT_FOUND, "UI not installed")
                return
            encoded = index_path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == "/api/health":
                projects = store.list_projects()
                self._send_json({
                    "status": "ok",
                    "paused": any(bool(project["paused"]) for project in projects),
                    "project_count": len(projects),
                })
                return
            if parsed.path == "/api/projects":
                self._send_json({"projects": store.list_projects()})
                return
            if parsed.path == "/api/rules":
                query = parse_qs(parsed.query)
                try:
                    project_id = int(query.get("project_id", ["1"])[0])
                    store.get_project(project_id)
                except ValueError as exc:
                    self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
                    return
                self._send_json({
                    "global_rules": store.list_global_rules(),
                    "project_rules": store.list_project_rules(project_id),
                })
                return
            if parsed.path == "/api/messages":
                query = parse_qs(parsed.query)
                try:
                    after = int(query.get("after", ["0"])[0])
                    project_id = int(query.get("project_id", ["1"])[0])
                except ValueError:
                    self._send_json(
                        {"error": "after and project_id must be integers"},
                        HTTPStatus.BAD_REQUEST,
                    )
                    return
                try:
                    project = store.get_project(project_id)
                except ValueError as exc:
                    self._send_json({"error": str(exc)}, HTTPStatus.NOT_FOUND)
                    return
                self._send_json({
                    "project": project,
                    "messages": store.list_messages(after_id=after, project_id=project_id),
                    "paused": store.is_paused(project_id),
                })
                return
            if parsed.path in {"/", "/index.html"}:
                self._send_html()
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def _origin_allowed(self):
            origin = self.headers.get("Origin")
            if not origin:
                return True
            parsed_origin = urlparse(origin)
            return parsed_origin.scheme == "http" and parsed_origin.hostname in {
                "127.0.0.1", "localhost", "::1"
            }

        def do_POST(self):
            parsed = urlparse(self.path)
            is_rule_approval = (
                parsed.path.startswith("/api/rules/")
                and parsed.path.endswith("/approve")
            )
            if parsed.path not in {"/api/messages", "/api/projects", "/api/rules"} and not is_rule_approval:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            if not self._origin_allowed():
                self._send_json({"error": "foreign origin rejected"}, HTTPStatus.FORBIDDEN)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 65536:
                    raise ValueError("invalid body length")
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                if is_rule_approval:
                    parts = parsed.path.strip("/").split("/")
                    if len(parts) != 4 or parts[:2] != ["api", "rules"]:
                        raise ValueError("invalid rule approval path")
                    result = store.approve_project_rule(int(parts[2]))
                elif parsed.path == "/api/projects":
                    result = store.create_project(
                        payload.get("name", ""),
                        payload.get("workspace", ""),
                        payload.get("hermes_session_id", ""),
                        payload.get("jaemin_conversation_id", ""),
                    )
                elif parsed.path == "/api/rules":
                    result = store.add_project_rule(
                        payload.get("project_id", 1),
                        payload.get("text", ""),
                        source="user",
                        status="active",
                    )
                else:
                    result = store.post(
                        payload.get("sender", ""),
                        payload.get("recipient", ""),
                        payload.get("type", ""),
                        payload.get("body", ""),
                        payload.get("reply_to"),
                        payload.get("project_id", 1),
                    )
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
                return
            self._send_json(result, HTTPStatus.CREATED)

    return MessengerHandler


def build_server(host="127.0.0.1", port=8765, db_path=DEFAULT_DB, index_path=DEFAULT_INDEX):
    store = MessageStore(db_path)
    return ThreadingHTTPServer((host, int(port)), _handler_factory(store, Path(index_path)))


def main():
    parser = argparse.ArgumentParser(description="Local Emma-Jaemin messenger")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args()
    server = build_server(args.host, args.port, args.db)
    print(f"Messenger: http://{args.host}:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
