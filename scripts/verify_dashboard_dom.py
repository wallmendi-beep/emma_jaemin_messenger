"""Bounded Edge DOM smoke test; isolated database and browser profile."""
import pathlib, tempfile, threading, subprocess, json
from messenger.server import build_server
from messenger.courier import CourierStore
root = pathlib.Path(__file__).resolve().parents[1]
evidence = root / 'data/dashboard-verification'
evidence.mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(prefix='dashboard-dom-') as tmp:
    db = pathlib.Path(tmp) / 'test.db'
    store = CourierStore(db)
    store.create_task(1, 'DOM-001', 'Browser fixture')
    server = build_server(port=0, db_path=db)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = subprocess.run(['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', '--headless', '--disable-gpu', '--no-first-run', '--no-default-browser-check', '--user-data-dir='+str(pathlib.Path(tmp)/'browser'), '--virtual-time-budget=4000', '--dump-dom', f'http://127.0.0.1:{server.server_port}'], capture_output=True, timeout=25)
        dom = result.stdout.decode('utf-8', errors='replace')
        (evidence/'rendered-dom.html').write_text(dom, encoding='utf-8')
        checks = dict(rendered_task='data-task="DOM-001"' in dom, five_lanes=dom.count('class="lane"')==5, exact_count='완료 0 / 전체 1' in dom, unverified='자동 깨우기 미구현' in dom, no_error='<p id="error" role="alert"></p>' in dom)
        (evidence/'checks.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')
        print(json.dumps(checks)); assert all(checks.values()), 'DOM smoke failed'
    finally:
        server.shutdown(); server.server_close(); thread.join()
