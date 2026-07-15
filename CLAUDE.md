# CLAUDE.md — theheals-engine-bot

더힐즈 엔진의 디스코드 관제 봇(`bot.py`). `#발주` 채널 메시지를 분류해 멀티 프로바이더 LLM으로
응답을 생성하고, 자가검증(발주 템플릿 체크리스트·출력 게이트)을 거쳐 `#승인대기`에 승인 게이트를
게시한다. 상세 CI 매핑·검증 레지스트리 등 더 깊은 내용은 `AGENTS.md`를 함께 참조할 것 — 이 문서는
빠르게 훑을 핵심 요약이고, `AGENTS.md`가 ci.yml 실물 줄번호까지 추적하는 상세본이다.

## 기술 스택

| 구성 | 버전/설정 | 비고 |
|------|-----------|------|
| Python | 3.12 | `ci.yml` `PYTHON_VERSION` |
| discord.py | >=2.3.0 | Discord Bot API 클라이언트 |
| anthropic (Claude) | >=0.40.0 | 기본 답변·계획 생성 (Sonnet 기본 티어, Opus 승격 티어) |
| openai | >=1.50.0 | 교차혈통 2심 리뷰어(감리) |
| google-generativeai (Gemini) | >=0.8.0 | 리서치 유형 전용 + 일일 브리핑 웹검색 |
| PyYAML | >=6.0 | `models.yaml` 파싱 |
| requests | >=2.31.0 | 볼트(vault) GitHub API 쓰기 |
| ruff | 설정 `pyproject.toml`: select E/F/I, line-length 120 | 린트+포맷 |
| pytest | 마커 `smoke`, `pythonpath=["."]` | 스모크 테스트만 CI 필수 |
| Render | Background Worker (`Procfile`: `worker: python bot.py`) | 배포 플랫폼. 환경변수는 Render Env에만 |

> ⚠️ 모델 프로바이더는 **Claude(Anthropic) / OpenAI / Gemini** 세 곳이다. Groq은 이 저장소
> 어디에도 쓰이지 않는다 — 다른 프로젝트와 혼동하지 말 것.
> 실제 모델 배정은 `models.yaml`(볼트 `90_SCHEMA/models.yaml`의 런타임 사본)이 유일한 기준.
> 계획서·문서에 모델명을 적을 때 이 파일의 실제 값만 인용 — 임의 모델명 기재 금지(과거 날조 사고 있었음).

## 실행

```bash
python bot.py
```

필수 환경변수: `DISCORD_TOKEN`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`.
볼트 쓰기(오답노트 등)에는 `GITHUB_TOKEN`, `VAULT_REPO`도 필요. 나머지(`ORDER_CHANNEL`,
`APPROVAL_CHANNEL`, `PROGRESS_CHANNEL`, `BRIEFING_HOUR`, `APPROVAL_TIMEOUT_SECONDS` 등)는
전부 기본값이 있는 선택 값 — 전체 목록은 `bot.py` 상단 참조.

## 테스트 / 검증

PR 올리기 전 로컬에서 반드시 한 줄로 실행:

```bash
ruff check . && ruff format --check . && pytest -m smoke && python -m compileall -q .
```

CI(`ci.yml`) 필수 잡 3개와 1:1 대응: `1심-A · Lint (ruff)` / `1심-B · Test (pytest smoke)` /
`1심-C · Build (byte-compile)`. **`ruff format --check`를 빠뜨리면 로컬은 통과하고 CI만 실패할
수 있으니 반드시 포함.** 스모크 테스트는 가드레일 로직만 네트워크 monkeypatch로 검증한다 —
실제 디스코드/모델/볼트 연동까지 확인하려면 별도 E2E가 필요하다(단위 통과 ≠ 통합 정상).

## 절대 금지 규칙

- **main 직접 커밋 금지.** 모든 변경은 브랜치 → PR → CI 3잡 green → 병합. main은 branch
  protection으로 강제 상태 체크 3개(admin도 우회 불가, force-push·삭제 금지)가 걸려 있다.
- **자기 머지 금지.** GitHub 쪽 `required_approving_review_count`는 0으로 설정되어 있다(1인
  운영 체제라 "대표 merge 클릭이 곧 승인"이기 때문 — 리뷰어 인원 부족이 아니라 의도적 설계).
  즉 플랫폼이 강제하는 규칙이 아니라 **에이전트가 지켜야 하는 작업 규율**이다: PR을 만드는
  것까지가 에이전트의 역할이고, merge 버튼은 항상 대표가 누른다.
- **S2 등급 콘텐츠 접근·기록 금지.** 특허 청구항 언어·핵심 수치 임계값 등은 S2 등급 —
  봇 응답·볼트 일반 문서에 기재 금지. 코드 레벨 방어선은 `vault_writer.py`의
  `save_skill_to_vault()`(`sensitivity: s2` 문자열 감지 시 GitHub PUT 차단)뿐이며, 이건
  자진신고 태그 기반 검사라 콘텐츠 자체를 분류하지는 않는다 — 실질 방어는 "애초에 S2급
  정보를 볼트에 쓰려 하지 않는 것"이다.
- **비밀값(토큰/키)을 코드·로그·볼트 문서에 쓰지 않는다.** Render Env에만 둔다.
- **봇 자동 저장 경로는 `10_WIKI/오답노트/`, `10_WIKI/진화창고/`뿐** (`vault_writer.py`
  `ALLOWED_PREFIX`). 경로 탈출(`..`)·다른 브랜치 지정(vault-sync 외)은 코드 레벨에서 차단됨.
- **카파시 4브레이크**: ① 모호하면 멈춰 질문한다 ② 단순함을 최우선한다 ③ 버그는 하나만
  수술하듯 고친다(주변 코드 임의 수정 금지) ④ 개선을 발견하면 대표에게 보고 후 진행한다.

## 볼트(vault) 구조

봇이 참조/기록하는 GitHub 저장소는 `theheals-engine-vault`(별도 레포, 로컬 경로
`C:\Heals\theheals-engine-vault`)이며 4개 최상위 디렉토리로 나뉜다:

| 디렉토리 | 용도 |
|---|---|
| `00_RAW` | 가공 전 원본 자료 |
| `10_WIKI` | 지식 문서(오답노트·발주·진행기록·특허 등). 봇이 유일하게 자동 쓰기 가능한 영역 |
| `20_SKILLS` | 재사용 스킬 문서. 봇은 초안만 만들고 실제 저장은 사람이 수동으로 함 |
| `90_SCHEMA` | 헌법·용어사전·모델 배정표(`models.yaml`) 등 거버넌스 문서 |

봇 저장소에 있는 `glossary.md`, `models.yaml`은 각각 볼트 `90_SCHEMA/`의 **런타임 사본**이다
(직접 편집 금지, 볼트 갱신 후 수동 동기화). 봇의 쓰기는 전부 `vault-sync` 브랜치로만 가며,
그 볼트 저장소의 `main` 자체는 이 봇 코드가 건드리지 않는다.
