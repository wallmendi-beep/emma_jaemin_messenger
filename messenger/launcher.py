"""Launch only the local courier HTTP server. Workers must poll separately."""
import argparse
import threading
import webbrowser
from pathlib import Path
from .server import DEFAULT_DB, build_server


def build_runtime(db_path=DEFAULT_DB, host='127.0.0.1', port=8765):
    return build_server(host, port, Path(db_path))


def main():
    parser = argparse.ArgumentParser(description='Local memo courier (no AI spawning)')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--db', type=Path, default=DEFAULT_DB)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    server = build_runtime(args.db, args.host, args.port)
    url = f'http://127.0.0.1:{server.server_port}'
    print(f'Memo courier: {url}\nExisting workers must integrate polling; no live session injection.', flush=True)
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
