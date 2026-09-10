"""Real Edge interaction regression. Temporary DB/port; no agents/live writes.
Run with Python + playwright installed, or private qa-deps on sys.path.
"""
import sys, json, tempfile, threading, hashlib, traceback
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'data/dashboard-verification/qa-deps'))
from playwright.sync_api import sync_playwright, expect
from messenger.courier import CourierStore
from messenger.server import build_server
OUT = ROOT / 'data/dashboard-verification'
OUT.mkdir(exist_ok=True)
checks = {}
def check(name, condition, detail=None):
    checks[name] = {'passed': bool(condition), 'detail': detail}
    print(name, bool(condition), detail)

with tempfile.TemporaryDirectory(prefix='interactive-qa-') as tmp:
    store = CourierStore(Path(tmp) / 'qa.db')
    p2 = store.create_project('QA second project', tmp)['id']
    store.create_task(p2, 'QA-001', 'Other project only')
    p3 = store.create_project('QA stale-selection project', tmp)['id']
    store.create_task(p3, 'STALE-A', 'Visible stale form')
    store.create_task(p3, 'STALE-B', 'Delayed detail target')
    p4 = store.create_project('QA request-order project', tmp)['id']
    store.create_task(p4, 'ORDER-1', 'Same task response order')
    p5 = store.create_project('QA submit-race project', tmp)['id']
    store.create_task(p5, 'ABA-A', 'Submit origin')
    store.create_task(p5, 'ABA-B', 'Navigation target')
    server = build_server(port=0, db_path=store.path)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless=True)
            page = browser.new_page(viewport={'width': 1500, 'height': 1100})
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{server.server_port}')
            expect(page.locator('#progress-label')).to_contain_text('전체 0')
            for key in ['QA-001', 'QA-002']:
                page.locator('#task-id').fill(key)
                page.locator('#task-title').fill('Interactive '+key)
                page.locator('#task-description').fill('Synthetic scope; no AI execution')
                page.locator('#task-form button').click()
                expect(page.locator('#task-detail')).to_contain_text(key)
            check('create_readback', [t['task_id'] for t in store.tasks(1)] == ['QA-001','QA-002'])
            page.locator('[data-task="QA-002"]').click()
            expect(page.locator('#task-detail')).to_contain_text('Interactive QA-002')
            store.transition_task(1,'QA-002','in_progress',1,note='External QA transition')
            page.locator('#refresh').click()
            expect(page.locator('#task-state')).to_have_value('in_progress')
            page.locator('#transition-form button').click()
            expect(page.locator('#error')).to_contain_text('state unchanged')
            check('untouched_selection_cannot_revert', store.task_detail(1,'QA-002')['state']=='in_progress')
            page.locator('#error').evaluate("el=>el.textContent=''")
            page.locator('[data-task="QA-001"]').click()
            expect(page.locator('#task-detail')).to_contain_text('Interactive QA-001')
            page.locator('#task-state').select_option('done')
            page.wait_for_timeout(2300)
            check('poll_preserves_pending_selection', page.locator('#task-state').input_value() == 'done')
            page.locator('#task-note').fill('QA manual completion')
            page.locator('#transition-form button').click()
            expect(page.locator('#progress-label')).to_contain_text('완료 1 / 전체 2')
            check('manual_provenance', store.task_detail(1,'QA-001')['history'][-1]['provenance']=='manual')
            check('real_counts', page.locator('.task-card').count()==2 and page.locator('.lane').count()==5 and page.locator('#progress').get_attribute('value')=='1')
            page.locator('#project').select_option(str(p2))
            expect(page.locator('#progress-label')).to_contain_text('전체 1')
            page.locator('[data-task="QA-001"]').click()
            expect(page.locator('#task-detail')).to_contain_text('Other project only')
            check('project_id_isolation', store.task_detail(p2,'QA-001')['state']=='todo' and page.locator('.task-card').count()==1)
            path = Path(tmp)/'memo.md'; path.write_bytes(b'QA fixture')
            n=store.notify(p2,'emma',str(path),hashlib.sha256(path.read_bytes()).hexdigest(),task_id='QA-001')
            c=store.claim(p2,'emma','synthetic-QA-worker')
            t=store.transition_task(p2,'QA-001','review',1,notification_id=n['id'],claim_token=c['claim_token'])
            page.locator('#refresh').click()
            expect(page.locator('#task-history')).to_contain_text('synthetic-QA-worker')
            check('worker_provenance_rendered', '작업자 보고' in page.locator('#task-history').inner_text() and t['history'][-1]['provenance']=='worker_reported')
            try:
                store.transition_task(1,'QA-001','review',2,notification_id=n['id'],claim_token=c['claim_token'])
                rejected=False
            except ValueError: rejected=True
            check('cross_project_claim_rejected', rejected)
            splitter=page.locator('#splitter'); box=splitter.bounding_box()
            page.mouse.move(box['x']+6,box['y']+30); page.mouse.down(); page.mouse.move(box['x']+76,box['y']+30,steps=8); page.mouse.up()
            width=splitter.get_attribute('aria-valuenow')
            check('pointer_resize', float(width)>400, width)
            splitter.focus(); splitter.press('ArrowLeft')
            width=splitter.get_attribute('aria-valuenow')
            board=page.locator('#kanban'); board.scroll_into_view_if_needed(); b=board.bounding_box()
            page.mouse.move(b['x']+b['width']-3,b['y']+b['height']-3);page.mouse.down();page.mouse.move(b['x']+b['width']-3,b['y']+b['height']+97,steps=10);page.mouse.up()
            page.wait_for_timeout(200)
            before=board.bounding_box()['height']
            check('vertical_drag',before>b['height']+50, {'before':b['height'],'after':before})
            page.screenshot(path=str(OUT/'interactive-desktop.png'),full_page=True)
            heights=[before]
            for _ in range(2):
                page.reload();expect(page.locator('#progress-label')).to_contain_text('전체 2');page.wait_for_timeout(150)
                heights.append(board.bounding_box()['height'])
            check('width_persistence',splitter.get_attribute('aria-valuenow')==width)
            check('height_persistence_no_drift',max(heights)-min(heights)<2,heights)
            page.locator('#project').select_option(str(p3))
            expect(page.locator('#progress-label')).to_contain_text('전체 2')
            page.locator('[data-task="STALE-A"]').click()
            expect(page.locator('#task-detail')).to_contain_text('Visible stale form')
            page.locator('#task-state').select_option('done')
            delayed = []
            def delay_stale_b_detail(route):
                if not delayed:
                    delayed.append(route)
                else:
                    route.continue_()
            page.route(f'**/api/tasks/detail?project_id={p3}&task_id=STALE-B', delay_stale_b_detail)
            page.locator('[data-task="STALE-B"]').click()
            page.wait_for_timeout(100)
            check('stale_form_invalidated_immediately',
                  len(delayed) == 1 and page.locator('#transition-form').is_hidden()
                  and page.locator('#transition-form button').is_disabled())
            page.locator('#transition-form').evaluate('form => form.requestSubmit()')
            page.wait_for_timeout(150)
            check('stale_form_cannot_submit_against_new_selection',
                  store.task_detail(p3, 'STALE-B')['state'] == 'todo',
                  store.task_detail(p3, 'STALE-B')['state'])
            delayed[0].continue_()
            page.unroute(f'**/api/tasks/detail?project_id={p3}&task_id=STALE-B', delay_stale_b_detail)
            expect(page.locator('#task-detail')).to_contain_text('Delayed detail target')
            page.locator('#error').evaluate("el=>el.textContent='' ")
            page.locator('#project').select_option(str(p4))
            page.locator('[data-task="ORDER-1"]').click()
            expect(page.locator('#task-detail')).to_contain_text('수정본 1')
            stale_detail = store.task_detail(p4, 'ORDER-1')
            held_details = []
            detail_pattern = f'**/api/tasks/detail?project_id={p4}&task_id=ORDER-1'
            page.route(detail_pattern, lambda route: held_details.append(route))
            page.locator('#refresh').click()
            page.wait_for_timeout(100)
            store.transition_task(p4, 'ORDER-1', 'in_progress', 1)
            fresh_detail = store.task_detail(p4, 'ORDER-1')
            page.locator('#refresh').click()
            page.wait_for_timeout(100)
            check('same_task_two_detail_requests_held', len(held_details) == 2, len(held_details))
            held_details[1].fulfill(status=200, content_type='application/json', body=json.dumps(fresh_detail))
            page.wait_for_timeout(100)
            held_details[0].fulfill(status=200, content_type='application/json', body=json.dumps(stale_detail))
            page.unroute(detail_pattern)
            page.wait_for_timeout(150)
            check('older_same_task_response_ignored',
                  '수정본 2' in page.locator('#task-detail').inner_text()
                  and page.locator('#task-state').input_value() == 'in_progress',
                  page.locator('#task-detail').inner_text())
            page.locator('#project').select_option(str(p5))
            page.locator('[data-task="ABA-A"]').click()
            expect(page.locator('#task-detail')).to_contain_text('Submit origin')
            page.locator('#task-state').select_option('done')
            page.locator('#task-note').fill('first request')
            held_posts = []
            page.route('**/api/tasks/transition', lambda route: held_posts.append(route))
            page.locator('#transition-form button').click()
            page.wait_for_timeout(100)
            page.locator('#transition-form').evaluate('form => form.requestSubmit()')
            page.wait_for_timeout(100)
            check('duplicate_transition_blocked',
                  len(held_posts) == 1 and page.locator('#transition-form button').is_disabled(),
                  len(held_posts))
            for route in held_posts:
                route.abort()
            page.unroute('**/api/tasks/transition')
            page.wait_for_timeout(150)
            page.locator('#error').evaluate("el=>el.textContent='' ")
            page.locator('#task-state').select_option('done')
            page.locator('#task-note').fill('old completion')
            aba_post = []
            page.route('**/api/tasks/transition', lambda route: aba_post.append(route))
            page.locator('#transition-form button').click()
            page.wait_for_timeout(100)
            page.locator('[data-task="ABA-B"]').click()
            expect(page.locator('#task-detail')).to_contain_text('Navigation target')
            page.locator('[data-task="ABA-A"]').click()
            expect(page.locator('#task-detail')).to_contain_text('Submit origin')
            page.locator('#task-state').select_option('review')
            page.locator('#task-note').fill('new pending edit')
            aba_post[0].continue_()
            page.unroute('**/api/tasks/transition')
            page.wait_for_timeout(300)
            check('aba_completion_preserves_new_edit',
                  page.locator('#task-note').input_value() == 'new pending edit'
                  and page.locator('#task-state').input_value() == 'review',
                  {'note': page.locator('#task-note').input_value(),
                   'state': page.locator('#task-state').input_value()})
            page.set_viewport_size({'width':390,'height':844})
            page.screenshot(path=str(OUT/'interactive-mobile.png'),full_page=True)
            check('mobile_no_body_overflow',page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
            check('no_javascript_errors',not errors,errors)
            check('no_ui_error',not page.locator('#error').inner_text(),page.locator('#error').inner_text())
            browser.close()
    except Exception:
        checks['exception']={'passed':False,'detail':traceback.format_exc()}
        raise
    finally:
        server.shutdown();server.server_close();thread.join()
        (OUT/'interactive-checks.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2),encoding='utf-8')
assert all(v['passed'] for v in checks.values()), 'Interactive regression failed; see evidence JSON'
