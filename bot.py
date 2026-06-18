"""
더힐즈 엔진 봇 v0.5 (반자동 메모리 학습)
- v0.4 + 메모리 학습: 작업 패턴을 감지해 스킬 승격을 '제안'(자동 승격 아님).
- 맥락 오염 차단: 대표 승인(버튼)을 통과한 학습만 확정.
- 멀티 프로바이더·승인 게이트·카파시 4원칙·국면 모드 모두 유지.
- 한계: 패턴 카운트는 세션 메모리(봇 재시작 시 리셋). 영구화는 다음 단계(GitHub 연동).
"""
import os
import datetime
import re
from collections import defaultdict
import discord
import anthropic

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
ORDER_CHANNEL = os.environ.get("ORDER_CHANNEL", "발주")
APPROVAL_CHANNEL = os.environ.get("APPROVAL_CHANNEL", "승인대기")

MODEL_DESIGN  = os.environ.get("MODEL_DESIGN",  "claude:claude-opus-4-8")
MODEL_REVIEW  = os.environ.get("MODEL_REVIEW",  "openai:gpt-5.5")
MODEL_RESEARCH = os.environ.get("MODEL_RESEARCH", "gemini:gemini-2.5-pro")

# 패턴 승격 임계값 (자료 ⑬: 3개 이상이면 스킬 후보)
PROMOTE_THRESHOLD = int(os.environ.get("PROMOTE_THRESHOLD", "3"))

SYSTEM_PROMPT = """당신은 더힐즈컴퍼니(The Heals Company)의 더힐즈 엔진 PM 에이전트 '지아'입니다.
회사 영문 표기는 The Heals (절대 The Hills 아님).
[국면 모드] 매 발주마다 🔵CREATE(추론우선)/🟢SCALE(효율) 먼저 제안. 애매하면 CREATE.
[PM] 계획-실행 분리: 계획(목적·단계·리스크·범위) 제안 후 승인 요청.
[카파시 4원칙] 1.모호하면 질문 2.단순함 3.수술하듯 최소변경 4.목표지향(검증기준 명시).
[태도] 무의미한 위로 배제. 린 제안. 진짜 목적 추론 + 대안 선제.
[비용] 완성도 우선이되 출력은 핵심 중심. 실제 실행 전 대표 승인."""

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
    if any(k in user_msg for k in research_kw): return "리서치"
    if any(k in user_msg for k in review_kw): return "검증"
    if any(k in user_msg for k in doc_kw): return "문서작성"
    if any(k in user_msg for k in code_kw): return "코드작업"
    return "일반"


def pick_model(task_type: str) -> str:
    if task_type == "리서치": return MODEL_RESEARCH
    if task_type == "검증": return MODEL_REVIEW
    return MODEL_DESIGN


def call_model(model_spec, system, user_msg, max_tokens=2048):
    provider, model_name = model_spec.split(":", 1)
    if provider == "claude":
        c = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        r = c.messages.create(model=model_name, max_tokens=max_tokens,
                              system=system, messages=[{"role": "user", "content": user_msg}])
        return r.content[0].text, f"입력 {r.usage.input_tokens}/출력 {r.usage.output_tokens}"
    elif provider == "openai":
        from openai import OpenAI
        c = OpenAI(api_key=OPENAI_API_KEY)
        r = c.chat.completions.create(model=model_name, max_completion_tokens=max_tokens,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user_msg}])
        u = r.usage
        return r.choices[0].message.content, f"입력 {u.prompt_tokens}/출력 {u.completion_tokens}"
    elif provider == "gemini":
        import google.generativeai as genai
        genai.configure(api_key=GEMINI_API_KEY)
        m = genai.GenerativeModel(model_name, system_instruction=system)
        return m.generate_content(user_msg).text, "토큰 정보 없음"
    return f"⚠️ 알 수 없는 프로바이더: {provider}", "—"


intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)


class ApprovalView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="승인", style=discord.ButtonStyle.success, emoji="✅")
    async def approve(self, i, b):
        for c in self.children: c.disabled = True
        now = datetime.datetime.now().strftime("%m-%d %H:%M")
        await i.response.edit_message(content=f"✅ **승인됨** ({now})", view=self)

    @discord.ui.button(label="수정", style=discord.ButtonStyle.primary, emoji="✏️")
    async def revise(self, i, b):
        for c in self.children: c.disabled = True
        await i.response.edit_message(content="✏️ **수정 요청됨**", view=self)

    @discord.ui.button(label="취소", style=discord.ButtonStyle.danger, emoji="❌")
    async def cancel(self, i, b):
        for c in self.children: c.disabled = True
        await i.response.edit_message(content="❌ **취소됨**", view=self)


# ── 스킬 승격 제안 버튼 (메모리 학습 핵심) ──
class PromoteView(discord.ui.View):
    def __init__(self, task_type):
        super().__init__(timeout=None)
        self.task_type = task_type

    @discord.ui.button(label="스킬로 승격", style=discord.ButtonStyle.success, emoji="✅")
    async def promote(self, i, b):
        for c in self.children: c.disabled = True
        examples = "\n".join(f"- {e}" for e in pattern_examples[self.task_type][:5])
        # 스킬 초안 생성 (Claude로)
        draft_prompt = (f"'{self.task_type}' 유형 작업이 반복 감지됨. 아래 실제 발주들을 보고, "
                        f"20_SKILLS에 넣을 재사용 스킬 초안을 마크다운으로 작성. "
                        f"헌법 제5조 승격 절차 준수, 간결하게.\n\n발주들:\n{examples}")
        try:
            draft, _ = call_model(MODEL_DESIGN, SYSTEM_PROMPT, draft_prompt, 1500)
        except Exception as e:
            draft = f"⚠️ 초안 생성 오류: {e}"
        await i.response.edit_message(
            content=f"✅ **스킬 승격 승인됨** — '{self.task_type}'\n\n"
                    f"**📄 스킬 초안:**\n{draft[:1400]}\n\n"
                    f"— — —\n"
                    f"💾 **저장 방법:** 위 초안을 검토 후 Claude Code(또는 옵시디언)로 "
                    f"`20_SKILLS/{self.task_type}-스킬.md`에 저장하세요. "
                    f"헌법 제5조에 따라 INDEX·LOG 등록도 함께.", view=self)

    @discord.ui.button(label="무시", style=discord.ButtonStyle.secondary, emoji="❌")
    async def ignore(self, i, b):
        for c in self.children: c.disabled = True
        await i.response.edit_message(content=f"❌ '{self.task_type}' 승격 보류됨", view=self)


@bot.event
async def on_ready():
    print(f"[더힐즈 엔진 봇 v0.5 메모리학습] 로그인: {bot.user}")


@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    if message.channel.name != ORDER_CHANNEL:
        return

    task_type = classify_task(message.content)
    model_spec = pick_model(task_type)

    async with message.channel.typing():
        try:
            answer, usage = call_model(model_spec, SYSTEM_PROMPT, message.content)
            answer += f"\n\n— — —\n🤖 모델: {model_spec} | 📊 {usage} | 🏷️ 유형: {task_type}"
        except Exception as e:
            answer = f"⚠️ 처리 오류 ({model_spec}): {e}"

    for idx in range(0, len(answer), 1900):
        await message.channel.send(answer[idx:idx + 1900])

    # ── 메모리 학습: 패턴 기록·감지 ──
    if task_type != "일반":
        pattern_counts[task_type] += 1
        pattern_examples[task_type].append(message.content[:100])

    approval_ch = discord.utils.get(message.guild.text_channels, name=APPROVAL_CHANNEL)
    if approval_ch:
        # 일반 승인 게이트
        await approval_ch.send(
            content=f"📋 **승인 대기** — \"{message.content[:150]}\"\n🤖 {model_spec}\n\n{answer[:1200]}",
            view=ApprovalView())

        # 패턴 감지 → 스킬 승격 제안 (임계값 도달 + 아직 제안 안 한 유형)
        if pattern_counts[task_type] >= PROMOTE_THRESHOLD and task_type not in promoted:
            promoted.add(task_type)
            # 판단 근거: 반복된 실제 작업 목록
            recent = pattern_examples[task_type][-PROMOTE_THRESHOLD:]
            examples_txt = "\n".join(f"   {n}. {e}" for n, e in enumerate(recent, 1))
            await approval_ch.send(
                content=(
                    f"🧠 **메모리 학습 — 패턴 감지**\n"
                    f"'{task_type}' 유형 작업이 **{pattern_counts[task_type]}회** 반복되었습니다.\n\n"
                    f"📊 **반복된 작업들:**\n{examples_txt}\n\n"
                    f"💡 **승격하면:** 다음 '{task_type}' 작업부터 이 스킬을 자동 참조 → "
                    f"일관성·속도 향상, 매번 처음부터 안 해도 됨\n"
                    f"⚠️ **보류하면:** 학습이 누적되지 않고 매번 새로 처리\n"
                    f"🛡️ 승인하셔도 자동 저장이 아니라 **초안만 생성**됩니다 "
                    f"(검토 후 직접 20_SKILLS에 저장 — 맥락 오염 차단)\n\n"
                    f"→ 재사용 스킬로 승격할까요?"
                ),
                view=PromoteView(task_type))


bot.run(DISCORD_TOKEN)
