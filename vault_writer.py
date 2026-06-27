# vault_writer.py — 길 B 영구기억: 봇 → GitHub 볼트 저장 (20_SKILLS 전용)
import base64
import datetime
import logging
import os
import re

import requests

logger = logging.getLogger(__name__)

ALLOWED_PREFIX = ("20_SKILLS/", "10_WIKI/오답노트/")  # 가드레일1: 허용 경로 목록
SECRET_PATTERNS = [  # 가드레일3: 비밀키 평문 차단
    r"github_pat_\w+",
    r"ghp_\w+",
    r"sk-[A-Za-z0-9]{20,}",  # OpenAI
    r"AIza[A-Za-z0-9_\-]{30,}",  # Google
]

# 가드레일4 (AgentShield, V2.5 B-2): 외부 코드 스킬 위험패턴 차단
SHIELD_PATTERNS = [
    r"from\s+\w+\s+import",
    r"pip\s+install",
    r"subprocess",
    r"__import__",
    r"eval\(",
    r"exec\(",
]
# 코드 파일만 shield 적용. 자체생성 .md 등 문서는 면제(오탐 방지).
CODE_EXTS = (".py", ".js", ".ts", ".sh", ".rb", ".pl", ".ps1", ".bat")


def _check_secrets(text: str):
    for p in SECRET_PATTERNS:
        if re.search(p, text):
            raise ValueError("거부: 비밀키 패턴 감지 — 볼트 평문 저장 금지(헌법)")


def shield_check(content: str, filename: str):
    """AgentShield: 외부 코드 스킬 위험패턴 차단. 반환 (ok: bool, reason: str).
    .md 등 비코드 파일은 면제(자체생성 문서는 코드패턴 없어 정상 통과)."""
    if not filename.lower().endswith(CODE_EXTS):
        return True, "면제(비코드 파일)"
    for p in SHIELD_PATTERNS:
        if re.search(p, content):
            return False, f"AgentShield 차단: 외부 코드패턴 감지 [{p}] — {filename}"
    return True, "통과(코드 파일, 위험패턴 없음)"


def save_skill_to_vault(path: str, content: str, message: str) -> dict:
    # 가드레일1: 화이트리스트
    if not path.startswith(ALLOWED_PREFIX):
        raise ValueError(f"거부: {ALLOWED_PREFIX} 외 경로 쓰기 금지 → {path}")
    # 가드레일2: 경로 탈출 차단
    if ".." in path or path.startswith("/"):
        raise ValueError(f"거부: 비정상 경로 → {path}")
    # 가드레일4 (AgentShield): 코드 파일 위험패턴 차단 (.md 등 문서는 면제). 기존 가드와 AND 체이닝.
    ok, reason = shield_check(content, path)
    if not ok:
        raise ValueError(f"거부: {reason}")
    _check_secrets(content)

    token = os.environ["GITHUB_TOKEN"]  # Render 환경변수에서만
    repo = os.environ["VAULT_REPO"]  # theheals-company/theheals-engine-vault
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}

    # 기존 파일이면 SHA 확보(업데이트), 없으면 신규 생성
    sha = None
    r = requests.get(url, headers=headers, timeout=15)
    if r.status_code == 200:
        sha = r.json()["sha"]

    body = {"message": message, "content": base64.b64encode(content.encode()).decode()}
    if sha:
        body["sha"] = sha

    # S2 인라인 가드: sensitivity:S2 감지 시 PUT 차단
    if "sensitivity: s2" in content.lower():
        logger.warning("S2 content blocked: %s", path)
        return {"ok": False, "reason": "S2_BLOCKED", "path": path}

    resp = requests.put(url, headers=headers, json=body, timeout=15)
    resp.raise_for_status()
    return {"ok": True, "path": path, "url": resp.json()["content"]["html_url"]}


def process_cancel_note(task_name: str, cause_raw: str, fix_raw: str) -> tuple:
    """취소 오답노트 순수 로직. 반환: (content, path, note_msg)"""
    cause = cause_raw.strip() or "(취소 사유 미입력)"
    fix = fix_raw.strip() or "(취소 사유 미입력)"
    content = build_mistake_note(task_name, cause, fix)
    today = datetime.date.today().isoformat()
    path = f"10_WIKI/오답노트/{today}-{slugify(task_name)}.md"
    try:
        result = save_skill_to_vault(
            path=path,
            content=content,
            message=f"오답노트: {task_name}",
        )
        if result["ok"]:
            note_msg = f"📝 오답노트 기록됨: {path}"
        else:
            note_msg = f"⚠️ 오답노트 기록 실패: {result['reason']}"
    except Exception as e:
        note_msg = f"⚠️ 오답노트 기록 실패: {e}"
    return content, path, note_msg


def slugify(text: str) -> str:
    """공백→하이픈, 특수문자 제거, 한글 허용."""
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"\s+", "-", text.strip())
    return text[:50]


def build_mistake_note(task: str, cause: str, fix: str) -> str:
    today = datetime.date.today().isoformat()
    return (
        f"---\nsensitivity: S0\ndate: {today}\n---\n"
        f"# 오답노트: {task}\n"
        f"- 날짜: {today}\n"
        f"- 작업: {task}\n"
        f"- 원인: {cause}\n"
        f"- 방지책: {fix}\n"
    )
