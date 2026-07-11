# tests/test_p2_features.py
# ORD-2026-0711-P2: 중간보고 버튼(카파시1원칙) · 장기작업 하트비트 · 추론 티어링 검증.
# 원칙: 실제 Discord/모델 API 호출 없음. tests/conftest.py의 isolated_orders_db가 DB를 격리.

import asyncio
import datetime
import os
import re

import discord
import pytest

os.environ.setdefault("DISCORD_TOKEN", "dummy-not-real")
discord.Client.run = lambda *a, **k: None

import bot  # noqa: E402
from core import orders_store  # noqa: E402

pytestmark = pytest.mark.smoke


# ── 가짜 Discord 객체 (test_ord_id_lifecycle.py와 동일 패턴, 파일 간 의존 없이 자족) ──


class _NullAsyncCM:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _SentMessage:
    _counter = 0

    def __init__(self):
        _SentMessage._counter += 1
        self.id = _SentMessage._counter
        self.edits = []

    async def edit(self, content=None, view=None):
        self.edits.append({"content": content, "view": view})


class _FakeChannel:
    def __init__(self, name):
        self.name = name
        self.sent = []

    def typing(self):
        return _NullAsyncCM()

    async def send(self, content=None, embed=None, view=None):
        msg = _SentMessage()
        self.sent.append({"content": content, "embed": embed, "view": view, "message": msg})
        return msg


class _FakeGuild:
    def __init__(self, text_channels):
        self.text_channels = text_channels


class _FakeOrderMessage:
    def __init__(self, content, channel, guild, msg_id=1):
        self.content = content
        self.channel = channel
        self.guild = guild
        self.author = object()
        self.id = msg_id
        self.jump_url = f"https://discord.test/channels/1/1/{msg_id}"
        self.replies = []

    async def reply(self, content=None, mention_author=True):
        self.replies.append(content)


def _make_guild():
    order_ch = _FakeChannel(bot.ORDER_CHANNEL)
    approval_ch = _FakeChannel(bot.APPROVAL_CHANNEL)
    progress_ch = _FakeChannel(bot.PROGRESS_CHANNEL)
    briefing_ch = _FakeChannel(bot.BRIEFING_CHANNEL)
    guild = _FakeGuild(text_channels=[order_ch, approval_ch, progress_ch, briefing_ch])
    return guild, order_ch, approval_ch, progress_ch


def _run(coro):
    return asyncio.run(coro)


def _order_id_from_reply(message):
    return re.match(r"✅ 접수됨 \(ID: (ORD-\d{8}-\d{2})\)", message.replies[0]).group(1)


def _healthy_answer(user_msg: str = "") -> str:
    """모듈1(4섹션)·모듈3(100자 이상·키워드 echo·모델메타)을 모두 통과하는 건강한 모의 응답."""
    return (
        f"{user_msg[:30]} 관련 실행 계획입니다.\n"
        "모델 배정: Sonnet 기본 티어로 처리합니다.\n"
        "산출물 및 저장 경로: docs/output.md에 저장합니다.\n"
        "버전관리/제출 경로: PR-only 원칙에 따라 브랜치 후 PR로 제출합니다.\n"
        "완료 및 검증 기준: 리뷰 승인 시 완료로 간주합니다."
    )


# ── 추론 티어링 (v0.2 §7-2) ─────────────────────────────────────────────────


@pytest.mark.parametrize("word", ["의사결정", "전략", "리스크", "왜", "판단", "위험"])
def test_needs_judgment_tier_detects_keywords(word):
    assert bot.needs_judgment_tier(f"이건 {word}이 필요한 질문이야") is True


def test_needs_judgment_tier_false_for_plain_message():
    assert bot.needs_judgment_tier("오늘 날씨 어때?") is False


def test_pick_model_defaults_to_sonnet_fallback_tier():
    model_spec, escalated = bot.pick_model("일반", "오늘 회의 요약해줘")
    assert escalated is False
    assert model_spec == f"claude:{bot.models_loader.get_fallback()}"


def test_pick_model_escalates_to_opus_on_judgment_keyword():
    model_spec, escalated = bot.pick_model("일반", "이 리스크에 대한 전략적 판단이 필요해")
    assert escalated is True
    assert model_spec == bot.models_loader.get_model("design")


def test_pick_model_research_and_review_bypass_tiering():
    """가드: 리서치/검증은 판단 키워드 유무와 무관하게 기존 전용 모델 사용(회귀 없음)."""
    research_spec, research_escalated = bot.pick_model("리서치", "왜 이 시장이 성장하는지 조사해줘")
    assert research_escalated is False
    assert research_spec == bot.models_loader.get_model("research")

    review_spec, review_escalated = bot.pick_model("검증", "이 판단이 맞는지 검증해줘")
    assert review_escalated is False
    assert review_spec == bot.models_loader.get_model("review")


def test_on_message_marks_escalated_answer_with_opus_notice(monkeypatch):
    """가드: 판단 필요 감지로 Opus 승격 시 응답에 명시 문구가 붙음."""
    monkeypatch.setattr(
        bot,
        "call_model",
        lambda model_spec, system, user_msg, max_tokens=2048: (_healthy_answer(user_msg), "입력 1/출력 1"),
    )
    guild, order_ch, approval_ch, progress_ch = _make_guild()
    message = _FakeOrderMessage("이 전략적 리스크에 대해 판단해줘", order_ch, guild)

    _run(bot.on_message(message))

    sent_texts = [s["content"] for s in order_ch.sent]
    assert any("🎯 판단 필요 감지 — Opus 티어 사용" in t for t in sent_texts)


def test_on_message_no_opus_notice_for_plain_message(monkeypatch):
    monkeypatch.setattr(
        bot,
        "call_model",
        lambda model_spec, system, user_msg, max_tokens=2048: (_healthy_answer(user_msg), "입력 1/출력 1"),
    )
    guild, order_ch, approval_ch, progress_ch = _make_guild()
    message = _FakeOrderMessage("안녕하세요 테스트입니다", order_ch, guild)

    _run(bot.on_message(message))

    sent_texts = [s["content"] for s in order_ch.sent]
    assert not any("🎯 판단 필요 감지" in t for t in sent_texts)


# ── 중간보고 버튼 (카파시1원칙) ───────────────────────────────────────────────


def test_on_message_failure_triggers_mid_report_and_skips_approval_gate(monkeypatch):
    """가드: 모델 호출 최종 실패 시 승인게이트로 보내지 않고 #진행상황에 중간보고를 올림."""

    def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(bot, "call_model", boom)
    monkeypatch.setattr(bot, "_should_escalate", lambda task_type: False)
    guild, order_ch, approval_ch, progress_ch = _make_guild()
    message = _FakeOrderMessage("안녕하세요 테스트입니다", order_ch, guild)

    _run(bot.on_message(message))

    order_id = _order_id_from_reply(message)
    assert orders_store.get_order(order_id)["status"] == "중간보고"
    assert approval_ch.sent == []  # 깨진 답이 승인 게이트로 흘러가지 않음

    mid_report = progress_ch.sent[-1]
    assert mid_report["view"] is not None
    assert isinstance(mid_report["view"], bot.MidReportView)
    assert mid_report["embed"].title == f"❓ 중간보고 — [{order_id}]"


def test_on_message_escalated_retry_success_does_not_trigger_mid_report(monkeypatch):
    """가드: 1차 실패 후 승계 재시도가 성공하면 중간보고 없이 정상 파이프라인 계속(회귀 방지)."""
    calls = {"n": 0}

    def flaky(model_spec, system, user_msg, max_tokens=2048):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("first failure")
        return _healthy_answer(user_msg), "입력 1/출력 1"

    monkeypatch.setattr(bot, "call_model", flaky)
    monkeypatch.setattr(bot, "_should_escalate", lambda task_type: True)

    async def fake_escalate(channel, task_type, reason):
        return "claude:claude-opus-4-8"

    monkeypatch.setattr(bot, "escalate_to_principal", fake_escalate)
    guild, order_ch, approval_ch, progress_ch = _make_guild()
    message = _FakeOrderMessage("안녕하세요 테스트입니다", order_ch, guild)

    _run(bot.on_message(message))

    order_id = _order_id_from_reply(message)
    assert orders_store.get_order(order_id)["status"] == "승인대기"
    assert len(approval_ch.sent) == 1


def test_mid_report_keep_going_sets_status_실행중_and_grays_buttons():
    order_id = orders_store.create_order("발주", "1")
    guild, order_ch, approval_ch, progress_ch = _make_guild()
    view = bot.MidReportView(order_id=order_id)

    class _FakeResponse:
        async def edit_message(self, content=None, view=None):
            pass

    class _FakeInteraction:
        def __init__(self):
            self.response = _FakeResponse()
            self.guild = guild

    _run(type(view).keep_going(view, _FakeInteraction(), None))

    assert orders_store.get_order(order_id)["status"] == "실행중"
    assert all(c.disabled for c in view.children)
    assert all(c.style == discord.ButtonStyle.secondary for c in view.children)


def test_mid_report_needs_revision_sets_status_수정요청():
    order_id = orders_store.create_order("발주", "1")
    guild, *_ = _make_guild()
    view = bot.MidReportView(order_id=order_id)

    class _FakeResponse:
        async def edit_message(self, content=None, view=None):
            pass

    class _FakeInteraction:
        def __init__(self):
            self.response = _FakeResponse()
            self.guild = guild

    _run(type(view).needs_revision(view, _FakeInteraction(), None))

    assert orders_store.get_order(order_id)["status"] == "수정요청"


def test_mid_report_abort_sets_status_반려():
    order_id = orders_store.create_order("발주", "1")
    guild, *_ = _make_guild()
    view = bot.MidReportView(order_id=order_id)

    class _FakeResponse:
        async def edit_message(self, content=None, view=None):
            pass

    class _FakeInteraction:
        def __init__(self):
            self.response = _FakeResponse()
            self.guild = guild

    _run(type(view).abort(view, _FakeInteraction(), None))

    assert orders_store.get_order(order_id)["status"] == "반려"


# ── 장기작업 하트비트 ─────────────────────────────────────────────────────────


def test_post_heartbeats_once_posts_line_and_marks_heartbeat(monkeypatch):
    guild, order_ch, approval_ch, progress_ch = _make_guild()

    class _FakeClient:
        guilds = [guild]

    monkeypatch.setattr(bot, "bot", _FakeClient())

    order_id = orders_store.create_order("발주", "1")
    orders_store.update_status(order_id, "실행중")
    old_time = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=1900)).isoformat()
    conn = orders_store._connect()
    conn.execute("UPDATE orders SET updated_at = ? WHERE id = ?", (old_time, order_id))
    conn.commit()
    conn.close()

    posted = _run(bot._post_heartbeats_once())

    assert posted == 1
    line = progress_ch.sent[-1]["content"]
    assert line.startswith(f"⏳ [{order_id}] 실행 중... (경과")
    assert orders_store.get_order(order_id)["last_heartbeat_at"] is not None


def test_post_heartbeats_once_no_op_when_nothing_due(monkeypatch):
    guild, order_ch, approval_ch, progress_ch = _make_guild()

    class _FakeClient:
        guilds = [guild]

    monkeypatch.setattr(bot, "bot", _FakeClient())

    posted = _run(bot._post_heartbeats_once())

    assert posted == 0
    assert progress_ch.sent == []
