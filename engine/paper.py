"""Vòng lặp paper: data -> strategy -> risk gate -> executor -> state.

Cấu hình qua biến môi trường (không secret):
  WATCHLIST, PAPER_CAPITAL, MIN_ORDER_VALUE, MA_FAST, MA_SLOW, DB_PATH
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")


def today_vn() -> str:
    """Ngày hôm nay theo giờ VN (yyyy-mm-dd)."""
    return datetime.now(tz=VN_TZ).date().isoformat()

from .executor import PaperExecutor, buy_fees
from .feed import DataFeed
from .risk import LOT_SIZE, check_buy
from .store import Store
from .strategy import BUY, SELL, MACrossStrategy

LOOKBACK_DAYS = 150


@dataclass
class Config:
    watchlist: tuple[str, ...]
    paper_capital: int
    min_order_value: int
    ma_fast: int
    ma_slow: int
    db_path: str

    @classmethod
    def load(cls) -> "Config":
        wl = tuple(s.strip().upper()
                   for s in os.environ.get("WATCHLIST", "ACB,FPT,MWG").split(",") if s.strip())
        return cls(
            watchlist=wl,
            paper_capital=int(os.environ.get("PAPER_CAPITAL", "200000000")),
            min_order_value=int(os.environ.get("MIN_ORDER_VALUE", "1000000")),
            ma_fast=int(os.environ.get("MA_FAST", "10")),
            ma_slow=int(os.environ.get("MA_SLOW", "20")),
            db_path=os.environ.get("DB_PATH", "data/paper.db"),
        )


def _bar_date(df: pd.DataFrame) -> str:
    return str(df["time"].iloc[-1])[:10]


def _desired_qty(cfg: Config, price: float) -> int:
    if price <= 0:
        return 0
    target = cfg.paper_capital / max(len(cfg.watchlist), 1)
    return (int(target // price) // LOT_SIZE) * LOT_SIZE


def process(cfg, store, strategy, executor, symbol, df) -> dict:
    """Xử lý 1 mã trên 1 khung dữ liệu. LUÔN trả dict mô tả quyết định + lý do
    (kể cả HOLD) -> nguồn cho nhật ký quyết định. KHÔNG tự ghi DB (để tái dùng)."""
    pos = store.get_position(symbol)
    holding = pos is not None
    sig = strategy.signal(symbol, df, holding)
    price, bar = sig.price, _bar_date(df)
    ev = {"symbol": symbol, "bar": bar, "price": price,
          "action": "hold", "reason": sig.reason}

    if sig.action == BUY:
        qty = _desired_qty(cfg, price)
        fees = buy_fees(price, qty) if qty else 0.0
        decision = check_buy(price=price, qty=qty, fees=fees,
                             available_cash=store.get_cash(),
                             max_capital=cfg.paper_capital, deployed=store.deployed(),
                             min_order_value=cfg.min_order_value)
        if not decision.allowed:
            ev.update(action="blocked", reason=f"{sig.reason} | risk gate chặn: {decision.reason}")
        else:
            fill = executor.buy(symbol, decision.adjusted_qty, price,
                                f"{symbol}-buy-{bar}", sig.reason, trade_date=bar)
            ev.update(action="buy", ok=fill.ok, skipped=fill.skipped, qty=fill.qty,
                      reason=sig.reason if fill.ok else fill.reason)
    elif sig.action == SELL and holding:
        fill = executor.sell(symbol, pos.qty, price,
                             f"{symbol}-sell-{bar}", sig.reason, trade_date=bar)
        ev.update(action="sell", ok=fill.ok, skipped=fill.skipped, qty=fill.qty,
                  reason=sig.reason if fill.ok else fill.reason)
    return ev


def run_tick(cfg: Config, store: Store, feed: DataFeed | None = None) -> list[dict]:
    """1 tick LIVE. Chỉ giao dịch nếu nến mới nhất = hôm nay (giờ VN) -> tránh
    đặt lệnh trên dữ liệu cũ (ngày nghỉ/lễ hoặc data chưa cập nhật)."""
    feed = feed or DataFeed()
    strategy = MACrossStrategy(cfg.ma_fast, cfg.ma_slow)
    executor = PaperExecutor(store)
    today = today_vn()
    events = []
    for symbol in cfg.watchlist:
        try:
            df = feed.history(symbol, days=LOOKBACK_DAYS)
        except Exception as exc:  # noqa: BLE001
            events.append({"symbol": symbol, "action": "error", "reason": str(exc)})
            continue
        bar = _bar_date(df)
        if bar != today:
            events.append({"symbol": symbol, "action": "skip_stale",
                           "reason": f"Nến mới nhất {bar} ≠ hôm nay {today} (ngày nghỉ/data chưa cập nhật)"})
            continue
        ev = process(cfg, store, strategy, executor, symbol, df)
        # ghi nhật ký quyết định cho phiên hôm nay (kể cả HOLD, kèm lý do)
        store.record_decision(bar, symbol, ev["action"], ev["reason"], ev.get("price"))
        events.append(ev)
    return events
