"""ORD-ID 영속 저장소 — SQLite 기반 발주 추적 백본 (ORD-2026-0708-P1).
발주서 §2: ORD-YYYYMMDD-NN 형식 ID + 7단계 생애주기(접수→분해→실행중→CI심판→감리→승인대기→완결/반려).
봇 재시작 내성 확보가 목적 — 메모리/채널 스캔 대신 이 파일이 단일 진실(SSOT)."""

import datetime
import os
import sqlite3

DB_PATH = os.environ.get("ORDERS_DB_PATH", "orders.db")

# 발주서 §2 생애주기 7단계 + 실사용 현황(수정요청/타임아웃)을 포괄하는 참고 어휘.
# status 컬럼은 자유 텍스트 — 아래는 강제 제약이 아니라 문서화용 상수.
FINAL_STATUSES = ("완결", "반려")


_SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    source_channel_msg_id TEXT,
    approval_msg_id TEXT,
    result_summary TEXT,
    pr_url TEXT
)
"""


def _connect(db_path=None):
    """모든 호출부가 테이블 존재를 가정할 수 있도록 연결 시마다 스키마를 보장한다
    (init_db() 호출 순서에 의존하지 않음 — 테스트/재시작 어느 경로에서도 안전)."""
    conn = sqlite3.connect(db_path or DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(_SCHEMA)
    return conn


def init_db(db_path=None):
    """orders 테이블 생성(존재하면 무시). 봇 기동 시 1회 호출(명시적 초기화 용도로 유지)."""
    _connect(db_path).close()


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def create_order(title: str, source_channel_msg_id: str | None = None, today=None, db_path=None) -> str:
    """ORD-YYYYMMDD-NN ID를 당일 순번으로 발급하고 orders에 접수 상태로 기록. ID 반환."""
    today = today or datetime.datetime.now(datetime.timezone.utc).date()
    prefix = f"ORD-{today:%Y%m%d}-"
    conn = _connect(db_path)
    try:
        (count,) = conn.execute("SELECT COUNT(*) FROM orders WHERE id LIKE ?", (prefix + "%",)).fetchone()
        order_id = f"{prefix}{count + 1:02d}"
        now = _now_iso()
        conn.execute(
            "INSERT INTO orders (id, title, status, created_at, updated_at, source_channel_msg_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (order_id, title, "접수", now, now, source_channel_msg_id),
        )
        conn.commit()
        return order_id
    finally:
        conn.close()


def update_status(order_id: str, status: str, db_path=None) -> None:
    conn = _connect(db_path)
    try:
        conn.execute(
            "UPDATE orders SET status = ?, updated_at = ? WHERE id = ?",
            (status, _now_iso(), order_id),
        )
        conn.commit()
    finally:
        conn.close()


def set_approval_message(order_id: str, approval_msg_id: str, db_path=None) -> None:
    conn = _connect(db_path)
    try:
        conn.execute(
            "UPDATE orders SET approval_msg_id = ?, updated_at = ? WHERE id = ?",
            (approval_msg_id, _now_iso(), order_id),
        )
        conn.commit()
    finally:
        conn.close()


def set_result(order_id: str, result_summary: str | None = None, pr_url: str | None = None, db_path=None) -> None:
    conn = _connect(db_path)
    try:
        conn.execute(
            "UPDATE orders SET result_summary = COALESCE(?, result_summary), "
            "pr_url = COALESCE(?, pr_url), updated_at = ? WHERE id = ?",
            (result_summary, pr_url, _now_iso(), order_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_order(order_id: str, db_path=None) -> dict | None:
    conn = _connect(db_path)
    try:
        row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_open_orders(db_path=None) -> list[dict]:
    """완결/반려로 전이되지 않은 모든 발주."""
    conn = _connect(db_path)
    try:
        placeholders = ",".join("?" for _ in FINAL_STATUSES)
        rows = conn.execute(f"SELECT * FROM orders WHERE status NOT IN ({placeholders})", FINAL_STATUSES).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def list_stale_open_orders(timeout_seconds: int, db_path=None) -> list[dict]:
    """미결 발주 중 approval_msg_id가 있고 updated_at이 timeout_seconds보다 오래된 것.
    startup_recovery()의 DB 우선 경로에서 사용 — 재시작으로 워치독을 잃은 항목 탐지."""
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=timeout_seconds)
    stale = []
    for order in list_open_orders(db_path=db_path):
        if not order.get("approval_msg_id"):
            continue
        updated_at = datetime.datetime.fromisoformat(order["updated_at"])
        if updated_at < cutoff:
            stale.append(order)
    return stale
