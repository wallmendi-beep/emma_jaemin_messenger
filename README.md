# 엠마 · 재민이 메모 우편함

## 작업 대시보드 (tasks-v1)

프로젝트 ID와 별도의 작업 ID, 병렬 칸반, 수동/작업자 보고 이력, 완료 수/전체 수,
크기 조절 패널을 제공합니다. 작업 등록은 AI 실행이 아닙니다.
API·마이그레이션·기존 작업자 연동·제약은 [대시보드 통합 문서](docs/dashboard-integration.md)를 참고하세요.

기존 작업자가 공유 Markdown 파일을 작성하고, 상대 작업자가 그 파일의 **정확한 버전**을 읽도록 알리는 로컬 전달 서버입니다. 알림·수신권·읽음 확인·결과 메모 연결은 SQLite에 보존됩니다. 서버는 메모를 작성하거나 AI를 실행하지 않습니다.

> **구현된 것은 worker polling 프로토콜이지 기존 Hermes/Antigravity 세션의 자동 깨우기가 아닙니다.**
> `--worker`는 소유자 표시용 문자열이며 세션 연결 명령이 아닙니다. 저장된 Hermes 세션 ID/Antigravity 대화 ID도 자동 연결되지 않습니다. 기존 세션이 아래 adapter를 직접 호출하거나, 해당 런타임에서 승인된 polling/event 연동을 별도로 구현해야 합니다. 우편함에 등록만 하면 상대 AI가 자동으로 일한다는 뜻이 아닙니다.

## 실행과 종료

Python 3.10 이상, 표준 라이브러리만 필요합니다. Hermes/Antigravity CLI는 서버 실행에 필요하지 않습니다.

- 저장소에서 `Start Messenger.bat` 또는 `python -m messenger.launcher` 실행.
- UI: `http://127.0.0.1:8765`. 종료: 실행 창에서 `Ctrl+C`.
- 브라우저 없이: `python -m messenger.launcher --no-browser`.
- 별도 시험 DB/포트: `python -m messenger.server --db data/test.db --port 8877`.
- `GET /api/health`: `status=ok`, `mode=memo-courier-v1`, `agent_spawning=false` 확인.
- 구형 `python -m messenger.bridge`는 안내문과 함께 종료합니다. 새 상담용 AI를 띄우던 경로는 폐기했습니다.

구형 서버가 실행 중이면 새 코드가 자동 적용되지 않습니다. 관리자가 기존 서버/브리지를 정상 종료하고 개인 DB를 백업한 뒤 새 서버를 실행해야 합니다. **이번 검증에서는 운영 서버를 재시작하지 않았습니다.**

## 프로젝트와 메모 작성

1. UI에서 프로젝트 이름과 **공유 작업 폴더의 절대 경로**를 등록합니다. 사용자 홈 전체 대신 승인된 좁은 폴더를 권장합니다.
2. 작성자는 그 폴더 안에 UTF-8 `.md` 파일을 직접 작성합니다. 역할·요청·허용 경로·금지 작업·완료 조건·승인이 필요한 사항을 명시합니다.
3. 파일 바이트의 SHA-256을 계산합니다. 알림은 프로젝트 ID, 수신자(`emma`/`jaemin`/`user`), 경로, 소문자 64자리 해시를 사용합니다.
4. UI 또는 worker adapter의 `notify`로 등록합니다. 경로는 프로젝트 상대 경로 또는 내부 파일의 절대 경로입니다. 기존 파일만 허용하며, 확장자 `.md`, 최대 4 MiB, 실제 해시 일치를 검사합니다. 폴더 밖 경로/심볼릭 링크 대상은 거절합니다.

해시 계산 예시(저장소에서 실행, 파일 경로는 실제 승인된 파일로 교체):

```bash
python -c "import hashlib; from pathlib import Path; print(hashlib.sha256(Path('C:/Work/Shared/memos/request-v1.md').read_bytes()).hexdigest())"
```

전달 후 파일을 덮어쓰지 말고 `request-v1.md`, `request-v2.md`처럼 버전별 파일을 보존하세요. 서버는 내용을 스냅샷으로 저장하지 않습니다. 원본이 바뀌거나 삭제되면 과거 알림 버전을 읽을 수 없습니다. 같은 프로젝트·수신자·정규화 경로·해시 재등록은 같은 알림을 반환합니다.

## 기존 작업자에서 CLI adapter 사용

아래는 **Git Bash** 예시입니다. `2`는 예시 프로젝트 ID이며 UI/API에서 확인한 실제 정수 ID로 바꾸세요. 모든 명령은 저장소 루트에서 실행합니다. `data/`는 개인 데이터 폴더이고 Git에서 제외됩니다.

```bash
# 작성자가 실제 메모를 저장한 후, 수신자 emma의 우편함에 등록
python -m messenger.worker --project 2 --recipient emma --worker existing-author notify --memo C:/Work/Shared/memos/request-v1.md --hash <SHA256>

# 기존 emma 작업자가 명시적으로 조회하여 수신권 확보
python -m messenger.worker --project 2 --recipient emma --worker existing-emma claim --lease 120 > data/emma-claim.json

# claim 결과가 null이면 대기 항목 없음. 아래 작업은 실행하지 않고 나중에 다시 claim.
# JSON 객체라면 파일을 실제로 읽고 해시 확인 후 read ACK 전송
python -m messenger.worker --project 2 --recipient emma --worker existing-emma read --claim-file data/emma-claim.json

# 오래 걸리는 작업은 임대가 끝나기 전에 갱신
python -m messenger.worker --project 2 --recipient emma --worker existing-emma renew --claim-file data/emma-claim.json --lease 120

# 기존 작업자가 자신의 역할을 수행하고 결과 MD를 직접 작성한 뒤 완료
python -m messenger.worker --project 2 --recipient emma --worker existing-emma complete --claim-file data/emma-claim.json --result C:/Work/Shared/memos/review-v1.md --hash <RESULT_SHA256>

# 상대 작업자에게 넘기려면 별도 알림 필요: complete는 자동 전달하지 않음
python -m messenger.worker --project 2 --recipient jaemin --worker existing-emma notify --memo C:/Work/Shared/memos/review-v1.md --hash <RESULT_SHA256>
```

`<SHA256>`/`<RESULT_SHA256>`는 설명용 자리표시자입니다. 꺾쇠까지 실행하지 말고 계산한 해시로 바꾸세요. `claim` 출력에는 비공개 `claim_token`이 들어갑니다. 공개 로그/커밋/메모에 붙이지 마세요. 완료·오류 후 claim 파일을 재사용하지 않습니다. 읽기 명령의 출력에는 메모 본문이 포함됩니다.

오류를 명시적으로 종료하려면:

```bash
python -m messenger.worker --project 2 --recipient emma --worker existing-emma error --claim-file data/emma-claim.json --error "메모 변경 확인: 작성자가 새 버전을 등록해야 함"
```

## Python 연동 계약

`messenger.worker.WorkerClient(base_url, project_id, recipient, worker_id)`를 **기존 작업자의 실행 흐름**에서 사용합니다.

- `claim(lease_seconds=120)` → 알림 객체 또는 `None`.
- `read(claim)` → 실제 읽고 해시 검증한 **동일 바이트** 반환 + 서버 읽음 확인. 이후 기존 작업자에게 이 내용과 프로젝트의 활성 원칙을 전달해야 합니다.
- `renew(claim, lease_seconds=120)` → 임대 갱신. 1~3600초 정수. 갱신 타이머/취소/예외 처리는 통합 코드 책임입니다.
- `complete(claim, result_path, result_hash)` → 기존 작업자가 작성한 결과 MD 확인 및 연결.
- `error(claim, reason)` → 오류 종료.
- `notify(recipient, memo_path, version_hash)` → 다음 작업자에게 별도 알림.

이 adapter에는 상시 루프, AI 호출, 세션 주입, 터미널 키 입력이 없습니다. `read` 성공은 파일 읽기/해시 일치 확인이지 AI 이해나 업무 수행 증명이 아닙니다. `complete`도 결과 파일 존재/해시 확인이지 내용의 정확성·품질 검수 증명이 아닙니다.

## 상태·재시도·장애 복구

`pending → claimed → read → completed` 또는 `claimed/read → error`.

- claim은 DB 트랜잭션으로 한 작업자에게 임대됩니다. 프로젝트와 수신자별로 가장 오래된 대기 항목을 가져옵니다.
- 작업자 중단 시 `claimed/read` 임대가 끝난 후 다음 claim에서 재전달됩니다. 새 토큰이 발급되며 이전 토큰은 거절됩니다. `attempts`가 증가합니다.
- **at-least-once 방식**입니다. 이미 수행한 외부 작업이 완료 ACK 전에 중단되면 다시 수행될 수 있습니다. 기존 작업자가 알림 ID·해시로 중복 실행을 막아야 합니다.
- 서버 재시작 후 DB의 알림/임대는 유지됩니다. 임대가 남으면 원래 claim으로 계속할 수 있고, 만료되면 새 claim이 필요합니다.
- `completed`/`error`는 종료 상태입니다. 같은 알림 재전송으로 재개되지 않습니다. 오류 해결 뒤 새 버전 또는 새 경로의 메모를 등록하세요. 관리용 재시도/취소 API는 아직 없습니다.
- 서버를 잠깐 사용할 수 없는 경우 adapter 호출은 실패합니다. 통합 코드는 backoff 후 재조회하고, 완료 요청 응답을 잃었다면 상태를 조회하여 성공 여부부터 확인해야 합니다.
- 조회 `after`는 **알림 ID 커서**이지 상태 변경 이벤트 커서가 아닙니다. 이전 알림의 상태 변화를 보려면 다시 조회해야 합니다. UI는 전체 알림을 페이지별로 다시 읽습니다.

## HTTP API 요약

POST는 JSON 객체, 최대 65536바이트. 보통 성공 200, 검증 오류 400, 외부 Origin/Host 403, 구형 대화 쓰기 405입니다.

| 경로 | 용도 / 핵심 필드 |
|---|---|
| `GET /api/health` | 모드 확인 |
| `GET/POST /api/projects` | 조회 / `name`, `workspace`로 생성 |
| `GET /api/notifications?project_id=2&after=0&limit=200` | 알림 조회; `next_after`, 최대 500개; claim token 제외 |
| `POST /api/notifications` | `project_id`, `recipient`, `memo_path`, `version_hash` |
| `POST /api/notifications/claim` | `project_id`, `recipient`, `worker_id`, 선택 `lease_seconds`; `{notification: object 또는 null}` |
| `POST /api/notifications/{id}/read` | `project_id`, `claim_token`, `version_hash` |
| `POST /api/notifications/{id}/renew` | `project_id`, `claim_token`, 선택 `lease_seconds` |
| `POST /api/notifications/{id}/complete` | `project_id`, `claim_token`, `result_path`, `result_hash`; 먼저 read 필요 |
| `POST /api/notifications/{id}/error` | `project_id`, `claim_token`, `error`(최대 2000자) |
| `GET /api/messages?project_id=2&after=0&limit=200` | 구형 대화 읽기 전용, ID 페이지네이션 |
| `GET /api/rules?project_id=2` | 보호 원칙 및 기존 프로젝트 원칙 조회 |

`project_id`는 양의 정수입니다. 웹 API claim은 wrapper 객체를 반환하지만 CLI `claim`은 내부 알림 객체만 출력합니다. claim 파일에는 **CLI 출력 형식**을 저장하세요.

기존 사용자용 원칙 추가/승인 API는 남아 있지만 UI는 조회 전용입니다. `POST /api/rules`는 사용자용 활성 원칙 등록이므로 worker가 자신을 사용자로 가장해서 호출하면 안 됩니다. 원칙 제안·승인은 기존 사용자 승인 절차에서 처리해야 합니다. 서버가 AI에 원칙을 자동 주입하거나 준수를 강제하지 않습니다.

## 보안 범위와 미구현 사항

- IPv4 loopback만 바인딩합니다. 정확한 Host/동일 Origin 검사, 외부 Origin 거절, 외부 redirect/HTTP proxy 사용 방지를 적용했습니다. 인터넷 공개·포트 포워딩·공유 PC용 서비스로 사용하지 마세요.
- **로컬 신뢰 프로세스용이며 사용자/worker 인증은 없습니다.** 로컬 프로그램은 worker 이름을 가장하거나 임의 프로젝트를 등록할 수 있습니다. claim token은 경쟁 수신/오래된 ACK 방지용이지 로그인 자격증명이 아닙니다.
- 프로젝트 폴더 검사·해시는 실행 샌드박스가 아닙니다. 동시 파일 변경/링크 교체에 대한 OS 수준 격리는 없으며, 작업자 자체 권한과 승인된 경로 제한이 필요합니다.
- 메모 내용은 명령으로 실행하지 않습니다. 기존 작업자는 메모를 무조건 신뢰하지 말고 사용자 승인·역할·허용 경로를 확인해야 합니다.
- 사용자 판단 대기, 중단, 파괴적 작업 승인, 자동 왕복 상한은 기존 작업자 연동에서 구현해야 합니다. 구형 `paused`/`USER_DECISION_REQUIRED` 기록은 보존되지만 새 courier 큐의 자동 정지 장치가 아닙니다.
- 자동 깨우기/실제 Hermes·Antigravity 세션 연동, 사용자 알림 push, 메모 내용 보관, 취소·재시도 관리, worker 인증은 미구현입니다.
- 서버는 로컬 전달만 담당합니다. 기존 작업자가 AI 제공자를 이용하면 메모 내용이 외부 제공자 서버로 전송될 수 있습니다.

## 개인 데이터·백업·이전 버전 복귀

- `data/messages.db`에는 개인 프로젝트·과거 대화·전달 경로가 있습니다. Git에 올리지 않습니다. `data/`, `backups/`, `*.db`, `*.bak`, 로그/캐시 제외 규칙을 유지하세요.
- 기존 DB에 courier 테이블이 없으면 최초 초기화 전에 SQLite backup API로 같은 폴더에 `messages.db.pre-courier-<임의값>.bak`를 생성합니다. 과거 messages 테이블에는 INSERT/UPDATE/DELETE 거절 트리거가 생깁니다. 기존 프로젝트·대화·프로젝트 원칙은 보존하며, 폐기된 자동협의/외부전송 없음 문구만 새 보호 원칙으로 대체합니다.
- 이번 재구축 전 백업: `backups/courier_rebuild_20260909_090241/`에 기존 소스와 `messages.db`가 있습니다. DB 읽기 전용 `PRAGMA integrity_check` 결과 `ok`를 확인했습니다.
- 운영 백업은 서버를 정상 종료한 뒤 하거나 SQLite backup API를 이용하세요. 실행 중 DB 파일만 단순 복사하면 WAL 내용이 빠질 수 있습니다.
- 복귀는 모든 서버/브리지를 종료하고 현재 DB도 별도 보존한 뒤 **구형 소스와 구형 백업 DB를 함께** 복원합니다. 구형 bridge를 courier DB에 직접 실행하면 읽기 전용 트리거와 충돌합니다. 백업 이후 알림은 구형 DB에 없으므로 유실 범위를 먼저 확인하세요.
- 포맷 후 복원은 저장소와 Python 외에 개인 DB·공유 메모 폴더도 별도 복원해야 합니다. 경로 변경 시 새 프로젝트 등록이 필요할 수 있습니다.

## 검증

```bash
python -m unittest discover -s tests -q
python -m unittest discover -s tests -p test_protocol_e2e.py -v
```

E2E는 OS가 고른 임시 포트, 임시 SQLite DB, 실제 UTF-8 임시 MD 파일을 사용합니다. emma→jaemin→emma 프로토콜 전달, claim 후 서버 재시작, 결과 해시와 최종 상태 재조회, 중복/프로젝트 격리/비공개 토큰 제외/잘못된 해시·경로·Origin·Host 거절을 검사합니다. **시험 작업자는 명시적인 fixture이며 실제 AI의 작업 결과가 아닙니다.** 운영 DB·기존 세션·매크로 프로젝트를 사용하지 않습니다.

구성: `courier.py` 전달 상태 저장, `worker.py` 기존 작업자용 one-shot adapter, `server.py` HTTP API, `launcher.py` 서버/브라우저 실행, `store.py` 이전 저장소 및 프로젝트·원칙, `static/index.html` 우편함 UI.
