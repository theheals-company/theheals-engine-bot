# tests/test_ord_id_lifecycle.py
# ORD-2026-0708-P1: ORD-ID 백본이 실제 파이프라인(on_message)과 승인 버튼에
# 올바르게 연결되는지 검증. 실제 Discord/모델 API 호출 없음(call_model monkeypatch).
# tests/conftest.py의 isolated_orders_db가 매 테스트를 임시 DB로 격리한다.

import os
import re

import discord
import pytest

os.environ.setdefault("DISCORD_TOKEN", "dummy-not-real")
discord.Client.run = lambda *a, **k: None

import bot  # noqa: E402
from core import orders_store  # noqa: E402

pytestmark = pytest.mark.smoke


# ── 가짜 Discord 객체 (on_message 흐름 검증용) ───────────────────────────────


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
        self.author = object()  # bot.user(None, 미접속)와 달라야 on_message가 처리함
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


def _healthy_answer(user_msg: str = "") -> str:
    """모듈1(4섹션)·모듈3(100자 이상·키워드 echo·모델메타)을 모두 통과하는 건강한 모의 응답.
    user_msg 일부를 그대로 echo해 발주 핵심 키워드 매칭 체크를 어떤 테스트 문구에도 통과시킨다."""
    return (
        f"{user_msg[:30]} 관련 실행 계획입니다.\n"
        "모델 배정: Sonnet 기본 티어로 처리합니다.\n"
        "산출물 및 저장 경로: docs/output.md에 저장합니다.\n"
        "버전관리/제출 경로: PR-only 원칙에 따라 브랜치 후 PR로 제출합니다.\n"
        "완료 및 검증 기준: 리뷰 승인 시 완료로 간주합니다."
    )


def _mock_call_model(monkeypatch):
    def fake_call_model(model_spec, system, user_msg, max_tokens=2048):
        return _healthy_answer(user_msg), "입력 1/출력 1"

    monkeypatch.setattr(bot, "call_model", fake_call_model)


def _run(coro):
    import asyncio

    return asyncio.run(coro)


# ── on_message: ORD-ID 발급 + DB 기록 + 상태전이 게시 ─────────────────────────


def test_on_message_assigns_ord_id_and_acks(monkeypatch):
    """가드: #발주 메시지 수신 시 ORD-ID가 발급되고 원본에 접수 ACK 답글이 감."""
    _mock_call_model(monkeypatch)
    guild, order_ch, approval_ch, progress_ch = _make_guild()
    message = _FakeOrderMessage("안녕하세요 테스트 발주입니다", order_ch, guild)

    _run(bot.on_message(message))

    assert len(message.replies) == 1
    match = re.match(r"✅ 접수됨 \(ID: (ORD-\d{8}-\d{2})\)", message.replies[0])
    assert match is not None
    order_id = match.group(1)
    assert orders_store.get_order(order_id) is not None


def test_on_message_posts_full_seven_stage_progress_trail(monkeypatch):
    """가드: 접수→분해→실행중→CI심판→감리→승인대기 6개 진행상황 라인이 순서대로 게시됨
    (완결/반려는 승인 버튼 클릭 시점 — 이 테스트 범위 밖)."""
    _mock_call_model(monkeypatch)
    guild, order_ch, approval_ch, progress_ch = _make_guild()
    message = _FakeOrderMessage("안녕하세요 테스트 발주입니다", order_ch, guild)

    _run(bot.on_message(message))

    order_id = re.match(r"✅ 접수됨 \(ID: (ORD-\d{8}-\d{2})\)", message.replies[0]).group(1)
    lines = [s["content"] for s in progress_ch.sent]
    expected_stage_order = ["접수", "분해", "실행중", "CI심판", "감리", "승인대기"]
    assert len(lines) == len(expected_stage_order)
    for line, stage in zip(lines, expected_stage_order):
        assert line.startswith(f"[{order_id}] 상태: {stage}")
        assert message.jump_url in line

    final_order = orders_store.get_order(order_id)
    assert final_order["status"] == "승인대기"
    assert final_order["approval_msg_id"] == str(approval_ch.sent[0]["message"].id)


def test_on_message_builds_result_embed_with_required_fields(monkeypatch):
    """가드: #승인대기 임베드에 변경 파일 수·핵심 요약·PR 링크·원 발주 링크 필드 포함."""
    _mock_call_model(monkeypatch)
    guild, order_ch, approval_ch, progress_ch = _make_guild()
    message = _FakeOrderMessage("안녕하세요 테스트 발주입니다", order_ch, guild)

    _run(bot.on_message(message))

    assert len(approval_ch.sent) == 1
    sent = approval_ch.sent[0]
    embed = sent["embed"]
    field_names = [f.name for f in embed.fields]
    assert "📁 변경 파일 수" in field_names
    assert "🔗 PR/커밋 링크" in field_names
    assert "✏️ 핵심 변경 요약" in field_names
    assert "↩️ 원 발주" in field_names
    summary_field = next(f for f in embed.fields if f.name == "✏️ 핵심 변경 요약")
    assert summary_field.value == _healthy_answer(message.content).splitlines()[0]
    link_field = next(f for f in embed.fields if f.name == "↩️ 원 발주")
    assert message.jump_url in link_field.value
    assert sent["content"].startswith(bot.APPROVAL_PENDING_PREFIX)
    assert isinstance(sent["view"], bot.ApprovalView)
    order_id = re.match(r"✅ 접수됨 \(ID: (ORD-\d{8}-\d{2})\)", message.replies[0]).group(1)
    assert sent["view"].order_id == order_id


def test_on_message_prepends_principal_mention_when_configured(monkeypatch):
    """가드: PRINCIPAL_MENTION_ID가 설정되어 있으면 승인대기 게시에 멘션이 붙되,
    APPROVAL_PENDING_PREFIX는 여전히 시작 부분에 남아 워치독/복구 로직과 호환됨."""
    _mock_call_model(monkeypatch)
    monkeypatch.setattr(bot, "PRINCIPAL_MENTION_ID", "123456789")
    guild, order_ch, approval_ch, progress_ch = _make_guild()
    message = _FakeOrderMessage("안녕하세요 테스트 발주입니다", order_ch, guild)

    _run(bot.on_message(message))

    content = approval_ch.sent[0]["content"]
    assert "<@123456789>" in content
    assert bot.APPROVAL_PENDING_PREFIX in content


def test_on_message_skips_ord_id_for_manual_briefing_trigger(monkeypatch):
    """가드: 수동 브리핑 트리거("브리핑")는 실제 발주가 아니므로 ORD-ID를 발급하지 않음."""
    monkeypatch.setattr(bot, "generate_briefing", lambda: _async_str("브리핑 내용"))
    guild, order_ch, approval_ch, progress_ch = _make_guild()
    message = _FakeOrderMessage("브리핑", order_ch, guild)

    _run(bot.on_message(message))

    assert message.replies == []
    assert progress_ch.sent == []
    assert orders_store.list_open_orders() == []


async def _async_str(value):
    return value


# ── ApprovalView: 승인/수정/취소/타임아웃이 orders.db 상태를 반영하는지 ─────────


class _FakeResponse:
    def __init__(self):
        self.edited = None

    async def edit_message(self, content=None, view=None):
        self.edited = {"content": content, "view": view}


class _FakeInteraction:
    def __init__(self, guild=None):
        self.response = _FakeResponse()
        self.guild = guild


def test_approve_with_order_id_transitions_to_완결_and_posts_progress():
    order_id = orders_store.create_order("테스트 발주", "1")
    guild, order_ch, approval_ch, progress_ch = _make_guild()
    view = bot.ApprovalView(task_name="일반", order_id=order_id)
    interaction = _FakeInteraction(guild=guild)

    _run(type(view).approve(view, interaction, None))

    assert orders_store.get_order(order_id)["status"] == "완결"
    assert progress_ch.sent[-1]["content"].startswith(f"[{order_id}] 상태: 완결")


def test_revise_with_order_id_triggers_regeneration_and_reaches_승인대기(monkeypatch):
    """가드(ORD-2026-0711-P2R 모듈2): '수정' 클릭은 revision_count를 올리고 자동
    재생성을 트리거한다. 1회차(revision_count=1)는 아직 승격 대상이 아니므로
    재생성이 정상 진행되면 다시 승인대기에 도달한다."""
    _mock_call_model(monkeypatch)
    order_id = orders_store.create_order("테스트 발주", "1", source_text="테스트 발주 원문")
    orders_store.set_task_type(order_id, "일반")
    guild, order_ch, approval_ch, progress_ch = _make_guild()
    view = bot.ApprovalView(task_name="일반", order_id=order_id)
    interaction = _FakeInteraction(guild=guild)

    _run(type(view).revise(view, interaction, None))

    order = orders_store.get_order(order_id)
    assert order["revision_count"] == 1
    assert order["status"] == "승인대기"
    assert len(approval_ch.sent) == 1
    assert "⬆️ 자동 승격" not in [f.name for f in approval_ch.sent[0]["embed"].fields]


def test_approve_without_order_id_does_not_touch_db_or_crash():
    """가드: order_id 없이 만든 기존 스타일 ApprovalView는 DB에 손대지 않고 정상 동작(하위호환)."""
    view = bot.ApprovalView(task_name="일반")  # order_id 생략 — 기존 테스트/호출부 호환
    interaction = _FakeInteraction(guild=None)

    _run(type(view).approve(view, interaction, None))  # 예외 없으면 통과

    assert interaction.response.edited["content"].startswith("✅ **승인됨**")


def test_on_timeout_with_order_id_transitions_to_타임아웃():
    order_id = orders_store.create_order("테스트 발주", "1")
    view = bot.ApprovalView(task_name="일반", order_id=order_id)

    _run(view.on_timeout())

    assert orders_store.get_order(order_id)["status"] == "타임아웃"


def test_approve_disables_and_regrays_buttons():
    """가드: '#승인대기 정보 밀도 개선' — 승인 확정 후 버튼이 비활성화되고 회색(secondary)으로 전환."""
    view = bot.ApprovalView(task_name="일반")
    interaction = _FakeInteraction(guild=None)

    _run(type(view).approve(view, interaction, None))

    assert all(c.disabled for c in view.children)
    assert all(c.style == discord.ButtonStyle.secondary for c in view.children)
