"""pytest 의 관례적 이름(test_*.py)을 쓴다 — 이것이 인식되지 않았다 (TS-025)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))
from convert import CURRENCIES, convert


class TestConvert:
    """PY-01: 허용된 통화만 변환한다"""

    def test_allowed(self):
        """PY-01.1: CURRENCIES 의 통화는 변환된다"""
        for c in CURRENCIES:
            assert convert(10, c) == 10

    def test_rejected(self):
        """PY-02.1: 없는 통화는 None 을 돌려준다"""
        assert convert(10, 'XXX') is None
