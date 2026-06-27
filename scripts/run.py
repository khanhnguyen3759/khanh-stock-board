"""Entrypoint board: chạy 1 tick paper -> cập nhật state -> xuất docs/data.json.

Chạy:  python -m scripts.run
KHÔNG cần secret. Chỉ dùng dữ liệu giá công khai (vnstock).
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

from engine.feed import DataFeed
from engine.paper import Config, run_tick
from engine.store import Store

BOARD_JSON = Path("docs/data.json")
AI_WATCHLIST = Path("docs/ai_watchlist.json")   # do screener repo chính xuất ra (public-safe)


def _load_ai_analysis() -> dict | None:
    """Đọc phân tích AI nếu có. File KHÔNG chứa secret (chỉ điểm + lý do)."""
    if not AI_WATCHLIST.exists():
        return None
    try:
        return json.loads(AI_WATCHLIST.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def build_snapshot(cfg: Config, store: Store, feed: DataFeed, events: list[dict]) -> dict:
    cash = store.get_cash()
    positions = []
    market_value = unrealized = 0.0
    for p in store.all_positions():
        try:
            last = feed.latest_price(p.symbol)
        except Exception:  # noqa: BLE001
            last = p.avg_price
        mv = last * p.qty
        pl = (last - p.avg_price) * p.qty
        market_value += mv
        unrealized += pl
        positions.append({
            "symbol": p.symbol, "qty": p.qty, "avg_price": round(p.avg_price),
            "last": round(last), "market_value": round(mv), "pnl": round(pl),
        })
    equity = cash + market_value
    realized = store.total_realized_pnl()

    # mốc GO-LIVE: ranh giới giữa backtest (tái dựng quá khứ) và giả lập thật.
    # Lần đầu chạy build_snapshot sẽ chốt = hôm nay; sau đó giữ nguyên.
    go_live = store.get_meta("go_live")
    if go_live is None:
        go_live = date.today().isoformat()
        store.set_meta("go_live", go_live)

    # ghi điểm equity hôm nay (đường equity)
    store.record_equity(date.today().isoformat(), equity)

    orders = [{
        "trade_date": r["trade_date"], "ts": r["ts"],
        "symbol": r["symbol"], "side": r["side"], "qty": r["qty"],
        "price": round(r["price"]), "fees": round(r["fees"]), "note": r["note"] or "",
    } for r in store.orders()]

    curve = [{"day": r["day"], "equity": round(r["equity"])} for r in store.equity_history()]

    journal = [{
        "day": r["day"], "symbol": r["symbol"], "action": r["action"],
        "reason": r["reason"], "price": round(r["price"]) if r["price"] else None,
    } for r in store.recent_decisions(15)]

    # phân tích AI (nếu có file watchlist.json do screener ở repo chính xuất ra)
    ai = _load_ai_analysis()

    return {
        "updated_at": datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
        "watchlist": list(cfg.watchlist),
        "paper_capital": cfg.paper_capital,
        "go_live": go_live,
        "strategy": f"MA cross ({cfg.ma_fast}/{cfg.ma_slow})",
        "cash": round(cash),
        "market_value": round(market_value),
        "equity": round(equity),
        "realized_pnl": round(realized),
        "unrealized_pnl": round(unrealized),
        "total_pnl": round(equity - cfg.paper_capital),
        "order_count": store.order_count(),
        "positions": positions,
        "orders": orders[-100:],          # 100 lệnh gần nhất
        "equity_curve": curve,
        "daily_log": journal,             # nhật ký quyết định 15 phiên gần nhất
        "ai_analysis": ai,                # phân tích AI (nếu có)
        "last_events": events,
    }


def main() -> int:
    cfg = Config.load()
    feed = DataFeed()
    with Store(cfg.db_path) as store:
        store.ensure_initialized(cfg.paper_capital)
        events = run_tick(cfg, store, feed)
        snapshot = build_snapshot(cfg, store, feed, events)
    BOARD_JSON.parent.mkdir(parents=True, exist_ok=True)
    BOARD_JSON.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Tick xong. Equity {snapshot['equity']:,} | "
          f"P&L {snapshot['total_pnl']:,} | lệnh {snapshot['order_count']} | "
          f"sự kiện: {len(events)}")
    for ev in events:
        print("  -", ev)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
