"""엔진이 바깥(apps/api adapters)에 요구하는 인터페이스.

엔진 코드는 이 Protocol만 의존한다. 구현체는 apps/api/app/adapters/ 에 둔다.
"""
from __future__ import annotations

from typing import Protocol
