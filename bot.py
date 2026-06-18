"""
더힐즈 엔진 봇 v0.4 (멀티 프로바이더)
- v0.3 + 모델 추상화 레이어: Claude / OpenAI GPT / Google Gemini 자유 교체.
- 작업 유형에 따라 프로바이더 자동 선택 (설계=Claude, 검증=GPT, 리서치=Gemini).
- "모델은 부품" 원칙을 코드로 완성. 한 곳이 막혀도 즉시 교체.
- 승인 게이트·카파시 4원칙·국면모드 모두 유지.
"""
import os
import datetime
import discord
import anthropic

# ── 비밀값 (Render 환경변수) ──
DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
ORDER_CHANNEL = os.environ.get("ORDER_CHANNEL", "발주")
APPROVAL_CHANNEL = os.environ.get("APPROVAL_CHANNEL", "승인대기")

# ── 역할별 모델 배정 (models.yaml 대응 — 여기 또는 환경변수로 변경) ──
# 형식: "provider:model"
MODEL_DESIGN  = os.environ.get("MODEL_DESIGN",  "claude:claude-opus-4-8")    # 설계·전략·기본
MODEL_REVIEW  = os.environ.get("MODEL_REVIEW",  "openai:gpt-5.5")            # 교차 검증
MODEL_RESEARCH = os.environ.get("MODEL_RESEARCH", "gemini:gemini-2.5-pro")  # 리서치·요약

SYSTEM_PROMPT = """당신은 더힐즈컴퍼니(The Heals Company)의 더힐즈 엔진 PM 에이전트 '지아'입니다.
회사 영문 표기는 The Heals (절대 The Hills 아님).

[국면 모드 — 매 발주마다 먼저 제안]
- 🔵 CREATE(추론 우선): 정답없는 작업·처음 작업·실패비용 큰 작업.
- 🟢 SCALE(효율): 양식 정해진 반복·단순 변환. 애매하면 CREATE 제안.

[PM — 계획-실행 분리] 발주 받으면 먼저 계획(목적·단계분해·리스크·범위) 제안 후 승인 요청.
[카파시 4원칙] 1.모호하면 질문 2.단순함 3.수술하듯 최소변경 4.목표지향(검증기준 명시).
[태도] 무의미한 위로 배제. 린(Lean) 제안. 진짜 목적 추론 + 대안 선제 제시.
[비용] 출력 최소화. 실제 실행 전 대표 승인."""


# ── 모델 추상화 레이어: provider별 호출을 하나로 통일 ──
def call_model(model_spec: str, system: str, user_msg: str, max_tokens: int = 2048):
    """model_spec = 'provider:model'. 어느 회사든 같은 인터페이스로 호출."""
    provider, model_name = model_spec.split(":", 1)

    if provider == "claude":
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model=model_name, max_tokens=max_tokens,
            system=system, messages=[{"role": "user", "content": user_msg}],
        )
        text = resp.content[0].text
        usage = f"입력 {resp.usage.input_tokens} / 출력 {resp.usage.output_tokens}"
        return text, usage

    elif provider == "openai":
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)
        resp = client.chat.completions.create(
            model=model_name, max_tokens=max_tokens,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user_msg}],
        )
        text = resp.choices[0].message.content
        u = resp.usage
        usage = f"입력 {u.prompt_tokens} / 출력 {u.completion_tokens}"
        return text, usage

    elif provider == "gemini":
        import google.generativeai as genai
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel(model_name, system_instruction=system)
        resp = model.generate_content(user_msg)
        text = resp.text
        usage = "토큰 정보 제공안함"
        return text, usage

    else:
        return f"⚠️ 알 수 없는 프로바이더: {provider}", "—"


# ── 작업 유형 판단 (간단 키워드 라우팅) ──
def pick_model(user_msg: str) -> str:
    msg = user_msg.lower()
    research_kw = ["조사", "찾아", "리서치", "동향", "검색", "최신", "뉴스", "시장"]
    review_kw = ["검증", "검수", "리뷰", "교차", "확인해", "맞는지", "오류"]
    if any(k in user_msg for k in research_kw):
        return MODEL_RESEARCH
    if any(k in user_msg for k in review_kw):
        return MODEL_REVIEW
    return MODEL_DESIGN  # 기본: 설계·전략 = Claude


intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)


class ApprovalView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="승인", style=discord.ButtonStyle.success, emoji="✅")
    async def approve(self, interaction, button):
        now = datetime.datetime.now().strftime("%m-%d %H:%M")
        for c in self.children:
            c.disabled = True
        await interaction.response.edit_message(
            content=f"✅ **승인됨** ({now}) — 실행 단계로 진행합니다.", view=self)

    @discord.ui.button(label="수정", style=discord.ButtonStyle.primary, emoji="✏️")
    async def revise(self, interaction, button):
        for c in self.children:
            c.disabled = True
        await interaction.response.edit_message(
            content="✏️ **수정 요청됨** — #발주에 보완 사항을 알려주세요.", view=self)

    @discord.ui.button(label="취소", style=discord.ButtonStyle.danger, emoji="❌")
    async def cancel(self, interaction, button):
        for c in self.children:
            c.disabled = True
        await interaction.response.edit_message(
            content="❌ **취소됨** — 이 발주는 진행하지 않습니다.", view=self)


@bot.event
async def on_ready():
    print(f"[더힐즈 엔진 봇 v0.4 멀티프로바이더] 로그인: {bot.user}")


@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    if message.channel.name != ORDER_CHANNEL:
        return

    model_spec = pick_model(message.content)
    async with message.channel.typing():
        try:
            answer, usage = call_model(model_spec, SYSTEM_PROMPT, message.content)
            answer += f"\n\n— — —\n🤖 모델: {model_spec}\n📊 토큰: {usage}"
        except Exception as e:
            answer = f"⚠️ 처리 중 오류 ({model_spec}): {e}"

    for i in range(0, len(answer), 1900):
        await message.channel.send(answer[i:i + 1900])

    approval_ch = discord.utils.get(message.guild.text_channels, name=APPROVAL_CHANNEL)
    if approval_ch:
        await approval_ch.send(
            content=f"📋 **승인 대기** — 발주: \"{message.content[:200]}\"\n"
                    f"🤖 처리 모델: {model_spec}\n\n{answer[:1400]}\n\n승인하시겠습니까?",
            view=ApprovalView())


bot.run(DISCORD_TOKEN)
