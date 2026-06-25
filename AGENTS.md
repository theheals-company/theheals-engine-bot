# AGENTS.md — theheals-engine-bot 작업 하네스

> 이 레포에서 작업하는 모든 에이전트의 단일 진실(SSOT). 시작 시 먼저 읽는다.
> 상위 규칙은 볼트 헌법(`theheals-engine-vault/90_SCHEMA/CLAUDE.md`)이며 충돌 시 헌법이 우선한다.

## 정체 / 스택
더힐즈 엔진의 디스코드 관제 봇(`bot.py`, v0.8). `#발주` 채널 메시지를 분류해
멀티 프로바이더(claude/openai/gemini)로 응답하고, `#승인대기`에 승인·교차2심 게이트를 게시한다.

| 구성 | 버전/설정 | 출처(실물) |
|------|-----------|-----------|
| Python | 3.12 | ci.yml `PYTHON_VERSION` |
| discord.py | >=2.3.0 | requirements.txt |
| anthropic / openai / google-generativeai | >=0.40.0 / >=1.50.0 / >=0.8.0 | requirements.txt |
| ruff | unpinned (CI `pip install ruff`) · 설정 pyproject.toml: select E/F/I, line-length 120, target py312 | ci.yml:38 / pyproject.toml |
| pytest | unpinned (CI `pip install pytest`) · 마커 `smoke`, `pythonpath=["."]` | ci.yml:60 / pyproject.toml |

## 실행
```
python bot.py
```
(Render Background Worker Start Command. 환경변수는 Render Env에만 입력 — 아래 금지 규칙.)

## 검증 레지스트리 ★핵심
**전체점검 한 줄** (PR 올리기 전 로컬에서 실행):
```
ruff check . && ruff format --check . && pytest -m smoke && python -m compileall -q .
```
ci.yml 1심 3잡과의 1:1 매핑 (실물 줄번호 재확인):

| 로컬 명령 | CI 잡 | ci.yml 줄 | CI 명령 |
|-----------|-------|-----------|---------|
| `ruff check .` | 1심-A Lint | 40 | `ruff check . --output-format=github` |
| `ruff format --check .` | 1심-A Lint | 42 | `ruff format --check .` |
| `pytest -m smoke` | 1심-B Test | 62 | `pytest tests/ -v -m smoke` |
| `python -m compileall -q .` | 1심-C Build | 78 | `python -m compileall -q .` |

> ⚠️ 1심-A(Lint)는 `ruff check`와 `ruff format --check` **두 명령**으로 구성된다(ci.yml 40·42).
> 전체점검 한 줄에 format 체크를 반드시 포함해야 CI와 일치한다(빠지면 로컬 통과·CI 실패 가능).
> ⚠️ **단위 통과 ≠ 통합 정상.** 스모크는 가드레일 '로직'만 검증한다(네트워크 monkeypatch).
> 실제 디스코드/모델/볼트 연동은 별도 E2E로 병행 확인할 것. (도면2호 §3-2)

## 절대 금지 규칙 (헌법)
- **main 직접 커밋 금지.** 모든 변경은 PR로. (main은 branch protection: PR 필수 + CI 3잡 green + 우회 불가)
- **토큰/키를 코드·로그에 쓰지 않는다.** 비밀값은 Render Env에만 둔다(헌법 제9조).
- **봇 자동 저장경로는 `20_SKILLS/` 만.** (vault_writer.py `ALLOWED_PREFIX`; 경로탈출·비밀키 가드 우회 금지)
- **카파시 4브레이크:**
  1. 모호하면 멈춰 질문한다.
  2. 단순함을 최우선한다.
  3. 버그는 하나만 수술하듯 고친다 — 주변 코드를 멋대로 수정하지 않는다.
  4. 개선을 발견하면 대표에게 보고한 뒤 진행한다.
