"""Risk gate — 3 lớp chặn vốn. LÀ LUẬT CUỐI (giống repo chính).

Mọi lệnh MUA phải đi qua đây. Trong board paper, trần vốn = PAPER_CAPITAL.
"""
from __future__ import annotations

from dataclasses import dataclass

LOT_SIZE = 100  # lô chẵn HOSE


@dataclass
class RiskDecision:
    allowed: bool
    adjusted_qty: int
    reason: str
    kill_switch: bool = False


def check_buy(*, price: float, qty: int, fees: float, available_cash: float,
              max_capital: float, deployed: float, min_order_value: float) -> RiskDecision:
    if available_cash < min_order_value:
        return RiskDecision(False, 0,
            f"Kill switch: tiền {available_cash:,.0f} < ngưỡng {min_order_value:,.0f}",
            kill_switch=True)
    budget = min(available_cash, max_capital - deployed)
    if budget <= 0:
        return RiskDecision(False, 0,
            f"Hết budget: deployed {deployed:,.0f} chạm trần {max_capital:,.0f}")
    order_value = price * qty + fees
    if order_value <= budget:
        return RiskDecision(True, qty, "OK")
    affordable = int((budget - fees) // price)
    affordable = (affordable // LOT_SIZE) * LOT_SIZE
    if affordable <= 0:
        return RiskDecision(False, 0, f"Budget {budget:,.0f} không đủ 1 lô giá {price:,.0f}")
    return RiskDecision(True, affordable,
        f"Giảm KL {qty} -> {affordable} cho vừa budget {budget:,.0f}")
