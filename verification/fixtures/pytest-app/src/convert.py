"""픽스처용 최소 모듈 — 하네스가 호출하지 않는다 (deadcode 감사에서 제외됨)."""

CURRENCIES = ['KRW', 'USD', 'EUR']


def convert(amount, currency):
    if currency not in CURRENCIES:
        return None
    return amount
