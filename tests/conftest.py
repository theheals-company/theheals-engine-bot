"""tests/conftest.py — 전 테스트 공통 격리 설정.
orders.db는 실행 위치의 실제 파일을 가리키므로, 테스트가 그걸 건드리면
반복 실행 시 상태가 누적되고 레포에 부작용 파일이 남는다. 매 테스트를
독립된 임시 DB로 격리한다(카파시2원칙: 테스트도 부작용 없이 단순하게)."""

import pytest

from core import orders_store


@pytest.fixture(autouse=True)
def isolated_orders_db(tmp_path, monkeypatch):
    monkeypatch.setattr(orders_store, "DB_PATH", str(tmp_path / "test_orders.db"))
