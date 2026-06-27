"""
더힐즈 엔진 봇 v0.8 (검색 효율화 — 감시초소 + Gemini 3.1)
- v0.7 + 검색 효율화: 넓은 웹 스캔 → 감시 키워드 4묶음으로 압축("감시초소").
- 검색 모델 상향: gemini-3.1-pro-preview (완성도 우선, 멀티모달 강화).
  접근 불가 시 gemini-2.5-pro 자동 폴백.
- ★ 유튜브 개발자·기술 영상 동향도 검색 범위에 포함.
- 진화 브리핑(포착·접목·방어·씨앗)·멀티프로바이더·메모리학습 모두 유지.
"""

import datetime
import os
from collections import defaultdict
from zoneinfo import ZoneInfo

import anthropic
import discord
from discord.ext import tasks

from core import models_loader
from vault_writer import process_cancel_note, save_skill_to_vault

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
ORDER_CHANNEL = os.environ.get("ORDER_CHANNEL", "발주")
APPROVAL_CHANNEL = os.environ.get("APPROVAL_CHANNEL", "승인대기")
BRIEFING_CHANNEL = os.environ.get("BRIEFING_CHANNEL", "일일브리핑")
MISTAKE_CHANNEL = os.environ.get("MISTAKE_CHANNEL", "오답노트")  # AgentShield 차단 알림용
KST = ZoneInfo("Asia/Seoul")
BRIEFING_HOUR = int(os.environ.get("BRIEFING_HOUR", "7"))  # KST 기준 시각

# 모델 배정은 models.yaml(볼트 권위본의 런타임 사본) → core.models_loader 경유. (V2.5 A-2)
# env 하드코딩 제거. 비밀값(API 키)만 env 유지.

# 패턴 승격 임계값 (자료 ⑬: 3개 이상이면 스킬 후보)
PROMOTE_THRESHOLD = int(os.environ.get("PROMOTE_THRESHOLD", "3"))

SYSTEM_PROMPT = """당신은 더힐즈컴퍼니(The Heals Company)의 더힐즈 엔진 PM 에이전트 '지아'입니다.
회사 영문 표기는 The Heals (절대 The Hills 아님).
[국면 모드] 매 발주마다 🔵CREATE(추론우선)/🟢SCALE(효율) 먼저 제안. 애매하면 CREATE.
[PM] 계획-실행 분리: 계획(목적·단계·리스크·범위) 제안 후 승인 요청.
[카파시 4원칙] 1.모호하면 질문 2.단순함 3.수술하듯 최소변경 4.목표지향(검증기준 명시).
[태도] 무의미한 위로 배제. 린 제안. 진짜 목적 추론 + 대안 선제.
[비용] 완성도 우선이되 출력은 핵심 중심. 실제 실행 전 대표 승인."""

# ── 4-A: 교차혈통 2심 리뷰어 시스템 프롬프트 ──
SYSTEM_CROSS = """너는 교차혈통 2심 리뷰어다. 빌더와 다른 회사 모델로서, 원발주 대비
드래프트의 누락·오류·과장을 비평한다. 출력은 반드시:
판정: 승인의견|보완필요|반려의견
• 핵심지적(최대3): ...
• 수정제안(선택): ...
너는 최종 판정자가 아니다. 최종 결정은 대표가 한다."""

# ── 세션 메모리: 작업 유형별 카운트 + 발주 기록 ──
pattern_counts = defaultdict(int)
pattern_examples = defaultdict(list)
promoted = set()  # 이미 승격 제안한 유형 (중복 제안 방지)


def classify_task(user_msg: str) -> str:
    """발주를 거친 유형으로 분류 (패턴 학습 단위)."""
    research_kw = ["조사", "찾아", "리서치", "동향", "검색", "최신", "뉴스", "시장"]
    review_kw = ["검증", "검수", "리뷰", "교차", "확인해", "맞는지", "오류"]
    doc_kw = ["작성", "기획", "보고서", "사업계획", "제안서", "정리", "초안"]
    code_kw = ["코드", "구현", "수정", "버그", "배포", "스크립트", "함수"]
    if any(k in user_msg for k in research_kw):
        return "리서치"
    if any(k in user_msg for k in review_kw):
        return "검증"
    if any(k in user_msg for k in doc_kw):
        return "문서작성"
    if any(k in user_msg for k in code_kw):
        return "코드작업"
    return "일반"


def pick_model(task_type: str) -> str:
    if task_type == "리서치":
        return models_loader.get_model("research")
    if task_type == "검증":
        return models_loader.get_model("review")
    return models_loader.get_model("design")


def call_model(model_spec, system, user_msg, max_tokens=2048):
    provider, model_name = model_spec.split(":", 1)
    if provider == "claude":
        c = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        r = c.messages.create(
            model=model_name, max_tokens=max_tokens, system=system, messages=[{"role": "user", "content": user_msg}]
        )
        return r.content[0].text, f"입력 {r.usage.input_tokens}/출력 {r.usage.output_tokens}"
    elif provider == "openai":
        from openai import OpenAI

        c = OpenAI(api_key=OPENAI_API_KEY)
        r = c.chat.completions.create(
            model=model_name,
            max_completion_tokens=max_tokens,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user_msg}],
        )
        u = r.usage
        return r.choices[0].message.content, f"입력 {u.prompt_tokens}/출력 {u.completion_tokens}"
    elif provider == "gemini":
        import google.generativeai as genai

        genai.configure(api_key=GEMINI_API_KEY)
        m = genai.GenerativeModel(model_name, system_instruction=system)
        return m.generate_content(user_msg).text, "토큰 정보 없음"
    return f"⚠️ 알 수 없는 프로바이더: {provider}", "—"


def pick_reviewer(builder_spec: str) -> str | None:
    """빌더와 다른 혈통(회사)의 2심 리뷰어 모델 선택. 동일 혈통뿐이면 None.
    모델 ID는 models_loader 경유(하드코딩 제거). 교차혈통 원칙은 유지(헌법 제4조)."""
    provider = builder_spec.split(":", 1)[0]
    if provider in ("claude", "gemini"):
        return models_loader.get_reviewer()  # 기본 openai 리뷰어
    if provider == "openai":
        return f"claude:{models_loader.get_principal()}"  # openai 빌더 → claude 리뷰어
    return None


def cross_review(draft, user_msg, builder_spec) -> str:
    """교차혈통 2심. fail-open: 동일혈통이면 생략, 실패해도 게이트를 막지 않음."""
    reviewer = pick_reviewer(builder_spec)
    if reviewer is None:
        return "⚠️ 교차 2심 생략 (동일 혈통)"
    try:
        # call_model은 (텍스트, 사용량) 튜플을 반환 → 텍스트만 사용
        text, _ = call_model(
            reviewer,
            SYSTEM_CROSS,
            f"[원발주]\n{user_msg}\n\n[드래프트]\n{draft}",
            max_tokens=700,
        )
        return text
    except Exception as e:
        return f"⚠️ 교차 2심 실패 ({type(e).__name__})"


# ── V2.5 A-2: 에스컬레이션 (연속 실패/특정 task_type → principal 재라우팅) ──
_fail_streak = {}  # task_type → 연속 실패 횟수 (메모리 내)


def _should_escalate(task_type: str) -> bool:
    """governance.trigger_conditions 충족 여부 (연속실패 임계 또는 특정 task_type)."""
    conds = models_loader.get_governance().get("escalate_to_principal", {}).get("trigger_conditions", [])
    threshold = None
    trigger_types = set()
    for c in conds:
        if "consecutive_failures" in c:
            threshold = c["consecutive_failures"]
        if "task_type" in c:
            trigger_types.add(c["task_type"])
    if task_type in trigger_types:
        return True
    return threshold is not None and _fail_streak.get(task_type, 0) >= threshold


async def escalate_to_principal(channel, task_type: str, reason: str) -> str:
    """principal 모델로 재라우팅 + #발주 채널 알림(비밀값 없이 모델명·사유만). 반환=provider:model."""
    principal = models_loader.get_principal()  # claude-opus-4-8 (bare)
    spec = f"claude:{principal}"
    await channel.send(f"⚠️ 에스컬레이션: {reason} → principal({principal}) 재라우팅")
    return spec


intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)


class CancelModal(discord.ui.Modal, title="취소 사유 입력"):
    cause_input = discord.ui.TextInput(
        label="원인",
        placeholder="이 작업이 왜 반려됐는지",
        required=False,
        style=discord.TextStyle.paragraph,
    )
    fix_input = discord.ui.TextInput(
        label="방지책",
        placeholder="다음에 어떻게 막을지",
        required=False,
        style=discord.TextStyle.paragraph,
    )

    def __init__(self, task_name: str, view: "ApprovalView"):
        super().__init__()
        self.task_name = task_name
        self.approval_view = view

    async def on_submit(self, interaction: discord.Interaction):
        content, path, note_msg = process_cancel_note(self.task_name, self.cause_input.value, self.fix_input.value)
        for c in self.approval_view.children:
            c.disabled = True
        await interaction.response.defer()
        await interaction.message.edit(
            content=f"❌ **취소됨**\n{note_msg}",
            view=self.approval_view,
        )


class ApprovalView(discord.ui.View):
    def __init__(self, task_name: str = "작업"):
        super().__init__(timeout=None)
        self.task_name = task_name

    @discord.ui.button(label="승인", style=discord.ButtonStyle.success, emoji="✅")
    async def approve(self, i, b):
        for c in self.children:
            c.disabled = True
        now = datetime.datetime.now().strftime("%m-%d %H:%M")
        await i.response.edit_message(content=f"✅ **승인됨** ({now})", view=self)

    @discord.ui.button(label="수정", style=discord.ButtonStyle.primary, emoji="✏️")
    async def revise(self, i, b):
        for c in self.children:
            c.disabled = True
        await i.response.edit_message(content="✏️ **수정 요청됨**", view=self)

    @discord.ui.button(label="취소", style=discord.ButtonStyle.danger, emoji="❌")
    async def cancel(self, i, b):
        await i.response.send_modal(CancelModal(task_name=self.task_name, view=self))


# ── 스킬 승격 제안 버튼 (메모리 학습 핵심) ──
class PromoteView(discord.ui.View):
    def __init__(self, task_type):
        super().__init__(timeout=None)
        self.task_type = task_type

    @discord.ui.button(label="스킬로 승격", style=discord.ButtonStyle.success, emoji="✅")
    async def promote(self, i, b):
        await i.response.defer()
        for c in self.children:
            c.disabled = True
        examples = "\n".join(f"- {e}" for e in pattern_examples[self.task_type][:5])
        # 스킬 초안 생성 (Claude로)
        draft_prompt = (
            f"'{self.task_type}' 유형 작업이 반복 감지됨. 아래 실제 발주들을 보고, "
            f"20_SKILLS에 넣을 재사용 스킬 초안을 마크다운으로 작성. "
            f"헌법 제5조 승격 절차 준수, 간결하게.\n\n발주들:\n{examples}"
        )
        try:
            draft, _ = call_model(models_loader.get_model("design"), SYSTEM_PROMPT, draft_prompt, 1500)
        except Exception as e:
            draft = f"⚠️ 초안 생성 오류: {e}"
        # === 길B: 승인된 초안을 볼트에 자동 저장 (정상 초안일 때만) ===
        save_msg = ""
        if not draft.startswith("⚠️"):
            try:
                result = save_skill_to_vault(
                    path=f"20_SKILLS/{self.task_type}-스킬.md",
                    content=draft,
                    message=f"길B 자동저장: {self.task_type} 스킬 승격 (대표 승인)",
                )
                save_msg = f"\n\n🟢 **볼트 자동저장 완료** → {result['url']}"
            except Exception as e:
                save_msg = f"\n\n🔴 **저장 실패** (수동 저장 필요): {e}"
                # AgentShield 차단이면 #오답노트에 자동 알림 (비밀값 없이 사유·파일명만)
                if "AgentShield" in str(e):
                    mch = discord.utils.get(i.guild.text_channels, name=MISTAKE_CHANNEL)
                    if mch:
                        await mch.send(f"🛡️ AgentShield 차단 — {self.task_type}: {e}")
        # ============================================================

        await i.edit_original_response(
            content=f"✅ **스킬 승격 승인됨** — '{self.task_type}'\n\n"
            f"**📄 스킬 초안:**\n{draft[:1400]}\n\n"
            f"— — —\n"
            f"💾 **저장 방법:** 위 초안을 검토 후 Claude Code(또는 옵시디언)로 "
            f"`20_SKILLS/{self.task_type}-스킬.md`에 저장하세요. "
            f"헌법 제5조에 따라 INDEX·LOG 등록도 함께." + save_msg,
            view=self,
        )

    @discord.ui.button(label="무시", style=discord.ButtonStyle.secondary, emoji="❌")
    async def ignore(self, i, b):
        for c in self.children:
            c.disabled = True
        await i.response.edit_message(content=f"❌ '{self.task_type}' 승격 보류됨", view=self)


# ── 일일 브리핑 생성 ──
# ── 1단계: Gemini 웹검색(Grounding)으로 오늘 동향 포착 ──
SEARCH_PROMPT = """더힐즈(XR 실기교육 플랫폼) 감시 키워드로 오늘 최신 동향을 검색하라.
[감시 키워드 — 이 범위만, 넓게 훑지 말 것]
1. XR 핸드/모션 트래킹, 공간컴퓨팅 (Vision Pro·Quest·XREAL·Android XR 등)
2. 헤어테크 / 뷰티 AI / 가상 코칭·아바타
3. 경쟁사 동향: Milbon, Panasonic 뷰티
4. AI 에이전트 / 코딩 도구 (Claude Code·MCP 등)

뉴스/발표뿐 아니라 ★유튜브 개발자·기술 영상 동향★도 포함해 검색하라.
각 건: [분야] 제목 — 핵심 한 줄 (+유튜브면 영상 표시). 한국어. 실제 최신 정보 위주.
총 5~7건으로 압축."""


def _gemini_call(model_name, query):
    """단일 Gemini 모델 호출. Grounding 우선, 미지원 시 일반 호출."""
    import google.generativeai as genai

    genai.configure(api_key=GEMINI_API_KEY)
    try:
        m = genai.GenerativeModel(model_name, tools="google_search_retrieval")
        return m.generate_content(query).text
    except Exception:
        m = genai.GenerativeModel(model_name)
        return m.generate_content(query).text


def gemini_search(query):
    """검색 모델(3.1) 우선, 실패 시 폴백 모델(2.5)로 자동 전환."""
    _, primary = models_loader.get_model("research").split(":", 1)
    _, fallback = models_loader.get_model("research_fallback").split(":", 1)
    try:
        return _gemini_call(primary, query)
    except Exception as e1:
        # 3.1 접근 불가/오류 → 2.5로 폴백
        try:
            return _gemini_call(fallback, query) + f"\n(※ {primary} 사용불가로 {fallback} 폴백)"
        except Exception as e2:
            raise Exception(f"검색 실패: 주모델={e1}, 폴백={e2}")


# ── 2단계: Claude가 우리 맥락(심화)으로 접목·방어·씨앗 분석 ──
HEALS_CONTEXT = """[더힐즈 핵심 맥락 — 분석 기준]
- 사업: XR 실기교육 플랫폼. 공통기술(2D→3D 변형·코칭아바타·데이터가공·UIUX) 위에
  헤어XR / 웰니스 두 콘텐츠. "함께 개발" 플랫폼 전략.
- 핵심 난제: Virtual Tension(손가락 관절각도로 모발장력 추론), 마스터 모션데이터 확보.
- 특허(PCT): 0092WO 햅틱-다이나믹 루프, 0095WO 이종센서 AI학습·데이터매칭.
- 경쟁: Milbon(미 상표 선점), Panasonic. 일일 모니터링 대상.
- 로드맵: Phase1 BYOD(스마트폰+TV) → XR → 로보틱스."""

ANALYSIS_PROMPT_TMPL = """아래는 Gemini가 검색한 오늘의 기술 동향이다.
{context}

[동향 원문]
{trends}

위 동향을 더힐즈 관점에서 분석하라. 진화학습 독트린의 4단계를 따른다.
한국어로, 정보 나열이 아니라 "그래서 우리가 무엇을"까지 간다:

🔍 **오늘의 동향** — 위 중 우리에게 의미있는 3~4건만 추려 한 줄씩
💡 **접목 포인트** — 이 중 공통-플랫폼/헤어/웰니스에 접목 가능한 것 1~2개, 구체적으로
🛡️ **방어 포인트** — 경쟁(Milbon 등)·리스크·특허 측면에서 주의할 신호
💎 **씨앗(신생 아이디어)** — 이 정보가 우리에게 열어주는 새 가능성·추론 1개
간결하게. 각 섹션 핵심만."""


async def generate_briefing():
    today = datetime.datetime.now(KST).strftime("%Y-%m-%d (%a)")
    # 1단계: Gemini 검색
    try:
        trends = gemini_search(SEARCH_PROMPT)
    except Exception as e:
        trends = f"(Gemini 검색 실패: {e})"
    # 2단계: Claude 심화 분석 (접목·방어·씨앗)
    try:
        analysis_prompt = ANALYSIS_PROMPT_TMPL.format(context=HEALS_CONTEXT, trends=trends[:3000])
        analysis, _ = call_model(models_loader.get_model("design"), SYSTEM_PROMPT, analysis_prompt, 2000)
    except Exception as e:
        analysis = f"⚠️ 분석 생성 오류: {e}\n\n[검색 원문]\n{trends[:1500]}"
    return f"📢 **더힐즈 엔진 진화 브리핑 — {today}**\n_Gemini 포착 → 지아 해석 (접목·방어·씨앗)_\n\n{analysis}"


@tasks.loop(time=datetime.time(hour=BRIEFING_HOUR, minute=0, tzinfo=KST))
async def daily_briefing():
    """매일 KST 지정 시각에 #일일브리핑에 자동 게시."""
    for guild in bot.guilds:
        ch = discord.utils.get(guild.text_channels, name=BRIEFING_CHANNEL)
        if ch:
            content = await generate_briefing()
            for idx in range(0, len(content), 1900):
                await ch.send(content[idx : idx + 1900])


@bot.event
async def on_ready():
    print(f"[더힐즈 엔진 봇 v0.8 검색효율화] 로그인: {bot.user}")
    if not daily_briefing.is_running():
        daily_briefing.start()
        print(f"[브리핑] 매일 KST {BRIEFING_HOUR:02d}:00 자동 게시 예약됨")


@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    if message.channel.name != ORDER_CHANNEL:
        return

    # 수동 브리핑 트리거 (테스트용): "브리핑"이라고만 치면 즉시 1회 실행
    if message.content.strip() in ("브리핑", "briefing", "브리핑해줘"):
        async with message.channel.typing():
            content = await generate_briefing()
        ch = discord.utils.get(message.guild.text_channels, name=BRIEFING_CHANNEL)
        target = ch if ch else message.channel
        for idx in range(0, len(content), 1900):
            await target.send(content[idx : idx + 1900])
        if ch:
            await message.channel.send(f"✅ 브리핑을 #{BRIEFING_CHANNEL}에 게시했습니다.")
        return

    task_type = classify_task(message.content)
    model_spec = pick_model(task_type)

    async with message.channel.typing():
        try:
            answer, usage = call_model(model_spec, SYSTEM_PROMPT, message.content)
            _fail_streak[task_type] = 0
            answer += f"\n\n— — —\n🤖 모델: {model_spec} | 📊 {usage} | 🏷️ 유형: {task_type}"
        except Exception as e:
            _fail_streak[task_type] = _fail_streak.get(task_type, 0) + 1
            if _should_escalate(task_type):
                # 연속 실패/특정 task_type → principal로 재라우팅 후 1회 재시도
                model_spec = await escalate_to_principal(
                    message.channel, task_type, f"{task_type} {_fail_streak[task_type]}회 연속 실패"
                )
                try:
                    answer, usage = call_model(model_spec, SYSTEM_PROMPT, message.content)
                    _fail_streak[task_type] = 0
                    answer += f"\n\n— — —\n🤖 모델(승계): {model_spec} | 📊 {usage} | 🏷️ 유형: {task_type}"
                except Exception as e2:
                    answer = f"⚠️ 처리 오류 (escalated {model_spec}): {e2}"
            else:
                answer = f"⚠️ 처리 오류 ({model_spec}): {e}"

    for idx in range(0, len(answer), 1900):
        await message.channel.send(answer[idx : idx + 1900])

    # ── 메모리 학습: 패턴 기록·감지 ──
    if task_type != "일반":
        pattern_counts[task_type] += 1
        pattern_examples[task_type].append(message.content[:100])

    approval_ch = discord.utils.get(message.guild.text_channels, name=APPROVAL_CHANNEL)
    if approval_ch:
        # 4-A 교차혈통 2심 (draft=answer, 원발주=message.content) — fail-open, 게이트 차단 안 함
        review = cross_review(answer, message.content, model_spec)
        reviewer_label = pick_reviewer(model_spec) or "동일 혈통"
        draft_txt = answer if len(answer) <= 1200 else answer[:1200] + "…(생략)"
        review_txt = review if len(review) <= 600 else review[:600] + "…(생략)"
        # 일반 승인 게이트 (교차 2심 결과 병기)
        await approval_ch.send(
            content=(
                f"📋 **승인 대기**\n{draft_txt}\n"
                f"───────────────\n"
                f"🔍 **교차 2심** ({reviewer_label})\n{review_txt}\n"
                f"───────────────"
            ),
            view=ApprovalView(task_name=task_type),
        )

        # 패턴 감지 → 스킬 승격 제안 (임계값 도달 + 아직 제안 안 한 유형)
        if pattern_counts[task_type] >= PROMOTE_THRESHOLD and task_type not in promoted:
            promoted.add(task_type)
            # 판단 근거: 반복된 실제 작업 목록
            recent = pattern_examples[task_type][-PROMOTE_THRESHOLD:]
            examples_txt = "\n".join(f"   {n}. {e}" for n, e in enumerate(recent, 1))
            # 지아의 분석: 이 패턴이 스킬로 만들 가치가 있는지 봇이 판단
            analyze_prompt = (
                f"'{task_type}' 유형 작업이 {pattern_counts[task_type]}회 반복됐다. "
                f"아래 실제 발주들을 분석해, 재사용 스킬로 승격할 가치가 있는지 판단하라.\n\n"
                f"발주들:\n{examples_txt}\n\n"
                f"다음 형식으로 4줄 이내로만 답하라(군더더기 금지):\n"
                f"공통점: (세 작업의 공통 패턴 한 줄)\n"
                f"스킬가치: 높음/중간/낮음 (한 줄 근거)\n"
                f"추천: ✅승격 권장 또는 ❌보류 권장 (한 줄 이유)"
            )
            try:
                analysis, _ = call_model(models_loader.get_model("design"), SYSTEM_PROMPT, analyze_prompt, 500)
            except Exception as e:
                analysis = f"(분석 생성 오류: {e})"
            await approval_ch.send(
                content=(
                    f"🧠 **메모리 학습 — 패턴 감지**\n"
                    f"'{task_type}' 유형 작업이 **{pattern_counts[task_type]}회** 반복되었습니다.\n\n"
                    f"📊 **반복된 작업들:**\n{examples_txt}\n\n"
                    f"🔍 **지아의 분석:**\n{analysis}\n\n"
                    f"🛡️ 승인하셔도 자동 저장이 아니라 **초안만 생성**됩니다 "
                    f"(검토 후 직접 20_SKILLS에 저장 — 맥락 오염 차단)\n\n"
                    f"→ 위 분석을 참고해 결정하세요."
                ),
                view=PromoteView(task_type),
            )


bot.run(DISCORD_TOKEN)
