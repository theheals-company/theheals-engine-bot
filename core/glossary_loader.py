"""용어사전 로더 (ORD-2026-0711-P2R 모듈4).

glossary.md(볼트 권위본의 런타임 사본)를 봇 기동 시 1회 로드해 모듈 싱글턴으로
캐싱한다. 매 LLM 호출마다 볼트를 재조회하지 않는다(비용 절감) — core/models_loader.py와
동일 패턴(로드 실패 시 조용한 폴백 없이 호출부가 판단하도록 None 반환).
"""

from pathlib import Path

# 봇 레포 루트의 glossary.md (core/ 의 부모). CWD와 무관하게 해석.
_GLOSSARY_PATH = Path(__file__).resolve().parent.parent / "glossary.md"

_CACHE: str | None = None


def load_glossary(path=None) -> str:
    """glossary.md를 읽어 캐시에 적재하고 반환. 부재 시 예외(models_loader.load_config와 동일 원칙)."""
    global _CACHE
    p = Path(path) if path else _GLOSSARY_PATH
    if not p.exists():
        raise FileNotFoundError(f"glossary.md 없음: {p}")
    _CACHE = p.read_text(encoding="utf-8")
    return _CACHE


def get_glossary() -> str | None:
    """캐시된 용어사전 반환. 로드된 적 없으면 None — 호출부가 '상태 미인지 모드'로 처리."""
    return _CACHE


def reset_cache() -> None:
    """테스트 격리용. 프로덕션 경로에서는 호출하지 않음."""
    global _CACHE
    _CACHE = None
