"""PaperExecutor — mô phỏng khớp lệnh, ghi DB. KHÔNG gọi API broker."""
from __future__ import annotations

from dataclasses import dataclass

from .store import Order, Store

BUY_FEE_RATE = 0.0015    # phí mua ~0.15%
SELL_FEE_RATE = 0.0015   # phí bán ~0.15%
SELL_TAX_RATE = 0.001    # thuế bán 0.1%


def buy_fees(price: float, qty: int) -> float:
    return price * qty * BUY_FEE_RATE


def sell_fees(price: float, qty: int) -> float:
    value = price * qty
    return value * SELL_FEE_RATE + value * SELL_TAX_RATE


@dataclass
class Fill:
    ok: bool
    symbol: str
    side: str
    qty: int
    price: float
    fees: float
    reason: str = ""
    skipped: bool = False


class PaperExecutor:
    mode = "paper"

    def __init__(self, store: Store):
        self._store = store

    def buy(self, symbol, qty, price, client_id, note="", trade_date="") -> Fill:
        if qty <= 0:
            return Fill(False, symbol, "buy", 0, price, 0, "qty <= 0")
        if self._store.has_order(client_id):
            return Fill(True, symbol, "buy", qty, price, 0, "Đã ghi", skipped=True)
        fees = buy_fees(price, qty)
        cost = price * qty + fees
        cash = self._store.get_cash()
        if cost > cash:
            return Fill(False, symbol, "buy", qty, price, fees,
                        f"Thiếu tiền: cần {cost:,.0f} > có {cash:,.0f}")
        pos = self._store.get_position(symbol)
        old_qty = pos.qty if pos else 0
        old_cost = pos.cost_basis if pos else 0.0
        new_qty = old_qty + qty
        new_avg = (old_cost + cost) / new_qty
        order = Order(client_id, symbol, "buy", qty, price, fees, self.mode, note,
                      trade_date=trade_date)
        if not self._store.apply_fill(order, cash - cost, new_qty, new_avg):
            return Fill(True, symbol, "buy", qty, price, fees, "Đã ghi", skipped=True)
        return Fill(True, symbol, "buy", qty, price, fees, "OK")

    def sell(self, symbol, qty, price, client_id, note="", trade_date="") -> Fill:
        if qty <= 0:
            return Fill(False, symbol, "sell", 0, price, 0, "qty <= 0")
        if self._store.has_order(client_id):
            return Fill(True, symbol, "sell", qty, price, 0, "Đã ghi", skipped=True)
        pos = self._store.get_position(symbol)
        if not pos or pos.qty < qty:
            held = pos.qty if pos else 0
            return Fill(False, symbol, "sell", qty, price, 0,
                        f"Không đủ CP: có {held}, bán {qty}")
        fees = sell_fees(price, qty)
        proceeds = price * qty - fees
        cash = self._store.get_cash()
        pnl = (price - pos.avg_price) * qty - fees
        new_qty = pos.qty - qty
        new_avg = pos.avg_price if new_qty > 0 else 0.0
        order = Order(client_id, symbol, "sell", qty, price, fees, self.mode, note,
                      trade_date=trade_date)
        if not self._store.apply_fill(order, cash + proceeds, new_qty, new_avg,
                                      realized=(pos.avg_price, price, pnl)):
            return Fill(True, symbol, "sell", qty, price, fees, "Đã ghi", skipped=True)
        return Fill(True, symbol, "sell", qty, price, fees, f"OK, P&L {pnl:,.0f}")
