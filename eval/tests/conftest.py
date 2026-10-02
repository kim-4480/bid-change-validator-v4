import sys
from pathlib import Path

# eval/runners 의 실행 스크립트를 테스트에서 import할 수 있게 한다.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runners"))
