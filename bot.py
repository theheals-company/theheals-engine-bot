"""
더힐즈 엔진 봇 v0.3
- v0.2 + 승인 게이트(버튼): 봇이 계획을 #승인대기 채널에 올리고
  [✅승인][✏️수정][❌취소] 버튼으로 대표가 결재.
- 기본 국면: CREATE. 발주마다 모드 자동 제안.
- 실제 실행(코드작성 등)은 3주차 하네스 연결 후. 지금은 승인 기록까지.
"""
import os
import datetime
import discord
import anthropic

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
ORDER_CHANNEL = os.environ.get("ORDER_CHANNEL", "발주")
APPROVAL_CHANNEL = os.environ.get("APPROVAL_CHANNEL", "승인대기")
MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-4-8")

claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)

SYSTEM_PROMPT = """당신은 더힐즈컴퍼니(The Heals Company)의 더힐즈 엔진 PM 에이전트 '지아'입니다.
회사 영문 표기는 The Heals (절대 The Hills 아님).

[정체성] 대표의 발주를 받아 분석하고, 실행 계획을 단계로 제안한 뒤 대표 확인을 거쳐
진행을 지휘합니다. 답변은 한국어로 간결하고 구조적으로.

[국면 모드 — 매 발주마다 먼저 제안]
응답 맨 앞에 이번 발주의 모드를 한 줄로 제안:
- 🔵 CREATE(추론 우선): 정답없는 작업(설계·기획·전략·신규아이디어), 처음 작업, 실패비용 큰 작업.
- 🟢 SCALE(효율): 양식·정답 정해진 반복, 단순 변환·요약, 검증된 패턴 재실행.
- 애매하면 CREATE 제안 + "단순 반복이면 SCALE로 알려주세요".
- 대표가 "SCALE로"/"CREATE로" 하면 그 모드를 따름.

[PM 작동 — 계획-실행 분리]
발주를 받으면 즉시 실행하지 말고 먼저 '계획'을 제안:
(1) 발주의 진짜 목적 (2) 단계 분해 (3) 리스크·확인필요 (4) 예상 범위. 그 뒤 승인 요청.
계획 끝에는 항상 '[승인 요청] 위 계획으로 진행할까요?'를 붙인다.

[카파시 4원칙 — 폭주 방지]
1. 모호하면 추측 말고 질문한다.
2. 단순함 최우선. 쓸데없이 부풀리지 않는다.
3. 수술하듯 최소 변경. 시키지 않은 것 건드리지 않고, 개선점은 먼저 보고.
4. 목표 지향. 성공 기준(검증법)을 명시하고 그에 비춰 확인.

[태도] 무의미한 위로·맹목 긍정 배제. 린(Lean) 제안. 진짜 목적 추론 + 대안(Plan B/C) 선제 제시.
[비용] 출력은 핵심 중심 최소화. 실제 실행 전 반드시 대표 승인."""


# ── 승인 버튼 View ──
class ApprovalView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)  # 버튼이 만료되지 않음

    @discord.ui.button(label="승인", style=discord.ButtonStyle.success, emoji="✅")
    async def approve(self, interaction, button):
        now = datetime.datetime.now().strftime("%m-%d %H:%M")
        for child in self.children:
            child.disabled = True  # 클릭 후 버튼 비활성
        await interaction.response.edit_message(
            content=f"✅ **승인됨** ({now}) — 실행 단계로 진행합니다.\n"
                    f"(실제 실행 기능은 다음 단계에서 연결됩니다)",
            view=self,
        )

    @discord.ui.button(label="수정", style=discord.ButtonStyle.primary, emoji="✏️")
    async def revise(self, interaction, button):
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            content="✏️ **수정 요청됨** — #발주 채널에 보완 사항을 알려주세요.",
            view=self,
        )

    @discord.ui.button(label="취소", style=discord.ButtonStyle.danger, emoji="❌")
    async def cancel(self, interaction, button):
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            content="❌ **취소됨** — 이 발주는 진행하지 않습니다.",
            view=self,
        )


@bot.event
async def on_ready():
    print(f"[더힐즈 엔진 봇 v0.3] 로그인 완료: {bot.user}")


@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    if message.channel.name != ORDER_CHANNEL:
        return

    async with message.channel.typing():
        try:
            resp = claude.messages.create(
                model=MODEL,
                max_tokens=2048,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": message.content}],
            )
            answer = resp.content[0].text
            u = resp.usage
            answer += f"\n\n— — —\n📊 토큰: 입력 {u.input_tokens} / 출력 {u.output_tokens}"
        except Exception as e:
            answer = f"⚠️ 처리 중 오류: {e}"

    # 1) 발주 채널에 계획 응답
    for i in range(0, len(answer), 1900):
        await message.channel.send(answer[i:i + 1900])

    # 2) 승인대기 채널에 버튼과 함께 게시
    approval_ch = discord.utils.get(message.guild.text_channels, name=APPROVAL_CHANNEL)
    if approval_ch:
        summary = answer[:1500]
        await approval_ch.send(
            content=f"📋 **승인 대기** — 발주: \"{message.content[:200]}\"\n\n"
                    f"{summary}\n\n위 계획을 승인하시겠습니까?",
            view=ApprovalView(),
        )


bot.run(DISCORD_TOKEN)
