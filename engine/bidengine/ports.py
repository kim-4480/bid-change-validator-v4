"""엔진이 바깥(apps/api adapters)에 요구하는 인터페이스.

엔진 코드는 이 Protocol만 의존한다. 구현체는 apps/api/app/adapters/ 에 둔다(실험·측정은
eval 쪽 구현을 쓴다). 엔진은 DB·파일 위치를 모른다.
"""
from __future__ import annotations

from typing import Protocol


class IndustryNameResolver(Protocol):
    """업종·등록 이름을 나라장터 업종코드(닫힌 어휘)로 바꾼다.

    공백·가운뎃점·쉼표 같은 표기 차이만 무시하고 **이름이 정확히 같을 때만** 코드를 준다.
    비슷한 이름을 추측하지 않는다 — 추측이 틀리면 닫힌 비교의 확신이 거짓이 된다.
    """

    def code_for(self, name: str) -> str | None: ...
