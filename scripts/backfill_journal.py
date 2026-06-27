"""Backfill nhật ký quyết định ~N phiên gần nhất từ lịch sử giá + sổ lệnh.

Tái dựng (xác định, không đổi state): mỗi ngày × mỗi mã -> tín hiệu MA cross +
trạng thái nắm giữ (suy từ sổ lệnh trước ngày đó) -> action + lý do. Để board
hiển thị được lý do các phiên đã qua (vd vì sao 25/6 không mua bán).

Chạy 1 lần: python -m scripts.backfill_journal [N=25]
"""
from __future__ import annotations

import sys

from engine.feed import DataFeed
from engine.paper import Config
from engine.store import Store
from engine.strategy import BUY, SELL, MACrossStrategy


def _holding_before(orders, symbol: str, day: str) -> bool:
    qty = 0
    for o in orders:
        if o["symbol"] != symbol or o["trade_date"] >= day:
            continue
        qty += o["qty"] if o["side"] == "buy" else -o["qty"]
    return qty > 0


def main(argv: list[str]) -> int:
    days = int(argv[0]) if argv else 25
    cfg = Config.load()
    feed = DataFeed()
    strat = MACrossStrategy(cfg.ma_fast, cfg.ma_slow)
    store = Store(cfg.db_path)
    orders = store.orders()

    hist = {}
    for sym in cfg.watchlist:
        try:
            df = feed.history(sym, days=days + cfg.ma_slow + 40).reset_index(drop=True)
            df["day"] = df["time"].astype(str).str[:10]
            hist[sym] = df
        except Exception as exc:  # noqa: BLE001
            print(f"  [{sym}] lỗi: {exc}", file=sys.stderr)

    all_days = sorted({d for df in hist.values() for d in df["day"]})[-days:]
    n = 0
    for d in all_days:
        for sym, df in hist.items():
            window = df[df["day"] <= d]
            if len(window) < cfg.ma_slow + 1:
                continue
            holding = _holding_before(orders, sym, d)
            sig = strat.signal(sym, window, holding)
            action = sig.action if sig.action in (BUY, SELL) else "hold"
            store.record_decision(d, sym, action, sig.reason,
                                  float(window["close"].iloc[-1]), overwrite=True)
            n += 1
    print(f"Backfill {len(all_days)} phiên × {len(hist)} mã = {n} dòng nhật ký "
          f"(từ {all_days[0] if all_days else '-'} đến {all_days[-1] if all_days else '-'}).")
    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
