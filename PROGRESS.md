# PROGRESS — 코드 작업단위 핸드오프 (theheals-engine-bot)

> 역할분리: **바통 = 전략 핸드오프(드라이브)** / **PROGRESS = 코드 작업단위 핸드오프(레포)**
> 작업 시작·종료 시 이 파일을 갱신해 다음 에이전트가 이어받게 한다.

## 현재 작업
- (없음 — ORD-2026-0708-P1 구현 완료, PR 리뷰 대기)

## 완료
- ORD-2026-0708-P1: 관제 채널 유기적 연결 Phase 1
  - orders.db(SQLite) 신설 — `core/orders_store.py` (ORD-ID 발급·상태전이·조회)
  - #발주 메시지 수신 시 ORD-YYYYMMDD-NN 자동 발급 + 접수 ACK 답글
  - 7단계 생애주기(접수→분해→실행중→CI심판→감리→승인대기→완결/반려) 전이마다 #진행상황 1줄 게시
  - startup_recovery() DB 우선 조회로 리팩토링(기존 채널 스캔은 fallback으로 유지)
  - #승인대기 임베드화 — 변경 파일 수·핵심 요약·PR 링크 필드 + 대표 멘션(PRINCIPAL_MENTION_ID)
  - 승인/수정/취소/타임아웃 확정 시 버튼 disabled + style=secondary(회색) 전환
  - 신규 테스트 20건 (test_orders_store.py, test_ord_id_lifecycle.py) + 기존 41건 회귀 없음(합계 61 passed)
  - 알려진 스코프 결정(PR 설명에 기록): CI심판=교차2심 단계, 감리=리뷰어 라벨 병기 단계에 대응(봇 파이프라인에
    별도 CI/감리 코드 단계가 없어 대표 승인 하에 매핑). 변경 파일 수·PR 링크는 이 챗봇 파이프라인 자체가
    git 변경을 만들지 않으므로 현재는 "—" 플레이스홀더(향후 실제 코딩 ORD가 orders_store.set_result()로 채움).

## 다음
- (없음 — 대표 PR 리뷰 및 실사용 스크린샷 증빙 필요: #발주→#진행상황→#승인대기 1건 E2E)

## git 저장점
- 브랜치: feat/ord-id-backbone-p1 (main에서 분기, PR 예정)
- 커밋 해시: (커밋 후 갱신)
- PR 번호: (PR 생성 후 갱신)
