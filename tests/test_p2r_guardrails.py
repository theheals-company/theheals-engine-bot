# tests/test_p2r_guardrails.py
# ORD-2026-0711-P2R: 발주 템플릿 체크리스트(모듈1) · 수정2회 자동승격(모듈2) ·
# 출력 게이트(모듈3) · 용어사전 실시간 주입(모듈4) 검증.
# 원칙: 실제 Discord/모델 API 호출 없음. tests/conftest.py가 DB·용어사전 캐시를 격리.

import asyncio
import os
import re

import discord
import pytest

os.environ.setdefault("DISCORD_TOKEN", "dummy-not-real")
discord.Client.run = lambda *a, **k: None

import bot  # noqa: E402
from core import glossary_loader, orders_store  # noqa: E402

pytestmark = pytest.mark.smoke


# ── 가짜 Discord 객체 (기존 테스트 파일들과 동일 패턴, 파일 간 의존 없이 자족) ──


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
    return (
        f"{user_msg[:30]} 관련 실행 계획입니다.\n"
        "모델 배정: Sonnet 기본 티어로 처리합니다.\n"
        "산출물 및 저장 경로: docs/output.md에 저장합니다.\n"
        "버전관리/제출 경로: PR-only 원칙에 따라 브랜치 후 PR로 제출합니다.\n"
        "완료 및 검증 기준: 리뷰 승인 시 완료로 간주합니다."
    )


# ══════════════════════════════════════════════════════════════════════════
# 모듈4 — 용어사전 실시간 주입
# ══════════════════════════════════════════════════════════════════════════


def test_glossary_loader_loads_real_file():
    text = glossary_loader.load_glossary()
    assert "IOBT" in text
    assert "Inside-Out Body Tracking" in text


def test_glossary_loader_raises_on_missing_file(tmp_path):
    missing = tmp_path / "no_such_glossary.md"
    with pytest.raises(FileNotFoundError):
        glossary_loader.load_glossary(str(missing))


def test_build_system_prompt_injects_glossary_when_loaded():
    glossary_loader.load_glossary()
    system_prompt, loaded = bot.build_system_prompt("BASE")
    assert loaded is True
    assert "BASE" in system_prompt
    assert "IOBT" in system_prompt
    assert "Inside-Out Body Tracking" in system_prompt
    # 세 용어 명시 강조 확인
    assert "CI심판 = 1차" in system_prompt
    assert "감리 = 2차" in system_prompt


def test_build_system_prompt_falls_back_when_not_loaded(monkeypatch):
    monkeypatch.setattr(glossary_loader, "_CACHE", None)
    system_prompt, loaded = bot.build_system_prompt("BASE")
    assert loaded is False
    assert "상태 미인지 모드" in system_prompt


def test_prefix_if_state_unaware_only_prefixes_when_not_loaded():
    assert bot._prefix_if_state_unaware("답변", True) == "답변"
    assert "⚠️ 상태 미인지 모드" in bot._prefix_if_state_unaware("답변", False)


def test_on_message_system_prompt_contains_iobt_definition_for_research(monkeypatch):
    """가드(완료기준③ 대리 검증): IOBT 관련 리서치 요청 시 call_model에 전달되는
    system 프롬프트에 올바른 정의(Inside-Out Body Tracking)와 금지 해석
    (Internet of Battlefield Things)이 모두 포함되는지 확인 — 실제 모델 호출은
    이 레포에 API 키가 없어 불가하므로, 주입 메커니즘 자체를 검증한다."""
    captured = {}

    def fake_call_model(model_spec, system, user_msg, max_tokens=2048):
        captured["system"] = system
        captured["user_msg"] = user_msg
        return _healthy_answer(user_msg), "토큰 정보 없음"

    monkeypatch.setattr(bot, "call_model", fake_call_model)
    guild, order_ch, approval_ch, progress_ch = _make_guild()
    message = _FakeOrderMessage("IOBT 관련 최신 동향 조사해줘", order_ch, guild)

    _run(bot.on_message(message))

    system_prompt = captured["system"]
    assert "Inside-Out Body Tracking" in system_prompt
    assert "Internet of Battlefield Things" in system_prompt  # 금지 해석으로 명시됨
    assert "군사/국방/드론/전장 맥락으로 해석 금지" in system_prompt or "절대 아님" in system_prompt


def test_on_message_state_unaware_notice_shown_when_glossary_missing(monkeypatch):
    """가드: 용어사전 로드 실패 시 응답 상단에 '상태 미인지 모드' 명시."""
    monkeypatch.setattr(glossary_loader, "_CACHE", None)
    monkeypatch.setattr(
        bot, "call_model", lambda model_spec, system, user_msg, max_tokens=2048: (_healthy_answer(user_msg), "—")
    )
    guild, order_ch, approval_ch, progress_ch = _make_guild()
    message = _FakeOrderMessage("안녕하세요 테스트 발주입니다", order_ch, guild)

    _run(bot.on_message(message))

    sent_texts = [s["content"] for s in order_ch.sent]
    assert any("⚠️ 상태 미인지 모드" in t for t in sent_texts)


# ══════════════════════════════════════════════════════════════════════════
# 모듈1 — 발주 템플릿 고정 체크리스트
# ══════════════════════════════════════════════════════════════════════════


def test_missing_template_sections_all_present():
    assert bot.missing_template_sections(_healthy_answer("x")) == []


def test_missing_template_sections_detects_each_missing_one():
    base = "모델 배정: A\n산출물 및 저장 경로: B\n버전관리/제출 경로: C\n완료 및 검증 기준: D"
    for section in bot.PLAN_TEMPLATE_SECTIONS:
        broken = base.replace(section, "제거됨")
        assert section in bot.missing_template_sections(broken)


def _is_generation_call(system: str) -> bool:
    """cross_review()도 call_model을 호출하므로(SYSTEM_CROSS 사용), 본 생성 경로
    호출만 구분해서 세려면 SYSTEM_CROSS 고유 마커의 부재로 판별한다(task_type과 무관하게
    항상 존재/부재가 갈리는 유일한 신호 — PLAN_TEMPLATE_INSTRUCTION은 리서치/검증엔 없음)."""
    return "교차혈통 2심 리뷰어" not in system


def test_on_message_retries_once_when_plan_sections_missing(monkeypatch):
    """가드: 계획성 응답(코드작업 등)에 4섹션이 누락되면 1회 자체 재작성 후 제출.
    (call_model은 cross_review의 감리 호출도 거치므로 생성 경로 호출만 별도로 센다.)"""
    gen_calls = {"n": 0}

    def fake_call_model(model_spec, system, user_msg, max_tokens=2048):
        if not _is_generation_call(system):
            return "판정: 승인의견\n• 핵심지적: 없음", "—"  # cross_review 감리 응답
        gen_calls["n"] += 1
        if gen_calls["n"] == 1:
            return "섹션이 하나도 없는 짧은 응답입니다만 100자를 채우기 위해 이렇게 길게 씁니다 여전히 부족한 내용", "—"
        return _healthy_answer(user_msg), "—"

    monkeypatch.setattr(bot, "call_model", fake_call_model)
    guild, order_ch, approval_ch, progress_ch = _make_guild()
    message = _FakeOrderMessage("코드 구현해줘", order_ch, guild)

    _run(bot.on_message(message))

    assert gen_calls["n"] == 2  # 최초 1회 + 누락 재작성 1회
    assert len(approval_ch.sent) == 1
    assert "모델 배정" in approval_ch.sent[0]["embed"].description


def test_on_message_skips_template_check_for_research_and_review(monkeypatch):
    """가드: 리서치/검증 유형은 계획 섹션이 없어도 재작성 트리거 안 됨(범위 밖)."""
    gen_calls = {"n": 0}

    def fake_call_model(model_spec, system, user_msg, max_tokens=2048):
        if not _is_generation_call(system):
            return "판정: 승인의견\n• 핵심지적: 없음", "—"  # cross_review 감리 응답
        gen_calls["n"] += 1
        return f"{user_msg[:20]} 조사 결과입니다. " + "충분히 긴 리서치 응답 본문을 채우기 위한 문장입니다. " * 3, "—"

    monkeypatch.setattr(bot, "call_model", fake_call_model)
    guild, order_ch, approval_ch, progress_ch = _make_guild()
    message = _FakeOrderMessage("최신 동향 조사해줘", order_ch, guild)

    _run(bot.on_message(message))

    assert gen_calls["n"] == 1  # 섹션 누락이어도 재작성 안 함(모듈1 대상 아님)
    assert len(approval_ch.sent) == 1


# ══════════════════════════════════════════════════════════════════════════
# 모듈3 — 출력 게이트
# ══════════════════════════════════════════════════════════════════════════


def test_validate_output_gate_passes_healthy_answer():
    answer = _healthy_answer("발주 원문") + "\n\n— — —\n🤖 모델: claude:x | 📊 y | 🏷️ 유형: 일반"
    assert bot.validate_output_gate(answer, "발주 원문", title="제목") == []


def test_validate_output_gate_flags_empty_body():
    failures = bot.validate_output_gate("짧음", "발주 원문", title="제목")
    assert any("본문 비어있음" in f for f in failures)


def test_validate_output_gate_flags_missing_keyword_overlap():
    long_unrelated = "전혀 무관한 내용을 아주 길게 채워서 백자 이상으로 만드는 문장입니다. " * 3
    failures = bot.validate_output_gate(long_unrelated, "고유키워드포함발주문", title="제목")
    assert any("키워드" in f for f in failures)


def test_validate_output_gate_flags_missing_title():
    answer = _healthy_answer("발주") + "\n🤖 모델: x"
    failures = bot.validate_output_gate(answer, "발주", title="")
    assert any("제목" in f for f in failures)


def test_validate_output_gate_flags_missing_model_meta():
    long_no_meta = "발주 관련 답변입니다. " * 10
    failures = bot.validate_output_gate(long_no_meta, "발주", title="제목")
    assert any("모델 메타" in f for f in failures)


def test_draft_matches_answer_exact_and_truncated():
    answer = "가" * 2000
    assert bot.draft_matches_answer(answer, answer) is True
    truncated = answer[:1200] + "…(생략)"
    assert bot.draft_matches_answer(truncated, answer) is True
    assert bot.draft_matches_answer("다른 내용…(생략)", answer) is False


def test_on_message_blocks_submission_when_output_gate_fails_twice(monkeypatch):
    """가드(사고3 재발 방지): 재생성해도 계속 실패하면 승인대기에 올리지 않고
    #진행상황에 실패 보고, 상태는 출력검증실패로 남는다."""
    monkeypatch.setattr(bot, "call_model", lambda model_spec, system, user_msg, max_tokens=2048: ("", "—"))
    guild, order_ch, approval_ch, progress_ch = _make_guild()
    message = _FakeOrderMessage("안녕하세요 테스트 발주입니다", order_ch, guild)

    _run(bot.on_message(message))

    order_id = _order_id_from_reply(message)
    assert orders_store.get_order(order_id)["status"] == "출력검증실패"
    assert approval_ch.sent == []
    fail_line = progress_ch.sent[-1]["content"]
    assert fail_line == f"❌ [{order_id}] 출력 검증 실패 — 수동 확인 필요"


def test_on_message_recovers_when_retry_fixes_output_gate(monkeypatch):
    """가드: 1차는 빈 드래프트지만 재생성이 정상 응답을 돌려주면 승인대기까지 도달."""
    calls = {"n": 0}

    def fake_call_model(model_spec, system, user_msg, max_tokens=2048):
        calls["n"] += 1
        if calls["n"] == 1:
            return "", "—"
        return _healthy_answer(user_msg), "—"

    monkeypatch.setattr(bot, "call_model", fake_call_model)
    guild, order_ch, approval_ch, progress_ch = _make_guild()
    message = _FakeOrderMessage("안녕하세요 테스트 발주입니다", order_ch, guild)

    _run(bot.on_message(message))

    order_id = _order_id_from_reply(message)
    assert orders_store.get_order(order_id)["status"] == "승인대기"
    assert len(approval_ch.sent) == 1


def test_on_message_blocks_submission_when_payload_mismatch_detected(monkeypatch):
    """가드(모듈3 4번째 검증): draft_matches_answer가 불일치를 보고하면(정상 경로에선
    있을 수 없지만 회귀 방지용 최종 방어선) 승인대기에 올리지 않고 실패 보고한다."""
    monkeypatch.setattr(
        bot, "call_model", lambda model_spec, system, user_msg, max_tokens=2048: (_healthy_answer(user_msg), "—")
    )
    monkeypatch.setattr(bot, "draft_matches_answer", lambda draft_txt, answer: False)
    guild, order_ch, approval_ch, progress_ch = _make_guild()
    message = _FakeOrderMessage("안녕하세요 테스트 발주입니다", order_ch, guild)

    _run(bot.on_message(message))

    order_id = _order_id_from_reply(message)
    assert orders_store.get_order(order_id)["status"] == "출력검증실패"
    assert approval_ch.sent == []
    assert progress_ch.sent[-1]["content"] == f"❌ [{order_id}] 출력 검증 실패 — 수동 확인 필요 (payload 불일치)"


# ══════════════════════════════════════════════════════════════════════════
# 모듈2 — 수정 2회 누적 시 자동 모델 승격
# ══════════════════════════════════════════════════════════════════════════


def test_increment_revision_count_accumulates():
    order_id = orders_store.create_order("발주", "1")
    assert orders_store.increment_revision_count(order_id) == 1
    assert orders_store.increment_revision_count(order_id) == 2
    assert orders_store.get_order(order_id)["revision_count"] == 2


def test_pick_model_force_escalate_overrides_to_opus_regardless_of_keywords():
    model_spec, escalated = bot.pick_model("일반", "그냥 평범한 문장", force_escalate=True)
    assert escalated is True
    assert model_spec == bot.models_loader.get_model("design")


class _FakeResponse:
    async def edit_message(self, content=None, view=None):
        pass


class _FakeInteraction:
    def __init__(self, guild=None):
        self.response = _FakeResponse()
        self.guild = guild


def test_revise_twice_forces_opus_escalation_with_embed_marker(monkeypatch):
    """가드(모듈2 핵심): 동일 ORD가 '수정' 2회 누적되면 3차 재작성부터 Opus로
    자동 승격되고, #승인대기 임베드에 '⬆️ 자동 승격' 마커가 표기된다."""
    monkeypatch.setattr(
        bot,
        "call_model",
        lambda model_spec, system, user_msg, max_tokens=2048: (_healthy_answer(user_msg), "—"),
    )
    order_id = orders_store.create_order("테스트 발주", "1", source_text="테스트 발주 원문 전체")
    orders_store.set_task_type(order_id, "일반")
    guild, order_ch, approval_ch, progress_ch = _make_guild()

    view1 = bot.ApprovalView(task_name="일반", order_id=order_id)
    _run(type(view1).revise(view1, _FakeInteraction(guild=guild), None))
    assert orders_store.get_order(order_id)["revision_count"] == 1
    assert "⬆️ 자동 승격" not in [f.name for f in approval_ch.sent[-1]["embed"].fields]

    view2 = bot.ApprovalView(task_name="일반", order_id=order_id)
    _run(type(view2).revise(view2, _FakeInteraction(guild=guild), None))

    order = orders_store.get_order(order_id)
    assert order["revision_count"] == 2
    assert order["status"] == "승인대기"
    last_embed = approval_ch.sent[-1]["embed"]
    field_names = [f.name for f in last_embed.fields]
    assert "⬆️ 자동 승격" in field_names
    marker_field = next(f for f in last_embed.fields if f.name == "⬆️ 자동 승격")
    assert "수정 2회 누적" in marker_field.value
    # 재생성 답변 본문에도 승격 마커가 명시됨
    assert any("⬆️ 자동 승격됨 (사유: 수정 2회 누적)" in s["content"] for s in order_ch.sent)


def test_revise_regeneration_does_not_double_count_pattern_learning(monkeypatch):
    """가드: 재작성 라운드는 pattern_counts를 다시 증가시키지 않는다(중복 집계 방지)."""
    monkeypatch.setattr(
        bot,
        "call_model",
        lambda model_spec, system, user_msg, max_tokens=2048: (_healthy_answer(user_msg), "—"),
    )
    bot.pattern_counts.clear()
    order_id = orders_store.create_order("코드 발주", "1", source_text="코드 구현해줘")
    orders_store.set_task_type(order_id, "코드작업")
    guild, order_ch, approval_ch, progress_ch = _make_guild()
    before = bot.pattern_counts["코드작업"]

    view = bot.ApprovalView(task_name="코드작업", order_id=order_id)
    _run(type(view).revise(view, _FakeInteraction(guild=guild), None))

    assert bot.pattern_counts["코드작업"] == before  # 재작성 라운드는 집계 안 함


def test_revise_without_guild_does_not_attempt_regeneration():
    """가드: interaction.guild가 없으면(테스트/엣지케이스) 재생성을 시도하지 않고 조용히 반환."""
    order_id = orders_store.create_order("발주", "1")
    view = bot.ApprovalView(task_name="일반", order_id=order_id)

    _run(type(view).revise(view, _FakeInteraction(guild=None), None))  # 예외 없이 통과해야 함

    assert orders_store.get_order(order_id)["status"] == "수정요청"
