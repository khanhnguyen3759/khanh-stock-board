"""MA cross — golden/death cross trên giá đóng cửa (VND)."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

BUY, SELL, HOLD = "buy", "sell", "hold"


@dataclass
class Signal:
    action: str
    symbol: str
    price: float
    reason: str = ""


class MACrossStrategy:
    name = "ma_cross"

    def __init__(self, fast: int = 10, slow: int = 20):
        if fast >= slow:
            raise ValueError("fast phải nhỏ hơn slow.")
        self.fast, self.slow = fast, slow

    def signal(self, symbol: str, df: pd.DataFrame, holding: bool) -> Signal:
        price = float(df["close"].iloc[-1])
        if len(df) < self.slow + 1:
            return Signal(HOLD, symbol, price, "Chưa đủ dữ liệu.")
        close = df["close"]
        fast_ma = close.rolling(self.fast).mean()
        slow_ma = close.rolling(self.slow).mean()
        fn, fp = fast_ma.iloc[-1], fast_ma.iloc[-2]
        sn, sp = slow_ma.iloc[-1], slow_ma.iloc[-2]
        if fp <= sp and fn > sn and not holding:
            return Signal(BUY, symbol, price,
                          f"Golden cross: MA{self.fast} {fn:,.0f} > MA{self.slow} {sn:,.0f}")
        if fp >= sp and fn < sn and holding:
            return Signal(SELL, symbol, price,
                          f"Death cross: MA{self.fast} {fn:,.0f} < MA{self.slow} {sn:,.0f}")
        return Signal(HOLD, symbol, price, "Không có giao cắt mới.")
