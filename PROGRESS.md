# PROGRESS — 코드 작업단위 핸드오프 (theheals-engine-bot)

> 역할분리: **바통 = 전략 핸드오프(드라이브)** / **PROGRESS = 코드 작업단위 핸드오프(레포)**
> 작업 시작·종료 시 이 파일을 갱신해 다음 에이전트가 이어받게 한다.

## 현재 작업
- (없음 — ORD-2026-0711-P2 구현 완료, PR 리뷰 대기)

## 완료
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
- (없음 — 대표 PR 리뷰 및 실사용 스크린샷 증빙 필요: 지연/모호 응답 시나리오로 하트비트·중간보고 버튼 실증)
- 보류된 P2 증보 항목 4·5는 문서 확보 후 별도 발주로

## git 저장점
- 브랜치: feat/p2-midreport-tiering-guardrails (main에서 분기, PR 예정)
- 커밋 해시: (커밋 후 갱신)
- PR 번호: (PR 생성 후 갱신)
