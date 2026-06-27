# tests/test_cancel_mistake_note.py
# 4-C-2: 취소 핸들러 오답노트 자동기록 — 순수 로직 검증
# 원칙: Discord interaction 없이 process_cancel_note / slugify 로직만 검증.

import pytest

import vault_writer
from vault_writer import process_cancel_note

pytestmark = pytest.mark.smoke


def _mock_save_ok(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "dummy")
    monkeypatch.setenv("VAULT_REPO", "owner/repo")
    monkeypatch.setattr(
        vault_writer,
        "save_skill_to_vault",
        lambda path, content, message: {"ok": True, "path": path, "url": "https://example.test"},
    )


def test_scenario_a_calls_build_and_save(monkeypatch):
    """A) 정상 취소 → build_mistake_note + save_skill_to_vault 호출 확인."""
    monkeypatch.setenv("GITHUB_TOKEN", "dummy")
    monkeypatch.setenv("VAULT_REPO", "owner/repo")

    build_calls = []
    orig_build = vault_writer.build_mistake_note

    def spy_build(task, cause, fix):
        build_calls.append((task, cause, fix))
        return orig_build(task, cause, fix)

    monkeypatch.setattr(vault_writer, "build_mistake_note", spy_build)

    save_calls = []

    def spy_save(path, content, message):
        save_calls.append(path)
        return {"ok": True, "path": path, "url": "https://example.test"}

    monkeypatch.setattr(vault_writer, "save_skill_to_vault", spy_save)

    content, path, note_msg = process_cancel_note("코드작업", "버그 미검증", "테스트 강화")

    assert len(build_calls) == 1, "build_mistake_note가 한 번 호출되어야 함"
    assert build_calls[0] == ("코드작업", "버그 미검증", "테스트 강화")
    assert len(save_calls) == 1, "save_skill_to_vault가 한 번 호출되어야 함"
    assert save_calls[0].startswith("10_WIKI/오답노트/")
    assert "📝 오답노트 기록됨" in note_msg


def test_scenario_b_empty_reason(monkeypatch):
    """B) 사유 미입력(빈값) → '(취소 사유 미입력)' content에 포함."""
    _mock_save_ok(monkeypatch)
    content, path, note_msg = process_cancel_note("테스트 작업", "", "")
    assert "(취소 사유 미입력)" in content


def test_scenario_c_content_has_s0(monkeypatch):
    """C) 저장된 content에 sensitivity: S0 포함 (S2 가드 통과 보장)."""
    _mock_save_ok(monkeypatch)
    content, path, note_msg = process_cancel_note("작업명", "원인", "방지책")
    assert "sensitivity: S0" in content


def test_scenario_d_save_fail_message(monkeypatch):
    """D) save 결과 ok=False → 실패 메시지 분기 확인."""
    monkeypatch.setenv("GITHUB_TOKEN", "dummy")
    monkeypatch.setenv("VAULT_REPO", "owner/repo")
    monkeypatch.setattr(
        vault_writer,
        "save_skill_to_vault",
        lambda path, content, message: {"ok": False, "reason": "S2_BLOCKED", "path": path},
    )
    content, path, note_msg = process_cancel_note("작업명", "원인", "방지책")
    assert "오답노트 기록 실패" in note_msg
    assert "S2_BLOCKED" in note_msg


def test_slugify_basics():
    """slugify: 공백→하이픈, 특수문자 제거, 한글 유지."""
    assert vault_writer.slugify("코드 작업!") == "코드-작업"
    assert vault_writer.slugify("hello world") == "hello-world"
    assert vault_writer.slugify("PR #123") == "PR-123"
