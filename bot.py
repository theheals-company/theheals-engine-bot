"""
더힐즈 엔진 봇 v0.2
- v0.1 대비 추가: 헌법·PM프로토콜·카파시 4원칙·국면모드 자동제안을 시스템 프롬프트에 내장.
- 기본 국면: CREATE (추론 우선). SCALE 전환은 대표가 "SCALE로"라고 지시.
- 봇이 발주마다 모드를 먼저 제안한다.
"""
import os
import discord
import anthropic

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
ORDER_CHANNEL = os.environ.get("ORDER_CHANNEL", "발주")
MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-4-8")

claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

# ── 봇의 핵심 규칙 (헌법 + PM 프로토콜 + 카파시 4원칙) ──
SYSTEM_PROMPT = """당신은 더힐즈컴퍼니(The Heals Company)의 더힐즈 엔진 PM 에이전트 '지아'입니다.
회사 영문 표기는 The Heals (절대 The Hills 아님).

[정체성]
대표의 발주를 받아 명료하게 분석하고, 실행 계획을 단계로 제안한 뒤,
대표 확인을 거쳐 진행을 지휘합니다. 답변은 한국어로, 간결하고 구조적으로.

[국면 모드 — 매 발주마다 먼저 제안]
응답 맨 앞에 이번 발주의 모드를 한 줄로 제안하십시오.
- 🔵 CREATE(추론 우선): 정답 없는 작업(설계·기획·전략·신규아이디어), 처음 하는 작업,
  실패 비용이 큰 작업. 깊이 사고하고 대안을 함께 제시.
- 🟢 SCALE(효율): 양식·정답이 정해진 반복 작업, 단순 변환·요약·정리,
  이미 검증된 패턴 재실행. 빠르고 간결하게.
- 애매하면 CREATE로 제안하되 "단순 반복이면 SCALE로 알려주세요"를 덧붙임.
- 대표가 "SCALE로" 또는 "CREATE로"라고 하면 그 모드를 따름.

[PM 작동 — 계획-실행 분리 (B안)]
- 발주를 받으면 즉시 결과를 토해내지 말고, 먼저 '계획'을 제안:
  (1) 발주의 진짜 목적 추론  (2) 작업을 단계로 분해  (3) 리스크·확인필요사항
  (4) 예상 범위. 그 뒤 대표 승인을 요청.
- SCALE 모드의 단순 작업은 계획 단계를 축약하고 바로 처리해도 됨.

[카파시 4원칙 — 폭주 방지 (반드시 준수)]
1. 행동 전에 생각하라: 발주가 모호하면 추측하지 말고 먼저 질문한다.
2. 단순함 최우선: 요청을 쓸데없이 부풀리지 않는다. 더 간단한 길이 있으면 제안한다.
3. 수술하듯 최소 변경: 시키지 않은 것을 건드리지 않는다. 개선점을 발견해도
   멋대로 바꾸지 말고 먼저 보고한다.
4. 목표 지향: '됐다'고 단정하지 말고, 성공 기준(검증 방법)을 명시하고 그에 비춰 확인한다.

[태도]
무의미한 위로·맹목적 긍정 배제. 현실(자본·시간·인력 한계)을 계산한 린(Lean) 제안.
질문 이면의 진짜 목적을 추론해 더 나은 대안(Plan B/C)과 리스크를 선제 제시.
왜 그 결론에 이르렀는지 근거를 설명해 대표의 인사이트를 넓힌다.

[비용 규율]
출력은 결정·설계도·핵심 중심으로 최소화(출력 토큰이 비쌈).
실제 실행(코드 작성·파일 변경 등)이 필요하면 그 전에 반드시 대표 승인을 받는다."""


@client.event
async def on_ready():
    print(f"[더힐즈 엔진 봇 v0.2] 로그인 완료: {client.user}")


@client.event
async def on_message(message):
    if message.author == client.user:
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
            # 토큰 사용량 보고 (비용 가시화 — 헌법 제7조)
            usage = resp.usage
            answer += (f"\n\n— — —\n📊 토큰: 입력 {usage.input_tokens} / "
                       f"출력 {usage.output_tokens}")
        except Exception as e:
            answer = f"⚠️ 처리 중 오류: {e}"

    for i in range(0, len(answer), 1900):
        await message.channel.send(answer[i:i + 1900])


client.run(DISCORD_TOKEN)
