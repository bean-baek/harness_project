"""unittest 태그 규약 — 기능 ID 는 **docstring** 에 넣는다.

파이썬 식별자에 하이픈을 쓸 수 없으므로 `def test_UT-01_...` 은 문법 오류다.
그래서 함수 이름이 아니라 `shortDescription()`(docstring 첫 줄)이 테스트 이름이 된다.
pytest 와 같은 이유이고, `UnittestRunner` 의 수집기가 그 값을 쓴다.

`CURRENCIES` 를 **import 해서 순회**한다 — 통화를 손으로 적으면 목록이 바뀔 때
테스트가 함께 틀어지지 않는다 (증거 독립성, TS-013/TS-020).
"""
import unittest

from src.wallet import CURRENCIES, convert


class ConvertTest(unittest.TestCase):
    """UT-01: 선언된 통화만 변환하고 나머지는 거부한다"""

    def test_declared_currencies_all_convert(self):
        """UT-01.1: CURRENCIES 에 있는 통화는 모두 변환된다"""
        for code in CURRENCIES:
            self.assertGreater(convert(10, code), 0)

    def test_unknown_currency_rejected(self):
        """UT-01.2: 목록에 없는 통화는 거부된다"""
        with self.assertRaises(ValueError):
            convert(10, 'JPY')


class AmountTest(unittest.TestCase):
    """UT-02: 0 이하의 금액은 거부한다"""

    def test_zero_rejected(self):
        """UT-02.1: 0 은 거부된다"""
        with self.assertRaises(ValueError):
            convert(0, 'KRW')

    def test_negative_rejected(self):
        """UT-02.2: 음수는 거부된다"""
        with self.assertRaises(ValueError):
            convert(-1, 'KRW')
