# kakaocli-win

Windows 10/11용 비공식 카카오톡 CLI입니다. 카카오 공식 API나 프로토콜을 사용하지 않고, 실행 중인 PC 카카오톡 창을 Win32 API로 조작합니다.

## 현재 지원 범위

- 카카오톡 설치·실행 상태 점검
- 현재 독립 창으로 열린 채팅방 목록
- 이미 독립 창으로 열린 채팅방 포커스
- 화면에 로드된 대화 텍스트 읽기
- 확인 후 메시지 전송
- 자동화용 JSON 출력
- 카카오톡 업데이트 호환성 진단용 컨트롤 트리 출력
- 실행 중인 `KakaoTalk.exe` 메모리에서 SQLCipher 4 raw key 후보 복구
- 검증된 키를 Windows DPAPI로 보호해 로컬 저장
- 저장된 키로 `TalkUserDB.edb`를 임시 복호화해 친구 목록 조회
- 저장된 별도 키로 `chatListInfo.edb`의 채팅방 메타데이터 조회(메시지 본문 제외)

`read`는 카카오톡 화면에 현재 로드된 대화만 대상으로 합니다. `friends`와 `chat-rooms`는 각각 친구 및 채팅방 메타데이터 DB를 읽지만, 메시지 본문은 읽지 않습니다. 카카오톡 UI가 변경되면 `inspect` 결과를 바탕으로 선택자를 조정해야 할 수 있습니다.

## 설치

요구 사항:

- Windows 10 또는 11
- Python 3.10 이상
- PC 카카오톡 설치 및 로그인

PowerShell에서 이 폴더로 이동한 뒤 실행합니다.

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\install.ps1
.\kakaocli.cmd doctor
```

GitHub에서 바로 설치하려면 다음처럼 복제할 수 있습니다.

```powershell
git clone https://github.com/Lee-SiHyeon/kakaocli-win.git
cd kakaocli-win
Set-ExecutionPolicy -Scope Process Bypass
.\install.ps1
```

## 사용법

```powershell
# 카카오톡 실행
.\kakaocli.cmd start

# 준비 상태 점검
.\kakaocli.cmd doctor

# 열린 채팅방 확인
.\kakaocli.cmd rooms

# 이미 독립 창으로 열린 채팅방 포커스
.\kakaocli.cmd open "홍길동"

# 화면에 로드된 대화 읽기
.\kakaocli.cmd read "홍길동"

# 실제 전송 전 점검
.\kakaocli.cmd send "홍길동" "테스트입니다" --dry-run

# 확인 질문을 거쳐 전송
.\kakaocli.cmd send "홍길동" "테스트입니다"

# 스크립트에서 사용: 정확한 방 이름 + 확인 질문 생략 + JSON
.\kakaocli.cmd --json send "홍길동" "테스트입니다" --exact --yes

# 최신 TalkUserDB.edb 키 복구 및 DPAPI 저장
.\kakaocli.cmd --json recover-key

# 특정 DB 키 복구
.\kakaocli.cmd --json recover-key --db "$env:LOCALAPPDATA\Kakao\KakaoTalk\users\사용자폴더\chat_data\chatListInfo.edb"

# 키 원문 없이 저장 상태와 지문 확인
.\kakaocli.cmd --json key-status

# GUI 자동화 없이 친구 DB 검색
.\kakaocli.cmd friends --contains "vs"

# 자동화용 JSON
.\kakaocli.cmd --json friends --contains "vs"

# GUI 자동화 없이 DB에서 채팅방 제목 검색
.\kakaocli.cmd chat-rooms --contains "바다"

# 종류·개수 필터와 메타데이터 JSON 출력
.\kakaocli.cmd --json chat-rooms --type MultiChat --limit 20

# 데이터 행을 노출하지 않고 DB 테이블·열·행 수만 확인
.\kakaocli.cmd --json db-schema
```

동일한 문자열이 들어간 방이 여러 개면 전송을 중단합니다. 자동화에서는 완전한 채팅방 이름과 `--exact` 사용을 권장합니다.

## 문제 해결

`doctor`가 메인 창을 찾지 못하면 카카오톡에 로그인하고 메인 창을 열어 둡니다. 관리자 권한으로 카카오톡을 실행했다면 CLI도 같은 권한 수준으로 실행해야 Windows가 입력을 허용합니다.

카카오톡은 버전에 따라 내부 컨트롤 클래스가 달라질 수 있습니다. 아래 결과를 파일로 저장하면 선택자 조정에 사용할 수 있습니다.

현재 확인된 카카오톡 버전에서는 친구 탭의 `Ctrl+F`가 검색이 아니라 친구 추가를 열기 때문에, 닫힌 채팅방을 CLI가 자동 검색하지 않습니다. 읽기나 전송 전 PC 카카오톡에서 대상 방을 직접 독립 창으로 열어 두세요.

```powershell
.\kakaocli.cmd --json inspect > main-controls.json
.\kakaocli.cmd --json inspect --room "홍길동" > room-controls.json
```

## 안전 및 제한

- 개인적인 테스트 및 자동화 용도로만 사용하세요.
- 카카오톡 서비스 약관과 조직 정책을 확인하세요.
- 대량·반복 전송 기능은 제공하지 않습니다.
- `send`는 기본적으로 사람의 확인을 요구합니다.
- `read` 명령은 대화 내용을 복사하므로 실행 후 Windows 클립보드가 해당 텍스트로 바뀝니다.
- UI 자동화 특성상 전송 후 실제 채팅창에서 결과를 확인하는 것이 좋습니다.
- 저장소에는 실제 카카오톡 DB, 대화 내용, 방 이름, 복구 키 또는 로컬 진단 결과를 커밋하지 마세요.

### DB 키 복구 안전성

- `recover-key`는 지정한 PID가 실제 `KakaoTalk.exe`인지 확인합니다.
- `MEM_COMMIT` 상태인 읽기 가능한 `MEM_PRIVATE` 영역만 읽습니다.
- 후보 키는 대상 DB 첫 페이지의 SQLCipher 4 HMAC-SHA512로 검증합니다.
- DB 원본과 카카오톡 프로세스 메모리를 수정하지 않습니다.
- 키 원문은 콘솔이나 JSON에 출력하지 않습니다.
- 검증 키는 `%LOCALAPPDATA%\kakaocli-win\keys.json`에 DPAPI 암호문으로 저장되어 같은 Windows 사용자만 해제할 수 있습니다.
- DB 조회 시 평문 SQLite 파일은 Windows 임시 폴더에 만들고 조회 종료 시 즉시 삭제합니다.
- DB가 실제로 사용되는 화면을 최근에 열지 않았다면 키가 메모리에 없을 수 있습니다. 이 경우 해당 화면을 연 뒤 다시 실행하세요.
- 다른 사람의 PC, 계정 또는 접근 권한이 없는 데이터에는 사용하지 마세요.

구현은 `TalkUserDB.edb` 키 복구·재검증과 DPAPI 저장을 지원합니다. 다른 `.edb` 파일은 별도 키를 사용할 수 있으며, 대상 데이터가 메모리에 로드되지 않았다면 제한 시간 안에 키를 찾지 못할 수 있습니다.

## Codex 스킬과 유지관리 스크립트

저장소에는 다른 사용자가 Codex에서 재사용할 수 있는 두 개의 스킬이 포함됩니다.

- `skills/kakaotalk-windows-cli`: 설치, 개인정보를 가린 진단, 안전한 UI 자동화
- `skills/kakaotalk-db-key-recovery`: 소유자 승인 범위의 로컬 DB 키 복구와 검증

스킬을 사용하려면 원하는 폴더를 Codex 스킬 디렉터리에 복사하세요. 각 스킬의 `scripts` 폴더에는 개인정보를 덜 노출하는 진단 및 키 복구 도우미가 들어 있습니다.

공개 전 검증은 다음 명령으로 실행합니다.

```powershell
.\scripts\verify.ps1
```

`privacy-audit.ps1`은 로컬 사용자 경로, 흔한 토큰 형식, 비밀키와 DB/키 저장 파일을 검사합니다. 이는 보조 검사이므로 커밋 전 `git diff --cached`도 직접 확인하세요.

## 출처

Windows의 `EVA_Window_Dblclk`/`RICHEDIT50W` 탐색 방식은 [rime10221/kakao_MCP](https://github.com/rime10221/kakao_MCP)의 공개 구현을 참고해 안전 확인과 진단 기능을 추가했습니다. 이 프로젝트는 해당 저장소나 카카오와 제휴되어 있지 않습니다.

SQLCipher 키 검증은 [SQLCipher 공식 설계 문서](https://www.zetetic.net/sqlcipher/design/)와 [공식 verify.c](https://github.com/sqlcipher/sqlcipher-tools/blob/master/verify.c)의 SQLCipher 4 페이지 HMAC 방식을 따릅니다.
