# tests/test_vault_writer.py
# 더힐즈 엔진 — 길 B 가드레일 스모크 테스트 (CI 1심-B)
# 원칙: 실제 네트워크(GitHub API) 호출 없음. 가드레일 '로직'만 검증.
# ⚠️ 이 파일은 초안. Claude Code가 fresh-clone한 실물 vault_writer.py와
#    대조(함수명·에러 메시지)해 일치 확인 후 확정할 것.

import pytest

import vault_writer

# 모든 테스트에 smoke 마커 (CI: pytest -m smoke)
pytestmark = pytest.mark.smoke


def test_guardrail1_rejects_path_outside_whitelist():
    """가드레일1: 20_SKILLS/ 밖 경로는 거부."""
    with pytest.raises(ValueError, match="20_SKILLS"):
        vault_writer.save_skill_to_vault("10_WIKI/sneaky.md", "내용", "msg")


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
