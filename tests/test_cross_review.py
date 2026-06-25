# tests/test_cross_review.py
# 더힐즈 엔진 — 4-A 교차혈통 2심 게이트 스모크 테스트
# 원칙: 실제 네트워크(모델 API) 호출 없음. pick_reviewer/cross_review '로직'만 검증.
# bot.py import 시 디스코드 클라이언트가 기동되지 않도록 필수 환경변수를 먼저 주입한다.

import os

import discord
import pytest

# bot.py 모듈 레벨은 (1) os.environ["DISCORD_TOKEN"]를 읽고 (2) 말미에서 bot.run()으로
# 디스코드 클라이언트를 기동한다. import 부작용 차단:
#   - 더미 토큰 주입(실제 값 아님)
#   - discord.Client.run 을 no-op로 치환 → 네트워크 연결·블로킹 없이 모듈 로드
os.environ.setdefault("DISCORD_TOKEN", "dummy-not-real")
discord.Client.run = lambda *a, **k: None

import bot  # noqa: E402

# 모든 테스트에 smoke 마커
pytestmark = pytest.mark.smoke


def test_pick_reviewer_claude_to_openai():
    """가드: claude 빌더 → openai 계열 리뷰어(MODEL_REVIEW 기본값)."""
    assert bot.pick_reviewer("claude:claude-opus-4-8") == "openai:gpt-5.5"


def test_pick_reviewer_openai_to_claude():
    """가드: openai 빌더 → claude 리뷰어로 교차."""
    assert bot.pick_reviewer("openai:gpt-5.5") == "claude:claude-opus-4-8"


def test_cross_review_fail_open_on_exception(monkeypatch):
    """가드: 리뷰 모델 호출이 터져도 게이트를 막지 않고 '⚠️ 교차 2심 실패'로 시작."""

    def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(bot, "call_model", boom)
    out = bot.cross_review("드래프트 내용", "원발주 내용", "claude:claude-opus-4-8")
    assert out.startswith("⚠️ 교차 2심 실패")
