"""State/DB (SQLite) — orders, positions, cash, P&L, equity theo ngày.

Idempotent qua client_id: chạy lại cùng cây nến KHÔNG nhân đôi lệnh.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id TEXT UNIQUE NOT NULL,
    ts TEXT NOT NULL,            -- thời điểm script chạy (UTC)
    trade_date TEXT NOT NULL,    -- NGÀY GIAO DỊCH thật (theo nến) — để xem dòng thời gian
    symbol TEXT NOT NULL, side TEXT NOT NULL,
    qty INTEGER NOT NULL, price REAL NOT NULL, fees REAL NOT NULL,
    mode TEXT NOT NULL, note TEXT
);
CREATE TABLE IF NOT EXISTS positions (
    symbol TEXT PRIMARY KEY, qty INTEGER NOT NULL, avg_price REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS realized_pnl (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, symbol TEXT NOT NULL,
    qty INTEGER NOT NULL, buy_price REAL NOT NULL, sell_price REAL NOT NULL, pnl REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS equity_snapshots (day TEXT PRIMARY KEY, equity REAL NOT NULL, ts TEXT NOT NULL);
-- Nhật ký quyết định: mỗi phiên, mỗi mã -> 1 dòng (kể cả HOLD) kèm lý do.
CREATE TABLE IF NOT EXISTS daily_log (
    day TEXT NOT NULL, symbol TEXT NOT NULL,
    action TEXT NOT NULL,   -- buy | sell | hold | blocked | skip
    reason TEXT NOT NULL, price REAL, ts TEXT NOT NULL,
    PRIMARY KEY (day, symbol)
);
"""


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


@dataclass
class Position:
    symbol: str
    qty: int
    avg_price: float

    @property
    def cost_basis(self) -> float:
        return self.qty * self.avg_price


@dataclass
class Order:
    client_id: str
    symbol: str
    side: str
    qty: int
    price: float
    fees: float
    mode: str
    note: str = ""
    ts: str = ""
    trade_date: str = ""    # ngày giao dịch thật (theo nến)


class Store:
    def __init__(self, db_path: str | Path):
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # meta / cash
    def get_meta(self, key, default=None):
        row = self._conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_meta(self, key, value):
        self._conn.execute(
            "INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)))
        self._conn.commit()

    def get_cash(self) -> float:
        v = self.get_meta("cash")
        return float(v) if v is not None else 0.0

    def set_cash(self, value: float):
        self.set_meta("cash", f"{value:.2f}")

    def ensure_initialized(self, starting_cash: float):
        if self.get_meta("cash") is None:
            self.set_cash(starting_cash)
            self.set_meta("initialized_at", _now())
            self.set_meta("starting_cash", f"{starting_cash:.2f}")

    def deployed(self) -> float:
        return sum(p.cost_basis for p in self.all_positions())

    # orders
    def has_order(self, client_id: str) -> bool:
        return self._conn.execute("SELECT 1 FROM orders WHERE client_id=?", (client_id,)).fetchone() is not None

    def order_count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) c FROM orders").fetchone()["c"]

    def orders(self):
        return self._conn.execute("SELECT * FROM orders ORDER BY id").fetchall()

    def apply_fill(self, order: Order, new_cash: float, new_qty: int,
                   new_avg_price: float, realized=None) -> bool:
        try:
            with self._conn:
                self._conn.execute(
                    "INSERT INTO orders(client_id,ts,trade_date,symbol,side,qty,price,fees,mode,note) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (order.client_id, order.ts or _now(), order.trade_date, order.symbol,
                     order.side, order.qty, order.price, order.fees, order.mode, order.note))
                self._conn.execute(
                    "INSERT INTO meta(key,value) VALUES('cash',?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (f"{new_cash:.2f}",))
                if new_qty <= 0:
                    self._conn.execute("DELETE FROM positions WHERE symbol=?", (order.symbol,))
                else:
                    self._conn.execute(
                        "INSERT INTO positions(symbol,qty,avg_price) VALUES(?,?,?) "
                        "ON CONFLICT(symbol) DO UPDATE SET qty=excluded.qty, avg_price=excluded.avg_price",
                        (order.symbol, new_qty, new_avg_price))
                if realized is not None:
                    bp, sp, pnl = realized
                    self._conn.execute(
                        "INSERT INTO realized_pnl(ts,symbol,qty,buy_price,sell_price,pnl) "
                        "VALUES(?,?,?,?,?,?)", (_now(), order.symbol, order.qty, bp, sp, pnl))
            return True
        except sqlite3.IntegrityError:
            return False

    # positions
    def get_position(self, symbol: str):
        row = self._conn.execute("SELECT * FROM positions WHERE symbol=?", (symbol,)).fetchone()
        return Position(row["symbol"], row["qty"], row["avg_price"]) if row else None

    def all_positions(self):
        rows = self._conn.execute("SELECT * FROM positions WHERE qty>0 ORDER BY symbol").fetchall()
        return [Position(r["symbol"], r["qty"], r["avg_price"]) for r in rows]

    # P&L
    def total_realized_pnl(self) -> float:
        return float(self._conn.execute("SELECT COALESCE(SUM(pnl),0) s FROM realized_pnl").fetchone()["s"])

    # equity snapshots (cho đường equity trên board)
    def record_equity(self, day: str, equity: float):
        self._conn.execute(
            "INSERT INTO equity_snapshots(day,equity,ts) VALUES(?,?,?) "
            "ON CONFLICT(day) DO UPDATE SET equity=excluded.equity, ts=excluded.ts",
            (day, equity, _now()))
        self._conn.commit()

    def equity_history(self):
        return self._conn.execute("SELECT day, equity FROM equity_snapshots ORDER BY day").fetchall()

    # nhật ký quyết định hằng ngày (mỗi ngày + mã -> 1 dòng, kể cả HOLD)
    def record_decision(self, day, symbol, action, reason, price=None, overwrite=False):
        if not overwrite and self._conn.execute(
            "SELECT 1 FROM daily_log WHERE day=? AND symbol=?", (day, symbol)
        ).fetchone():
            return
        self._conn.execute(
            "INSERT INTO daily_log(day,symbol,action,reason,price,ts) VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(day,symbol) DO UPDATE SET action=excluded.action, "
            "reason=excluded.reason, price=excluded.price, ts=excluded.ts",
            (day, symbol, action, reason, price, _now()))
        self._conn.commit()

    def recent_decisions(self, days: int = 15):
        rows = self._conn.execute(
            "SELECT day, symbol, action, reason, price FROM daily_log "
            "WHERE day IN (SELECT DISTINCT day FROM daily_log ORDER BY day DESC LIMIT ?) "
            "ORDER BY day DESC, symbol", (days,)).fetchall()
        return rows
