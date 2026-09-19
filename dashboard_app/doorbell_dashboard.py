"""Native Windows shell for the local Doorbell dashboard."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

DASHBOARD_URL = "http://127.0.0.1:8765"


def app_data_directory() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "DoorbellDashboard"


def saved_project_root() -> Path | None:
    config = app_data_directory() / "config.json"
    try:
        value = json.loads(config.read_text(encoding="utf-8")).get("project_root")
        return Path(value) if isinstance(value, str) and value else None
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def save_project_root(root: Path) -> None:
    directory = app_data_directory()
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "config.json").write_text(json.dumps({"project_root": str(root)}, ensure_ascii=False), encoding="utf-8")


def application_directory() -> Path:
    return Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent


def find_project_root() -> Path:
    configured_root = os.environ.get("DOORBELL_PROJECT_ROOT")
    candidates = [
        Path(configured_root) if configured_root else None,
        saved_project_root(),
        Path.home() / "emma-jaemin-messenger",
        application_directory(),
        *application_directory().parents,
    ]
    for directory in candidates:
        if directory and (directory / "messenger" / "server.py").is_file():
            return directory
    raise RuntimeError("메신저 프로젝트 폴더를 찾지 못했습니다. DOORBELL_PROJECT_ROOT를 프로젝트 폴더로 지정하세요.")


def dashboard_running() -> bool:
    try:
        with urlopen(f"{DASHBOARD_URL}/api/health", timeout=1) as response:
            return response.status == 200
    except (URLError, TimeoutError):
        return False


def start_server(root: Path) -> subprocess.Popen[bytes] | None:
    if dashboard_running():
        return None
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    python_executable = os.environ.get("DOORBELL_PYTHON", "python") if getattr(sys, "frozen", False) else sys.executable
    process = subprocess.Popen(
        [python_executable, "-m", "messenger.server", "--host", "127.0.0.1", "--port", "8765"],
        cwd=root, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )
    for _ in range(24):
        if dashboard_running():
            return process
        time.sleep(0.25)
    process.terminate()
    raise RuntimeError("대시보드 서버를 시작하지 못했습니다.")


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()
    root = find_project_root()
    if args.self_check:
        print(json.dumps({"project_root": str(root), "dashboard_running": dashboard_running()}, ensure_ascii=False))
        return 0

    owned_server = start_server(root)
    try:
        import webview
        window = webview.create_window("초인종 프로젝트 작업기록", DASHBOARD_URL, width=1500, height=980, min_size=(1000, 720))
        webview.start(gui="edgechromium")
    finally:
        if owned_server and owned_server.poll() is None:
            owned_server.terminate()
            try:
                owned_server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                owned_server.kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
