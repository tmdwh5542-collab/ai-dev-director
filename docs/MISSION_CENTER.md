# 미션 센터 개선판

공개 저장소 `digilogd-cmd/ai-dev-director`의 커밋 `d2541ad`(v3.1.8)를 기준으로 만든 별도 개선본입니다.
사용자가 첨부한 `ai-dev-director-trial.zip`은 전송 도구의 32 MiB 제한으로 열지 못했습니다.
따라서 그 ZIP에만 있는 사용자 수정이나 `launch-trial.py`와의 호환성은 확인하지 않았습니다.

## 달라진 사용 흐름

1. 콘솔에서 **미션 센터**를 엽니다. 직접 주소는 `/missions`입니다.
2. 현재 프로젝트와 공급자의 마지막 기록 상태를 확인합니다. **프로젝트 선택**에서 최근 프로젝트, 폴더 찾아보기, 경로 입력을 사용할 수 있습니다.
3. **새 미션 준비**에서 목표, 완료 조건, 작업 범위와 주의사항을 작성합니다. 기능 추가·버그 수정·품질 개선 예시를 사용할 수 있습니다.
4. 작업 규모를 고르고 **미션 시작**을 누르면 선택한 프로젝트에서 작업을 시작합니다. 서버의 시작 요청 상태가 표시되며 새로고침해도 이어서 확인할 수 있습니다. **스테이지에서 확인**은 기존처럼 실행하지 않고 초안만 넘깁니다.
5. 미션 센터에서 목표·프로젝트·미션 ID를 검색하거나 상태를 필터링합니다. 기록은 15초마다 갱신되며 검색 중이나 상세 창을 보는 동안에는 목록을 자동 교체하지 않습니다.
6. 미션 제목을 누르면 단계별 테스트, 독립 검수, 수정 횟수, HEAD 요약, 작업본 경로, 원본 적용 여부와 AI 호출 기록을 확인할 수 있습니다.
7. 단계의 **실행 로그 · 검수 지적 · 변경 내용 보기**를 누르면 실제 실패 출력과 지적을 볼 수 있습니다. 수정 지시를 적어 **재계획**, 예산을 늘려 **이어서 진행**, 서버 중단으로 멈춘 미션의 **재개**를 사용할 수 있습니다.
8. 검증된 결과는 상세 창에서 **원본에 적용**할 수 있습니다. 충돌이 생기면 건너뛰지 않고 보류합니다. **보고서 저장**은 현재 조회한 요약 근거를 Markdown 파일로 다운로드합니다. 권한 승인과 정지 등 기존 관리는 작업실에서도 사용할 수 있습니다.

2차 개선의 상세 동작과 복구 방법은 [EXECUTION_CENTER.md](EXECUTION_CENTER.md)를 참고하세요.

완료된 미션 수는 `DONE` 기록의 개수입니다. 개별 테스트 통과나 원본 적용까지 보장하는 수치는 아니므로 상세 창에서 각각 확인합니다.
공급자의 “정상 기록”은 마지막 저장 상태이며 현재 로그인·잔여 한도를 실시간으로 검사한 결과가 아닙니다.
미확인 상태나 테스트 기록이 없는 경우는 그대로 표시합니다. 토큰의 `~` 표시는 추정치입니다.
상세 보고서의 AI 호출 기록은 원래 기록 조회 함수와 같이 완료된 호출 중 시간순으로 최대 400건을 표시합니다.

## Windows에서 별도 실행

기존 프로그램 폴더를 보관하고, 개선판을 **새 폴더**에 풀어 사용하는 것을 권장합니다.
기존 `AI DEV DIRECTOR.lnk`는 이전 폴더의 `launch-trial.py`를 가리키므로 새 개선판을 실행하지 않습니다.

새 폴더에서 PowerShell을 열어 실행합니다. Python 3.9 이상, Git이 필요합니다.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe companion_server.py
```

서버가 켜지면 브라우저에서 `http://127.0.0.1:8081/missions`를 엽니다.
실제 개발 작업에는 원본 프로그램과 마찬가지로 로그인된 CLI와 구독이 필요합니다.
기본 포트 8081을 쓰는 이전 프로그램이 실행 중이라면 먼저 이전 프로그램의 **시스템 중지**로 종료해야 합니다.
새 프로그램과 이전 프로그램을 같은 포트에서 동시에 실행할 수 없습니다.

macOS / Linux:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python companion_server.py
```

## 기존 설정과 기록을 이어서 사용할 때

공개 저장소와 다른 trial 버전에는 먼저 파일 차이를 확인해야 합니다. 개선판 ZIP을 기존 폴더 전체에 무작정 덮어쓰지 마세요.

기존 프로그램을 종료한 상태에서 기존 폴더를 통째로 백업한 뒤, 새 폴더에 필요한 설정·상태를 **복사**합니다.

- `config.yaml`, `companion.json`: 프로젝트 경로·포트·역할·검증 명령 등 기존 설정.
- `data/`: 데이터베이스, 미션 기록, 역할 설정 등 런타임 상태. 일부 결과 근거는 `runs/`에도 있습니다.
- `runs/`: 기존 실행의 추가 근거가 필요할 때 복사합니다.

미션 JSON에 저장된 결과물 경로는 절대 경로입니다. 폴더를 이동해도 자동 변경되지 않습니다.
기존 `.director_worktrees`와 원본 프로젝트를 유지해야 예전 작업본에 접근할 수 있습니다.
소스 폴더 자체를 검증 대상 프로젝트로 지정할 수 없는 원본 제한도 유지됩니다.
`config.yaml`의 `resume_on_start`와 `auto_apply` 등 원래 실행 정책이 적용되므로,
기존 기록을 복사한 후 실행할 때는 해당 설정을 확인하세요.

## 초안과 전송 복구

- 미션 양식과 스테이지 입력은 현재 브라우저의 로컬 저장소에 보관합니다. 브라우저/포트가 다르면 공유되지 않습니다.
- 비밀정보를 입력하지 마세요. **초안 지우기**는 준비 양식만 지웁니다. 스테이지 초안은 입력창에서 지울 수 있습니다.
- 전송은 서버의 `accepted`/`duplicate` 응답을 확인한 다음 입력을 비웁니다. 바쁨·오류·통신 실패에는 입력을 유지합니다.
- 통신 실패 후 같은 요청을 재시도할 때는 기존 요청 ID를 유지해 서버의 중복 실행 방지를 사용합니다. 서버를 재시작하면 원본의 메모리 기반 중복 방지 기록은 사라집니다.
- 전송 중 사용자가 다음 요청을 작성한 경우, 이전 요청의 성공 응답이 새 초안을 지우지 않습니다.
- 저장소 접근이 차단되면 양식에 안내를 표시하며 작성 내용을 직접 복사할 수 있습니다.

## 개발자 검증

```sh
python -m pip install -r requirements-dev.txt
python -m pytest -q tests/test_mission_center.py tests/test_v309_trinity_stage.py tests/test_v301_companion_http.py tests/test_v0238_dashboard_ux.py
python -m pytest -q tests/test_verifier_python_cache.py tests/test_v306_head_proxy_autonomy.py tests/test_v303_proposal.py
python -m pytest -q tests/test_mission_execution_center.py
```

브라우저 회귀 검증은 선택 사항이며 Node.js와 Playwright가 필요합니다.

```sh
npm install --no-save playwright
npx playwright install chromium
# 현재 Python 환경에 requirements-dev.txt가 설치되어 있어야 합니다.
node tests/browser/mission_center.cjs
node tests/browser/execution_center.cjs
```

다른 Python이나 Chromium을 쓰려면 `DIRECTOR_UI_PYTHON`, `DIRECTOR_UI_CHROMIUM`을 지정합니다.
Linux 가상환경 예:

```sh
DIRECTOR_UI_PYTHON=.venv/bin/python DIRECTOR_UI_CHROMIUM=/usr/bin/chromium node tests/browser/mission_center.cjs
```

이 검증은 임시 DB와 임시 미션을 쓰는 별도 서버를 실행하고 종료합니다. 실제 AI CLI를 실행하지 않습니다.
검색, 필터, 페이지 이동, 근거 조회, 보고서 저장, HTML 삽입 방지, 초안 복원,
전송 실패/재시도, 전송 중 입력 유지, 모바일, 장애와 빈 기록 상태를 확인합니다.
`artifacts/`의 화면 캡처는 **테스트용 예시 데이터**로 촬영한 것이며 사용자의 실제 작업 이력이 아닙니다.

## 구현 범위

- `console/missions.html`, `missions.css`, `missions.js`: 외부 의존성 없는 반응형 미션 센터.
- `dashboard_server.py`: 읽기 전용 `/ops/missions` 목록·상세 API. 목록은 페이지당 최대 50건이며 상세 근거는 선택 시 읽습니다.
- `core/mission_launch.py`: 시작 요청의 SQLite 기록, 동시 계획 제한, 중복 ID 검증, 중단 감지.
- `companion_server.py`, `dashboard_server.py`: 시작 요청/상태, 프로젝트 목록, 제한된 실행 근거 조회, 토큰이 필요한 미션 제어 API.
- `companion_server.py`: 새 정적 파일을 명시적 허용 목록에 추가. 기존 로컬 출처 검사와 CSP 유지.
- `console/stage.js`: 초안 보관, 성공 확인 후 입력 삭제, 재시도 요청 ID 유지.
- `core/verifier.py`: 명령별 임시 Python 캐시 경로로, 같은 크기·같은 타임스탬프의 이전 `.pyc`가 수정한 소스 대신 검증되는 문제 방지. 기존 프로젝트의 캐시 파일은 삭제하지 않습니다.
- `console/index.html`, `stage.css`: 미션 센터 진입 링크.
- AI 공급자 호출 방식, 구독 정책, 권한 심사, 원본 반영과 정지 정책은 기존 구현을 사용합니다.

실제 Windows PC에서의 실행과 로그인된 세 CLI의 종단간 실행은 이 Linux 개발 환경에서 검증하지 않았습니다.
