"""엔진 기억(조항 라벨·극성·조항 선택)의 이름공간.

기억 열쇠는 조항 원문으로 만든다. 그것만으로는 모델이나 프롬프트를 바꿔도 예전 모델의 답을 그대로
재사용한다 — gpt-6-luna 가 남긴 답이 glm 으로 바꾼 뒤에도 쓰인다. 기억을 "모델 | 프롬프트 판 |" 접두사로
감싸 이름공간을 나눈다. 접두사는 열쇠에만 붙고 답은 그대로다.
"""
from __future__ import annotations

from collections.abc import Iterator, MutableMapping
from typing import Any


class NamespacedMemory(MutableMapping[str, Any]):
    def __init__(self, inner: MutableMapping[str, Any], prefix: str) -> None:
        self._inner = inner
        self._prefix = prefix

    def _key(self, key: str) -> str:
        return f"{self._prefix}{key}"

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and self._key(key) in self._inner

    def __getitem__(self, key: str) -> Any:
        return self._inner[self._key(key)]

    def __setitem__(self, key: str, value: Any) -> None:
        self._inner[self._key(key)] = value

    def __delitem__(self, key: str) -> None:
        del self._inner[self._key(key)]

    def __iter__(self) -> Iterator[str]:
        n = len(self._prefix)
        return (key[n:] for key in list(self._inner) if key.startswith(self._prefix))

    def __len__(self) -> int:
        return sum(1 for _ in self)


def namespaced(memory: MutableMapping[str, Any] | None, namespace: str | None, version: str) -> MutableMapping[str, Any] | None:
    """namespace(대개 모델 이름)가 있으면 "namespace|version|" 으로 감싼다. 없으면 그대로(예전 동작)."""
    if memory is None or not namespace:
        return memory
    return NamespacedMemory(memory, f"{namespace}|{version}|")
