"""Seed board bằng backtest lịch sử — tạo đường equity + lịch sử lệnh ban đầu.

Replay từng NGÀY theo trục thời gian gộp của watchlist, ghi snapshot equity mỗi
ngày -> board có đường equity thật ngay từ đầu. Chạy 1 LẦN trên DB sạch:

  python -m scripts.seed [số_ngày]      # mặc định 365

Sau đó dùng scripts.run cho các tick hằng ngày (append tiếp).
"""
from __future__ import annotations

import sys
from datetime import date

from engine.executor import PaperExecutor
from engine.feed import DataFeed
from engine.paper import Config, process
from engine.store import Store
from engine.strategy import MACrossStrategy


def main(argv: list[str]) -> int:
    days = int(argv[0]) if argv else 365
    cfg = Config.load()
    feed = DataFeed()
    store = Store(cfg.db_path)
    if store.order_count() > 0:
        print("⚠️  DB đã có lệnh — seed chỉ chạy trên DB SẠCH. Bỏ qua.", file=sys.stderr)
        store.close()
        return 1
    store.ensure_initialized(cfg.paper_capital)
    strategy = MACrossStrategy(cfg.ma_fast, cfg.ma_slow)
    executor = PaperExecutor(store)

    # tải lịch sử + lập bảng tra giá đóng cửa theo ngày cho mỗi mã
    hist, close_by_day = {}, {}
    for sym in cfg.watchlist:
        try:
            df = feed.history(sym, days=days).reset_index(drop=True)
        except Exception as exc:  # noqa: BLE001
            print(f"  [{sym}] lỗi tải dữ liệu: {exc}", file=sys.stderr)
            continue
        df["day"] = df["time"].astype(str).str[:10]
        hist[sym] = df
        close_by_day[sym] = dict(zip(df["day"], df["close"]))

    all_days = sorted({d for m in close_by_day.values() for d in m})
    last_close: dict[str, float] = {}
    n_trades = 0

    for d in all_days:
        for sym, df in hist.items():
            if d in close_by_day[sym]:
                last_close[sym] = close_by_day[sym][d]
            idx = df.index[df["day"] == d]
            if len(idx) == 0:
                continue
            i = int(idx[0])
            if i < cfg.ma_slow + 1:
                continue
            ev = process(cfg, store, strategy, executor, sym, df.iloc[: i + 1])
            if ev and ev.get("ok") and not ev.get("skipped"):
                n_trades += 1
        # equity cuối ngày d theo giá đóng cửa gần nhất của từng mã đang giữ
        equity = store.get_cash() + sum(
            p.qty * last_close.get(p.symbol, p.avg_price) for p in store.all_positions()
        )
        store.record_equity(d, equity)

    eq = store.equity_history()
    final = eq[-1]["equity"] if eq else cfg.paper_capital
    print(f"Seed {days} ngày xong: {n_trades} lệnh khớp, {len(eq)} điểm equity, "
          f"equity cuối {final:,.0f}, P&L {final - cfg.paper_capital:,.0f}")
    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
