# tests/test_orders_store.py
# ORD-2026-0708-P1: orders.db 영속 저장소 — ORD-ID 발급/조회/상태전이 순수 로직 검증.
# 원칙: 실제 Discord 연결 없음. tests/conftest.py의 isolated_orders_db가 매 테스트를 임시 DB로 격리.

import datetime

import pytest

from core import orders_store

pytestmark = pytest.mark.smoke


def test_create_order_assigns_sequential_daily_id():
    """가드: 같은 날짜의 발주는 ORD-YYYYMMDD-01, -02 순으로 순번이 매겨짐."""
    day = datetime.date(2026, 7, 9)
    first = orders_store.create_order("첫 발주", "111", today=day)
    second = orders_store.create_order("둘째 발주", "222", today=day)

    assert first == "ORD-20260709-01"
    assert second == "ORD-20260709-02"


def test_create_order_resets_sequence_per_day():
    """가드: 날짜가 바뀌면 순번이 01부터 다시 시작됨."""
    day1 = datetime.date(2026, 7, 9)
    day2 = datetime.date(2026, 7, 10)
    orders_store.create_order("어제", "1", today=day1)
    next_day_first = orders_store.create_order("오늘", "2", today=day2)

    assert next_day_first == "ORD-20260710-01"


def test_create_order_persists_row_with_접수_status():
    """가드: 생성 직후 상태는 '접수', source_channel_msg_id가 그대로 기록됨."""
    order_id = orders_store.create_order("발주 제목", "999", today=datetime.date(2026, 7, 9))
    order = orders_store.get_order(order_id)

    assert order["title"] == "발주 제목"
    assert order["status"] == "접수"
    assert order["source_channel_msg_id"] == "999"
    assert order["created_at"] == order["updated_at"]


def test_update_status_changes_status_and_bumps_updated_at():
    """가드: update_status가 상태값을 바꾸고 updated_at을 갱신함(created_at은 불변)."""
    order_id = orders_store.create_order("발주", "1", today=datetime.date(2026, 7, 9))
    before = orders_store.get_order(order_id)

    orders_store.update_status(order_id, "실행중")
    after = orders_store.get_order(order_id)

    assert after["status"] == "실행중"
    assert after["created_at"] == before["created_at"]
    assert after["updated_at"] >= before["updated_at"]


def test_set_approval_message_records_message_id():
    order_id = orders_store.create_order("발주", "1", today=datetime.date(2026, 7, 9))
    orders_store.set_approval_message(order_id, "555")
    order = orders_store.get_order(order_id)
    assert order["approval_msg_id"] == "555"


def test_set_result_updates_summary_and_pr_url_independently():
    """가드: 인자 하나만 넘겨도 나머지 컬럼은 기존 값을 보존(COALESCE)."""
    order_id = orders_store.create_order("발주", "1", today=datetime.date(2026, 7, 9))
    orders_store.set_result(order_id, result_summary="3개 파일 변경")
    mid = orders_store.get_order(order_id)
    assert mid["result_summary"] == "3개 파일 변경"
    assert mid["pr_url"] is None

    orders_store.set_result(order_id, pr_url="https://example.test/pr/1")
    after = orders_store.get_order(order_id)
    assert after["result_summary"] == "3개 파일 변경"  # 보존됨
    assert after["pr_url"] == "https://example.test/pr/1"


def test_get_order_returns_none_for_unknown_id():
    assert orders_store.get_order("ORD-99999999-99") is None


def test_list_open_orders_excludes_완결_and_반려():
    """가드: 완결/반려로 전이된 발주는 미결 목록에서 제외됨."""
    day = datetime.date(2026, 7, 9)
    open_id = orders_store.create_order("진행중 발주", "1", today=day)
    done_id = orders_store.create_order("완결 발주", "2", today=day)
    rejected_id = orders_store.create_order("반려 발주", "3", today=day)
    orders_store.update_status(done_id, "완결")
    orders_store.update_status(rejected_id, "반려")

    open_ids = {o["id"] for o in orders_store.list_open_orders()}
    assert open_id in open_ids
    assert done_id not in open_ids
    assert rejected_id not in open_ids


def test_list_stale_open_orders_requires_approval_msg_and_timeout_elapsed():
    """가드: approval_msg_id가 없으면 대상에서 제외, 있어도 타임아웃 전이면 제외."""
    day = datetime.date(2026, 7, 9)

    no_approval_msg = orders_store.create_order("승인메시지 없음", "1", today=day)

    fresh = orders_store.create_order("방금 승인대기", "2", today=day)
    orders_store.set_approval_message(fresh, "111")
    orders_store.update_status(fresh, "승인대기")

    stale = orders_store.create_order("오래된 승인대기", "3", today=day)
    orders_store.set_approval_message(stale, "222")
    old_time = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)).isoformat()
    conn = orders_store._connect()
    conn.execute("UPDATE orders SET updated_at = ? WHERE id = ?", (old_time, stale))
    conn.commit()
    conn.close()

    stale_ids = {o["id"] for o in orders_store.list_stale_open_orders(timeout_seconds=900)}
    assert no_approval_msg not in stale_ids
    assert fresh not in stale_ids
    assert stale in stale_ids


def test_init_db_is_idempotent(tmp_path):
    """가드: init_db()를 여러 번 호출해도 예외 없이 통과(CREATE TABLE IF NOT EXISTS)."""
    db_path = str(tmp_path / "another.db")
    orders_store.init_db(db_path)
    orders_store.init_db(db_path)
    order_id = orders_store.create_order("발주", "1", today=datetime.date(2026, 7, 9), db_path=db_path)
    assert orders_store.get_order(order_id, db_path=db_path) is not None
