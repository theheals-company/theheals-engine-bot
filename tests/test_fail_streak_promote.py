# tests/test_fail_streak_promote.py
# 4-C-3: 실패 유형 누적 → 스킬 승격 연결 검증

import pytest

import vault_writer

pytestmark = pytest.mark.smoke


def test_scenario_a_first_fail(monkeypatch):
    """A) record_fail_pattern 1회 호출 → count=1, threshold_reached=False."""
    monkeypatch.setattr(vault_writer, "_fail_counts", {})
    result = vault_writer.record_fail_pattern("코드작업")
    assert result["task_type"] == "코드작업"
    assert result["count"] == 1
    assert result["threshold_reached"] is False


def test_scenario_b_threshold_reached(monkeypatch):
    """B) 동일 task_type 2회 호출 → count=2, threshold_reached=True."""
    monkeypatch.setattr(vault_writer, "_fail_counts", {})
    vault_writer.record_fail_pattern("코드작업")
    result = vault_writer.record_fail_pattern("코드작업")
    assert result["count"] == 2
    assert result["threshold_reached"] is True


def test_scenario_c_independent_counters(monkeypatch):
    """C) 다른 task_type 카운터 독립 — 코드작업=2여도 리서치=1."""
    monkeypatch.setattr(vault_writer, "_fail_counts", {})
    vault_writer.record_fail_pattern("코드작업")
    vault_writer.record_fail_pattern("코드작업")
    result = vault_writer.record_fail_pattern("리서치")
    assert result["count"] == 1
    assert result["threshold_reached"] is False
    assert vault_writer._fail_counts["코드작업"] == 2


def test_scenario_d_promote_returns_draft_without_saving(monkeypatch):
    """D) 승격 시 파일 저장 없이 20_SKILLS/ 제안 경로 + 초안 내용만 반환 (길B 자동저장 역전)."""
    save_calls = []

    def mock_save(path, content, message):
        save_calls.append(path)
        return {"ok": True, "path": path, "url": "https://example.test"}

    monkeypatch.setattr(vault_writer, "save_skill_to_vault", mock_save)
    result = vault_writer.promote_fail_pattern("코드작업", "더 꼼꼼히 확인")
    assert save_calls == [], "promote_fail_pattern은 더 이상 save_skill_to_vault를 호출하면 안 됨"
    assert result["ok"] is True
    assert result["path"].startswith("20_SKILLS/")
    assert "더 꼼꼼히 확인" in result["content"]


def test_scenario_e_fail_counts_path_allowed():
    """E) _fail_counts.json 경로 → ALLOWED_PREFIX 통과, shield 면제 (JSON은 비코드)."""
    path = "10_WIKI/오답노트/_fail_counts.json"
    assert path.startswith(vault_writer.ALLOWED_PREFIX)
    ok, _ = vault_writer.shield_check('{"코드작업": 2}', path)
    assert ok
