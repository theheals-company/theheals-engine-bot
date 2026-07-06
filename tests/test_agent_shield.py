# tests/test_agent_shield.py
# 더힐즈 엔진 — V2.5 B-2 AgentShield 스모크 테스트
# 원칙: 네트워크 0·토큰 0. shield_check 로직 + save_skill_to_vault AND 체이닝만 검증.

import pytest

import vault_writer

pytestmark = pytest.mark.smoke


def test_shield_blocks_code_pattern_in_py():
    """가드: .py 파일 + 위험 코드패턴 → 차단(False)."""
    ok, reason = vault_writer.shield_check("import os\nfrom evil import x\n", "20_SKILLS/evil.py")
    assert ok is False
    assert "AgentShield" in reason


def test_shield_exempts_md_documents():
    """가드: .md 문서는 코드패턴이 있어도 면제(True) — 오탐 방지."""
    ok, reason = vault_writer.shield_check("문서에 eval( 가 본문에 있어도 .md는 면제", "20_SKILLS/doc.md")
    assert ok is True
    assert "면제" in reason


def test_save_and_chains_shield_for_code_file():
    """가드: save_skill_to_vault가 .py+코드패턴을 AND 체이닝으로 거부(네트워크 도달 전)."""
    with pytest.raises(ValueError, match="AgentShield"):
        vault_writer.save_skill_to_vault("10_WIKI/오답노트/x.py", "subprocess.run(['rm','-rf'])", "msg")
