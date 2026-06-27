# tests/test_vault_writer.py
# 더힐즈 엔진 — 길 B 가드레일 스모크 테스트 (CI 1심-B)
# 원칙: 실제 네트워크(GitHub API) 호출 없음. 가드레일 '로직'만 검증.

import pytest

import vault_writer

# 모든 테스트에 smoke 마커 (CI: pytest -m smoke)
pytestmark = pytest.mark.smoke


def test_guardrail1_rejects_path_outside_whitelist():
    """가드레일1: 허용 경로 외(예: 00_RAW/) 거부."""
    with pytest.raises(ValueError, match="경로 쓰기 금지"):
        vault_writer.save_skill_to_vault("00_RAW/sneaky.md", "내용", "msg")


def test_guardrail2_rejects_path_traversal():
    """가드레일2: 20_SKILLS/로 시작해도 .. 포함 시 거부."""
    with pytest.raises(ValueError, match="비정상 경로"):
        vault_writer.save_skill_to_vault("20_SKILLS/../etc/passwd", "내용", "msg")


def test_guardrail3_rejects_secret_in_content():
    """가드레일3: 비밀키 패턴이 내용에 있으면 거부.
    주의: 진짜 키 아님. 스캐너(우리 자신·GitHub push protection) 오탐 방지를 위해
          비밀키처럼 '보이는' 문자열을 런타임에 조립한다(파일에 리터럴로 박지 않음)."""
    fake_secret = "ghp_" + "A" * 30  # ghp_\w+ 패턴에만 매칭, 실제 키 아님
    with pytest.raises(ValueError, match="비밀키"):
        vault_writer.save_skill_to_vault("20_SKILLS/ok.md", f"문서\n{fake_secret}\n", "msg")


def test_happy_path_passes_guards_and_writes(monkeypatch):
    """가드 3종 통과 + 네트워크는 가짜로 대체 → 실제 GitHub 호출 없이 ok 반환."""
    monkeypatch.setenv("GITHUB_TOKEN", "dummy-not-real")
    monkeypatch.setenv("VAULT_REPO", "owner/repo")

    class FakeResp:
        status_code = 404  # 기존 파일 없음 → 신규 생성 경로

        def json(self):
            return {"content": {"html_url": "https://example.test/x"}}

        def raise_for_status(self):
            pass

    def fake_get(*a, **k):
        return FakeResp()

    def fake_put(*a, **k):
        r = FakeResp()
        r.status_code = 201
        return r

    monkeypatch.setattr(vault_writer.requests, "get", fake_get)
    monkeypatch.setattr(vault_writer.requests, "put", fake_put)

    out = vault_writer.save_skill_to_vault("20_SKILLS/clean.md", "안전한 내용", "test")
    assert out["ok"] is True
    assert out["path"] == "20_SKILLS/clean.md"


# ── 4-C-1 시나리오 A/B/C/D ────────────────────────────────────────────────


def _fake_requests(monkeypatch):
    """공통 네트워크 목(mock) 설정. put_called 리스트로 호출 여부 추적."""
    monkeypatch.setenv("GITHUB_TOKEN", "dummy-not-real")
    monkeypatch.setenv("VAULT_REPO", "owner/repo")

    put_called = []

    class FakeResp:
        status_code = 404

        def json(self):
            return {"content": {"html_url": "https://example.test/x"}}

        def raise_for_status(self):
            pass

    def fake_get(*a, **k):
        return FakeResp()

    def fake_put(*a, **k):
        put_called.append(True)
        r = FakeResp()
        r.status_code = 201
        return r

    monkeypatch.setattr(vault_writer.requests, "get", fake_get)
    monkeypatch.setattr(vault_writer.requests, "put", fake_put)
    return put_called


def test_scenario_a_s2_blocked(monkeypatch):
    """A) sensitivity: S2 포함 → S2_BLOCKED 반환, PUT 미호출."""
    put_called = _fake_requests(monkeypatch)
    content = "---\nsensitivity: S2\n---\n민감한 내용"
    out = vault_writer.save_skill_to_vault("20_SKILLS/secret.md", content, "msg")
    assert out["ok"] is False
    assert out["reason"] == "S2_BLOCKED"
    assert out["path"] == "20_SKILLS/secret.md"
    assert put_called == [], "PUT이 호출되면 안 됨"


def test_scenario_b_s0_skills_path(monkeypatch):
    """B) sensitivity: S0, 경로 20_SKILLS/ → PUT 호출, ok=True."""
    put_called = _fake_requests(monkeypatch)
    content = "---\nsensitivity: S0\n---\n안전한 스킬 내용"
    out = vault_writer.save_skill_to_vault("20_SKILLS/safe.md", content, "msg")
    assert out["ok"] is True
    assert len(put_called) == 1, "PUT이 정확히 한 번 호출되어야 함"


def test_scenario_c_s0_mistake_note_path(monkeypatch):
    """C) sensitivity: S0, 경로 10_WIKI/오답노트/ → PUT 호출, ok=True."""
    put_called = _fake_requests(monkeypatch)
    content = vault_writer.build_mistake_note("테스트 작업", "원인", "방지책")
    out = vault_writer.save_skill_to_vault("10_WIKI/오답노트/test.md", content, "msg")
    assert out["ok"] is True
    assert len(put_called) == 1, "PUT이 정확히 한 번 호출되어야 함"


def test_scenario_d_disallowed_path(monkeypatch):
    """D) 허용 안 된 경로(00_RAW/) → 기존 경로 차단 유지."""
    with pytest.raises(ValueError, match="경로 쓰기 금지"):
        vault_writer.save_skill_to_vault("00_RAW/data.md", "내용", "msg")


def test_build_mistake_note_passes_s2_guard():
    """build_mistake_note 출력은 sensitivity: S0 고정이므로 S2 가드 통과."""
    note = vault_writer.build_mistake_note("작업명", "원인", "방지책")
    assert "sensitivity: S0" in note
    assert "sensitivity: s2" not in note.lower()
    assert "오답노트: 작업명" in note
