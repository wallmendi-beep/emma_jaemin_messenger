from __future__ import annotations

import argparse
import threading
import time
import webbrowser
from pathlib import Path

from .bridge import AgentCommandRunner, CollaborationBridge
from .server import DEFAULT_DB, build_server
from .store import MessageStore


def build_runtime(db_path=DEFAULT_DB, host="127.0.0.1", port=8765, max_exchanges=6):
    db_path = Path(db_path)
    server = build_server(host, port, db_path)
    bridge = CollaborationBridge(
        MessageStore(db_path), AgentCommandRunner(), max_exchanges=max_exchanges
    )
    return server, bridge


def _bridge_watch(bridge, stop_event, interval=2.0):
    while not stop_event.is_set():
        bridge.drain()
        stop_event.wait(interval)


def main():
    parser = argparse.ArgumentParser(description="Start the private collaboration room")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    server, bridge = build_runtime(args.db, args.host, args.port)
    stop = threading.Event()
    worker = threading.Thread(
        target=_bridge_watch, args=(bridge, stop), name="emma-jaemin-bridge", daemon=True
    )
    worker.start()
    url = f"http://{args.host}:{server.server_port}"
    print(f"Private messenger: {url}", flush=True)
    print("Consultation-only mode. Press Ctrl+C to stop.", flush=True)
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.shutdown()
        server.server_close()
        worker.join(timeout=3)


if __name__ == "__main__":
    main()
