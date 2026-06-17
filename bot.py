"""
더힐즈 엔진 봇 v0.1 (기본형)
- #발주 채널의 메시지를 받아 Claude(Anthropic API)로 응답한다.
- 헌법·PM 프로토콜의 전체 7단계는 이후 단계적으로 붙인다.
- 오늘 목표: 봇이 24시간 살아서 응답하는 것.
"""
import os
import discord
import anthropic

# ── 환경변수에서 비밀값 읽기 (코드에 직접 안 적음 — 헌법 제9조) ──
DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
# 발주를 받을 채널 이름 (기본값 '발주')
ORDER_CHANNEL = os.environ.get("ORDER_CHANNEL", "발주")
# 사용할 모델 (models.yaml과 별개로 환경변수로 임시 지정)
MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-4-8")

# ── Claude 클라이언트 ──
claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# ── 디스코드 클라이언트 (메시지 내용 읽기 권한 필요) ──
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

# ── 봇의 기본 페르소나 (PM 레이어 축약본) ──
SYSTEM_PROMPT = """당신은 더힐즈컴퍼니(The Heals Company)의 더힐즈 엔진 PM 에이전트입니다.
대표의 발주를 받아 명료하게 답합니다. 현재는 기본형으로, 받은 발주를 이해하고
무엇을 할지 계획을 제안하는 역할을 합니다. 답변은 한국어로, 간결하고 구조적으로.
실행이 필요한 작업은 단계로 분해해 제안하되, 실제 실행 전 대표 확인을 요청합니다."""


@client.event
async def on_ready():
    print(f"[더힐즈 엔진 봇] 로그인 완료: {client.user}")


@client.event
async def on_message(message):
    # 봇 자신의 메시지는 무시
    if message.author == client.user:
        return
    # '발주' 채널의 메시지에만 반응
    if message.channel.name != ORDER_CHANNEL:
        return

    # 타이핑 표시 후 Claude 호출
    async with message.channel.typing():
        try:
            resp = claude.messages.create(
                model=MODEL,
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": message.content}],
            )
            answer = resp.content[0].text
        except Exception as e:
            answer = f"⚠️ 처리 중 오류: {e}"

    # 디스코드 메시지 길이 제한(2000자) 대응
    for i in range(0, len(answer), 1900):
        await message.channel.send(answer[i:i + 1900])


client.run(DISCORD_TOKEN)
