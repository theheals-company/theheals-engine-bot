"""모델 거버넌스 로더 (V2.5 A-2).

models.yaml(볼트 권위본의 런타임 사본)을 1회 파싱해 모듈 싱글턴으로 캐시하고,
역할명 → "provider:model" 매핑과 governance 라우팅 값을 제공한다.

원칙: yaml 부재/파싱오류 시 조용한 폴백 없이 명확한 예외를 던진다.
"""

from pathlib import Path

import yaml

# 봇 레포 루트의 models.yaml (core/ 의 부모). CWD와 무관하게 해석.
_YAML_PATH = Path(__file__).resolve().parent.parent / "models.yaml"

_CONFIG = None


def load_config(path=None):
    """models.yaml 을 파싱해 싱글턴 캐시에 적재하고 반환. 부재/오류 시 예외."""
    global _CONFIG
    p = Path(path) if path else _YAML_PATH
    if not p.exists():
        raise FileNotFoundError(f"models.yaml 없음: {p}")
    with open(p, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict) or "models" not in data:
        raise ValueError(f"models.yaml 파싱 실패 또는 'models' 섹션 없음: {p}")
    _CONFIG = data
    return _CONFIG


def get_config():
    """캐시된 설정 반환. 미적재면 1회 로드."""
    if _CONFIG is None:
        load_config()
    return _CONFIG


def get_model(role: str) -> str:
    """역할명(design/review/research/research_fallback) → "provider:model"."""
    models = get_config()["models"]
    if role not in models:
        raise KeyError(f"models.yaml 'models'에 역할 없음: {role}")
    return models[role]


def get_governance() -> dict:
    """governance 섹션 전체 반환."""
    return get_config().get("governance", {})


def get_principal() -> str:
    """escalate_to_principal.principal_model (bare id)."""
    return get_governance()["escalate_to_principal"]["principal_model"]


def get_fallback() -> str:
    """escalate_to_principal.fallback_model (bare id)."""
    return get_governance()["escalate_to_principal"]["fallback_model"]


def get_reviewer() -> str:
    """pick_reviewer 기본 리뷰어 → "provider:model"."""
    pr = get_governance()["pick_reviewer"]
    return f"{pr['default']}:{pr['model']}"
