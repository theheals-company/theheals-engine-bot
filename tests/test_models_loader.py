# tests/test_models_loader.py
# 더힐즈 엔진 — V2.5 A-2 모델 거버넌스 로더 스모크 테스트
# 원칙: 네트워크 0·토큰 0. models.yaml 로딩·라우팅 로직만 검증.

import pytest

from core import models_loader

pytestmark = pytest.mark.smoke


def test_loader_loads():
    """load_config() 정상 + get_model('design') == claude:claude-opus-4-8."""
    cfg = models_loader.load_config()
    assert cfg is not None and "models" in cfg
    assert models_loader.get_model("design") == "claude:claude-opus-4-8"


def test_reviewer():
    """get_reviewer()에 gpt-5.5 포함 (교차혈통 기본 리뷰어)."""
    assert "gpt-5.5" in models_loader.get_reviewer()


def test_principal():
    """get_principal() == claude-opus-4-8 (에스컬레이션 대상)."""
    assert models_loader.get_principal() == "claude-opus-4-8"
