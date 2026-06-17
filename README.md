# theheals-engine-bot
더힐즈 엔진의 디스코드 관제 봇 (v0.1 기본형).

## 동작
- 디스코드 '발주' 채널의 메시지를 받아 Claude로 응답.

## 필요한 환경변수 (Render에 입력, 코드에 적지 않음)
- DISCORD_TOKEN     : 디스코드 봇 토큰
- ANTHROPIC_API_KEY : Anthropic API 키
- ORDER_CHANNEL     : (선택) 발주 채널 이름, 기본 '발주'
- CLAUDE_MODEL      : (선택) 모델명, 기본 claude-opus-4-8

## 배포
- Render에서 이 저장소를 Background Worker로 연결.
- Start Command: python bot.py
