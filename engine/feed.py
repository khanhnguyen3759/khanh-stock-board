"""Data feed — giá cổ phiếu VN qua vnstock (nguồn VCI), normalize về VND.

vnstock trả giá theo nghìn đồng (ACB 22.35 = 22.350đ) -> nhân 1000 ra VND.
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

PRICE_UNIT = 1_000
_PRICE_COLS = ("open", "high", "low", "close")


class DataFeed:
    def __init__(self, source: str = "VCI"):
        self._source = source

    def _quote(self, symbol: str):
        from vnstock.api.quote import Quote
        return Quote(symbol=symbol, source=self._source)

    def history(self, symbol: str, days: int = 150, interval: str = "1D") -> pd.DataFrame:
        end = date.today().isoformat()
        start = (date.today() - timedelta(days=days)).isoformat()
        df = self._quote(symbol).history(start=start, end=end, interval=interval)
        if df is None or df.empty:
            raise RuntimeError(f"Không lấy được dữ liệu giá cho {symbol}.")
        df = df.copy()
        for col in _PRICE_COLS:
            if col in df.columns:
                df[col] = df[col] * PRICE_UNIT
        return df

    def latest_price(self, symbol: str) -> float:
        return float(self.history(symbol, days=10)["close"].iloc[-1])
