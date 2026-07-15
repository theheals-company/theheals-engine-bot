# tests/test_approval_watchdog.py
# 승인대기 워치독 + 부팅 시 복구 루틴 — 2026-07-07 Render 강제종료 사고 대응
# 원칙: 실제 Discord 연결 없음. asyncio.run으로 코루틴만 직접 구동(pytest-asyncio 미도입).

import asyncio
import datetime
import os

import discord
import pytest

# bot.py import 부작용 차단 (test_cross_review.py와 동일 패턴)
os.environ.setdefault("DISCORD_TOKEN", "dummy-not-real")
discord.Client.run = lambda *a, **k: None

import bot  # noqa: E402
import vault_writer  # noqa: E402

pytestmark = pytest.mark.smoke


# ── 가짜 Discord 객체 (실제 discord.py 인스턴스 대신 duck-typing) ──────────────


class _FakeResponse:
    def __init__(self):
        self.edited = None
        self.deferred = False
        self.modal = None

    async def edit_message(self, content=None, view=None):
        self.edited = {"content": content, "view": view}

    async def defer(self):
        self.deferred = True

    async def send_modal(self, modal):
        self.modal = modal


class _FakeInteraction:
    def __init__(self, guild=None, message=None):
        self.response = _FakeResponse()
        self.guild = guild
        self.message = message


class _FakeMessage:
    def __init__(self, content, author=None, created_at=None):
        self.content = content
        self.author = author
        self.created_at = created_at
        self.edits = []

    async def edit(self, content=None, view=None):
        self.edits.append({"content": content, "view": view})
        self.content = content


class _FakeChannel:
    def __init__(self, name, messages=None):
        self.name = name
        self._messages = messages or []

    async def history(self, limit=None):
        for m in self._messages[:limit]:
            yield m


class _FakeGuild:
    def __init__(self, text_channels):
        self.text_channels = text_channels


class _FakeClient:
    def __init__(self, guilds, user):
        self.guilds = guilds
        self.user = user


_BOT_USER = object()  # bot.user 자리표시자(신원 비교만 필요, 속성 불필요)


def _run(coro):
    return asyncio.run(coro)


# ── ApprovalView: 타임아웃 설정 ──────────────────────────────────────────────


def test_approval_view_uses_configured_timeout():
    """가드: ApprovalView가 timeout=None이 아니라 APPROVAL_TIMEOUT_SECONDS를 사용."""
    view = bot.ApprovalView(task_name="테스트")
    assert view.timeout == bot.APPROVAL_TIMEOUT_SECONDS
    assert view.timeout is not None


# ── 워치독: on_timeout ───────────────────────────────────────────────────────


def test_on_timeout_disables_buttons_and_edits_message():
    """가드: 타임아웃 발생 시 버튼 비활성화 + 메시지가 타임아웃 문구로 갱신됨."""
    view = bot.ApprovalView(task_name="테스트")
    fake_msg = _FakeMessage(content=bot.APPROVAL_PENDING_PREFIX)
    view.message = fake_msg

    _run(view.on_timeout())

    assert all(c.disabled for c in view.children)
    assert len(fake_msg.edits) == 1
    assert fake_msg.edits[0]["content"] == bot.APPROVAL_TIMEOUT_MESSAGE


def test_on_timeout_without_message_does_not_crash():
    """가드: message가 아직 설정 안 된 상태(전송 실패 등)에서도 예외 없이 종료."""
    view = bot.ApprovalView(task_name="테스트")
    _run(view.on_timeout())  # 예외 발생하지 않으면 통과
    assert all(c.disabled for c in view.children)


# ── 최종 상태 도달 시 워치독 정지(self.stop()) ───────────────────────────────


def test_approve_stops_watchdog():
    """가드: 승인 클릭 시 self.stop() 호출 → is_finished()가 True로 전환.
    주의: discord.py View의 __stopped Future는 '실행 중인 이벤트 루프'가 있어야 생성되므로
    View 생성 자체를 코루틴 안(러닝 루프 위)에서 수행해야 is_finished()가 의미를 가진다."""

    async def scenario():
        view = bot.ApprovalView(task_name="테스트")
        interaction = _FakeInteraction()
        assert not view.is_finished()

        await type(view).approve(view, interaction, None)

        assert view.is_finished()
        assert interaction.response.edited["content"].startswith("✅ **승인됨**")

    _run(scenario())


def test_revise_stops_watchdog():
    """가드: 수정 클릭 시에도 self.stop() 호출 — 이미 종결된 메시지를 워치독이 덮어쓰지 않도록."""

    async def scenario():
        view = bot.ApprovalView(task_name="테스트")
        interaction = _FakeInteraction()

        await type(view).revise(view, interaction, None)

        assert view.is_finished()
        assert interaction.response.edited["content"] == "✏️ **수정 요청됨**"

    _run(scenario())


def test_cancel_modal_stops_watchdog_on_submit(monkeypatch):
    """가드: 취소 모달 제출(on_submit) 완료 시 approval_view.stop() 호출."""
    monkeypatch.setenv("GITHUB_TOKEN", "dummy-not-real")
    monkeypatch.setenv("VAULT_REPO", "owner/repo")
    monkeypatch.setattr(
        vault_writer,
        "save_skill_to_vault",
        lambda path, content, message: {"ok": True, "path": path, "url": "https://example.test"},
    )

    async def scenario():
        approval_view = bot.ApprovalView(task_name="테스트")
        modal = bot.CancelModal(task_name="테스트", view=approval_view)
        fake_message = _FakeMessage(content=bot.APPROVAL_PENDING_PREFIX)
        interaction = _FakeInteraction(guild=None, message=fake_message)

        assert not approval_view.is_finished()

        await modal.on_submit(interaction)

        assert approval_view.is_finished(), "취소 완료 후 워치독이 정지되어야 함"
        assert interaction.response.deferred
        assert fake_message.content.startswith("❌ **취소됨**")

    _run(scenario())


def test_cancel_modal_defers_before_slow_network_call(monkeypatch):
    """가드: on_submit 첫 줄이 defer() — process_cancel_note()의 GitHub API 블로킹
    호출보다 먼저 인터랙션에 응답해야 3초 시한 내 "This interaction failed"를 피한다."""
    monkeypatch.setenv("GITHUB_TOKEN", "dummy-not-real")
    monkeypatch.setenv("VAULT_REPO", "owner/repo")
    call_order = []

    def slow_save(path, content, message):
        call_order.append("save_skill_to_vault")
        return {"ok": True, "path": path, "url": "https://example.test"}

    monkeypatch.setattr(vault_writer, "save_skill_to_vault", slow_save)

    async def scenario():
        approval_view = bot.ApprovalView(task_name="테스트")
        modal = bot.CancelModal(task_name="테스트", view=approval_view)
        fake_message = _FakeMessage(content=bot.APPROVAL_PENDING_PREFIX)
        interaction = _FakeInteraction(guild=None, message=fake_message)

        class _TrackedResponse(type(interaction.response)):
            async def defer(self):
                call_order.append("defer")
                await super().defer()

        interaction.response.__class__ = _TrackedResponse

        await modal.on_submit(interaction)

        assert call_order == ["defer", "save_skill_to_vault"], "defer()가 네트워크 호출보다 먼저 실행되어야 함"

    _run(scenario())


# ── 부팅 시 복구 루틴: startup_recovery ──────────────────────────────────────


def test_startup_recovery_recovers_stale_pending_message():
    """가드: 타임아웃 지난 '진행중' 메시지 → 타임아웃 문구로 편집 + 카운트."""
    old_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        seconds=bot.APPROVAL_TIMEOUT_SECONDS + 60
    )
    stale = _FakeMessage(
        content=f"{bot.APPROVAL_PENDING_PREFIX}\n어떤 발주 내용", author=_BOT_USER, created_at=old_time
    )
    ch = _FakeChannel(name=bot.APPROVAL_CHANNEL, messages=[stale])
    client = _FakeClient(guilds=[_FakeGuild(text_channels=[ch])], user=_BOT_USER)

    recovered = _run(bot.startup_recovery(client=client))

    assert recovered == 1
    assert stale.content == bot.APPROVAL_TIMEOUT_MESSAGE
    assert len(stale.edits) == 1
    assert stale.edits[0]["view"] is None


def test_startup_recovery_skips_already_resolved_message():
    """가드: 이미 최종 상태로 전이된 메시지(예: 승인됨)는 손대지 않음."""
    old_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        seconds=bot.APPROVAL_TIMEOUT_SECONDS + 60
    )
    resolved = _FakeMessage(content="✅ **승인됨** (07-07 12:00)", author=_BOT_USER, created_at=old_time)
    ch = _FakeChannel(name=bot.APPROVAL_CHANNEL, messages=[resolved])
    client = _FakeClient(guilds=[_FakeGuild(text_channels=[ch])], user=_BOT_USER)

    recovered = _run(bot.startup_recovery(client=client))

    assert recovered == 0
    assert resolved.edits == []


def test_startup_recovery_skips_message_within_timeout_window():
    """가드: 아직 타임아웃 이전(최근 게시)인 진행중 메시지는 건드리지 않음."""
    recent_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=10)
    fresh = _FakeMessage(content=bot.APPROVAL_PENDING_PREFIX, author=_BOT_USER, created_at=recent_time)
    ch = _FakeChannel(name=bot.APPROVAL_CHANNEL, messages=[fresh])
    client = _FakeClient(guilds=[_FakeGuild(text_channels=[ch])], user=_BOT_USER)

    recovered = _run(bot.startup_recovery(client=client))

    assert recovered == 0
    assert fresh.edits == []


def test_startup_recovery_ignores_non_bot_authors():
    """가드: 봇이 작성하지 않은 메시지(사람이 채널에 쓴 잡담 등)는 대상에서 제외."""
    old_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        seconds=bot.APPROVAL_TIMEOUT_SECONDS + 60
    )
    someone_else = object()
    human_msg = _FakeMessage(content=bot.APPROVAL_PENDING_PREFIX, author=someone_else, created_at=old_time)
    ch = _FakeChannel(name=bot.APPROVAL_CHANNEL, messages=[human_msg])
    client = _FakeClient(guilds=[_FakeGuild(text_channels=[ch])], user=_BOT_USER)

    recovered = _run(bot.startup_recovery(client=client))

    assert recovered == 0
    assert human_msg.edits == []


def test_startup_recovery_tolerates_edit_failure():
    """가드: message.edit()가 HTTPException을 던져도 전체 복구 루틴은 죽지 않고 카운트만 제외."""

    class _FakeHTTPResponse:
        status = 404
        reason = "Not Found"

    class _FailingMessage(_FakeMessage):
        async def edit(self, content=None, view=None):
            raise discord.HTTPException(response=_FakeHTTPResponse(), message="stale message")

    old_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        seconds=bot.APPROVAL_TIMEOUT_SECONDS + 60
    )
    failing = _FailingMessage(content=bot.APPROVAL_PENDING_PREFIX, author=_BOT_USER, created_at=old_time)
    ch = _FakeChannel(name=bot.APPROVAL_CHANNEL, messages=[failing])
    client = _FakeClient(guilds=[_FakeGuild(text_channels=[ch])], user=_BOT_USER)

    recovered = _run(bot.startup_recovery(client=client))  # 예외 전파되면 테스트 자체가 실패함

    assert recovered == 0
