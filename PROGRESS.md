# PROGRESS — 코드 작업단위 핸드오프 (theheals-engine-bot)

> 역할분리: **바통 = 전략 핸드오프(드라이브)** / **PROGRESS = 코드 작업단위 핸드오프(레포)**
> 작업 시작·종료 시 이 파일을 갱신해 다음 에이전트가 이어받게 한다.

## 현재 작업
- (없음 — ORD-2026-0711-P2R 구현 완료, PR 리뷰 대기)

## 완료
- ORD-2026-0711-P2R: 발주 템플릿 가드레일 + 출력 게이트 + 용어사전 실시간 주입
  - 배경: 2026-07-11 실사고 3건(IOBT를 "Internet of Battlefield Things"로 오인·통계 날조,
    계획서에 models.yaml과 무관한 모델명 임의 기재, 재작성 요청에 빈 드래프트를 그대로 감리 제출) 재발 방지.
  - **CI심판/감리 정의 진단**: 대표 확정(마스터 도면 §2 ⑤ 기준 CI심판=1차 GitHub Actions 자동검증,
    감리=2차 교차모델 리뷰) 반영해 코드 재확인 — `bot.py`에 실제 GitHub Actions 호출 로직은 없음(빈 라벨),
    cross_review가 CI심판 자리를 대신한 적 없이 처음부터 "감리"로 올바르게 라벨링되어 있었음을 확인(수정 안 함, 진단만).
  - **모듈4 용어사전 실시간 주입**: `core/glossary_loader.py` 신설(models_loader.py와 동일 패턴) +
    `glossary.md`(볼트 vault-sync `SCH-더힐즈엔진-용어사전-v1.1-병합.md` 런타임 사본, 대표 승인 완료).
    `build_system_prompt()`가 모든 LLM 호출(주 답변·재작성·교차2심·브리핑·스킬초안) system 프롬프트에
    전문 자동 주입 + IOBT/CI심판/감리 3용어 명시 강조. 로드 실패 시 "⚠️ 상태 미인지 모드" 응답 상단 명시.
  - **모듈1 발주 템플릿 체크리스트**: 계획성 응답(리서치·검증 제외)에 4섹션(모델 배정/산출물 및 저장
    경로/버전관리 제출 경로/완료 및 검증 기준) 누락 시 1회 자체 재작성 후 제출.
  - **모듈3 출력 게이트**: 제출 직전 4종 자가검증(100자 이상·발주 키워드 echo·필수 필드·payload-body
    일치) — 실패 시 1회 재생성, 그래도 실패하면 승인대기에 올리지 않고 `#진행상황`에
    "❌ [ORD-ID] 출력 검증 실패 — 수동 확인 필요" 보고(사고3 재발 차단 확인).
  - **모듈2 수정 2회 자동 승격**: `orders.db`에 `revision_count`/`source_text`/`task_type` 컬럼 추가.
    "수정" 클릭마다 카운트 증가, 2회 누적 시 다음 재작성부터 `pick_model(force_escalate=True)`로
    Opus 자동 승격 + 임베드에 "⬆️ 자동 승격됨 (사유: 수정 2회 누적)" 표기. `_generate_and_submit()`로
    생성 파이프라인을 공유 함수화해 on_message(최초)와 ApprovalView.revise(재작성)가 함께 사용.
  - 신규 테스트 25건(test_p2r_guardrails.py 24건 + 기존 파일 보강) + 기존 85건 회귀 없음(합계 110 passed).
    call_model 모의 응답을 "건강한 답변"(100자 이상·4섹션·키워드 echo)으로 현실화 — 출력 게이트가
    실제로 작동하기 시작하면서 기존 테스트의 placeholder 모의 응답이 통과하지 못했던 것을 발견해 수정.
  - IOBT 리서치 시나리오 수동 검증(완료기준③, 실 API 키 없어 시스템 프롬프트 주입까지 확인): 시스템
    프롬프트에 IOBT 정의(Inside-Out Body Tracking)와 금지 해석(Internet of Battlefield Things) 모두 주입 확인.

- ORD-2026-0708-P1: 관제 채널 유기적 연결 Phase 1 (PR #11, 머지·배포 완료)
  - orders.db(SQLite) 신설 — `core/orders_store.py` (ORD-ID 발급·상태전이·조회)
  - #발주 메시지 수신 시 ORD-YYYYMMDD-NN 자동 발급 + 접수 ACK 답글
  - 7단계 생애주기(접수→분해→실행중→CI심판→감리→승인대기→완결/반려) 전이마다 #진행상황 1줄 게시
  - startup_recovery() DB 우선 조회로 리팩토링(기존 채널 스캔은 fallback으로 유지)
  - #승인대기 임베드화 — 변경 파일 수·핵심 요약·PR 링크 필드 + 대표 멘션(PRINCIPAL_MENTION_ID)
  - 승인/수정/취소/타임아웃 확정 시 버튼 disabled + style=secondary(회색) 전환

- ORD-2026-0711-P2: 관제 채널 유기적 연결 Phase 2 (중간보고·하트비트·티어링)
  - **중간보고 버튼**: 실행중 단계 모델 호출 최종 실패 시(승계 재시도 후에도) 깨진 답을 승인게이트로
    보내지 않고 `MidReportView`([계속 진행/수정 필요/중단])를 #진행상황에 게시, orders.db 상태전이로 분기
  - **장기작업 하트비트**: `heartbeat_check` 루프(5분 주기)가 "실행중" 30분↑ 정체 발주에
    "⏳ [ORD-ID] 실행 중... (경과 N분)" 게시. `orders_store.list_orders_needing_heartbeat`/`mark_heartbeat`,
    스키마에 `last_heartbeat_at` 컬럼 마이그레이션 추가(기존 orders.db도 ALTER TABLE로 안전 이관)
  - **추론 티어링(v0.2 §7-2)**: `pick_model()`이 (model_spec, escalated) 튜플 반환 — 기본 Sonnet
    (governance.fallback_model), 의사결정/전략/리스크/왜/판단/위험 키워드 감지 시 Opus(design 역할)로 자동
    승격 + 응답에 "🎯 판단 필요 감지 — Opus 티어 사용" 명시. 일일브리핑 분석도 Sonnet 기본 티어로 전환.
    리서치/검증 역할과 기존 Fable 3출격조건(governance.escalate_to_principal)은 손대지 않음(변경 금지 준수)
  - **오답노트 승격 상정**: 기존 4-C-3 구현(CancelModal.on_submit → record_fail_pattern → FailPromoteView)이
    이미 요구사항을 충족 — 신규 코드 없음, 기존 테스트로 재확인만 함
  - 신규 테스트 24건(test_orders_store.py 하트비트 5건, test_p2_features.py 19건) + 기존 61건 회귀 없음(합계 85 passed)
  - **보류(사용자 확정)**: 항목 4(발주 템플릿 체크리스트)·5(수정 2회 자동 승격)는 근거 문서
    `ORD-P2증보-템플릿체크리스트-수정2회승격-v0.1.md`를 볼트 어디에서도 찾지 못해 이번 PR 범위에서 제외.
    문서 확보 후 별도 발주로 진행 예정.

## 다음
- (없음 — 대표 PR 리뷰 및 실배포 후 실 API 키 기준 IOBT 시나리오 재검증 권장)
- P2의 하트비트·중간보고 버튼 실사용 스크린샷 증빙은 여전히 대표 실배포 확인 필요(누적 이월)

## git 저장점
- 브랜치: feat/p2r-guardrails-glossary (main에서 분기, PR 예정)
- 커밋 해시: (커밋 후 갱신)
- PR 번호: (PR 생성 후 갱신)
