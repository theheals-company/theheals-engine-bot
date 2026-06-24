# vault_writer.py — 길 B 영구기억: 봇 → GitHub 볼트 저장 (20_SKILLS 전용)
import base64
import os
import re

import requests

ALLOWED_PREFIX = "20_SKILLS/"  # 가드레일1: 이 경로만 쓰기 허용
SECRET_PATTERNS = [  # 가드레일3: 비밀키 평문 차단
    r"github_pat_\w+",
    r"ghp_\w+",
    r"sk-[A-Za-z0-9]{20,}",  # OpenAI
    r"AIza[A-Za-z0-9_\-]{30,}",  # Google
]


def _check_secrets(text: str):
    for p in SECRET_PATTERNS:
        if re.search(p, text):
            raise ValueError("거부: 비밀키 패턴 감지 — 볼트 평문 저장 금지(헌법)")


def save_skill_to_vault(path: str, content: str, message: str) -> dict:
    # 가드레일1: 화이트리스트
    if not path.startswith(ALLOWED_PREFIX):
        raise ValueError(f"거부: {ALLOWED_PREFIX} 외 경로 쓰기 금지 → {path}")
    # 가드레일2: 경로 탈출 차단
    if ".." in path or path.startswith("/"):
        raise ValueError(f"거부: 비정상 경로 → {path}")
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

    resp = requests.put(url, headers=headers, json=body, timeout=15)
    resp.raise_for_status()
    return {"ok": True, "path": path, "url": resp.json()["content"]["html_url"]}
