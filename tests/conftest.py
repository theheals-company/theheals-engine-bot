"""tests/conftest.py — 전 테스트 공통 격리 설정.
orders.db는 실행 위치의 실제 파일을 가리키므로, 테스트가 그걸 건드리면
반복 실행 시 상태가 누적되고 레포에 부작용 파일이 남는다. 매 테스트를
독립된 임시 DB로 격리한다(카파시2원칙: 테스트도 부작용 없이 단순하게)."""

import pytest

from core import glossary_loader, orders_store


@pytest.fixture(autouse=True)
def isolated_orders_db(tmp_path, monkeypatch):
    monkeypatch.setattr(orders_store, "DB_PATH", str(tmp_path / "test_orders.db"))


@pytest.fixture(autouse=True)
def isolated_glossary_cache():
    """매 테스트 시작 시 실제 glossary.md를 로드해 "정상 로드됨" 상태를 기본값으로 삼는다
    — 이게 프로덕션의 정상 상태(on_ready에서 부팅 시 로드)이기 때문. 이전 테스트가 남긴
    캐시 상태에 의존하지 않도록 매번 새로 로드해 격리한다. "상태 미인지 모드"를 테스트하려는
    개별 테스트는 monkeypatch.setattr(glossary_loader, "_CACHE", None)로 덮어쓰면 되고,
    monkeypatch가 테스트 종료 시 자동으로 이 로드된 값으로 되돌린다."""
    glossary_loader.load_glossary()
