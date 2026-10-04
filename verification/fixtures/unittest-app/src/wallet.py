"""unittest 픽스처의 대상 코드.

이 픽스처는 **런너 실행 계층을 CI 에서 돌리기 위해** 있다 (TS-031). 설치가 0이므로
(`unittest` 는 stdlib) jest 외에 처음으로 실제 실행·결과 파싱·커버리지까지 CI 가
확인하는 파이썬 경로다.

`never_reached` 는 **일부러 테스트가 호출하지 않는다** — TS-026 의 미실행 줄 필터가
파이썬 경로에서도 작동하는지 고정하기 위한 자리다.
"""

CURRENCIES = ['KRW', 'USD', 'EUR']

RATES = {'KRW': 1, 'USD': 1300, 'EUR': 1400}


def convert(amount, to):
    """금액을 통화로 환산한다. 선언되지 않은 통화와 0 이하 금액은 거부한다."""
    if to not in CURRENCIES:
        raise ValueError(f'unknown currency: {to}')
    if amount <= 0:
        raise ValueError('amount must be positive')
    return amount * RATES[to]


def never_reached(flag):
    """어떤 테스트도 이 함수를 호출하지 않는다 (TS-026 고정용).

    여기에 변이를 넣으면 **생존이 보장된다** — 증거가 지나가지 않기 때문이다.
    줄 지도 필터가 없으면 그 생존이 '증거의 구멍'으로 오계수된다.
    """
    if flag is True:
        return 'yes'
    return 'no'
