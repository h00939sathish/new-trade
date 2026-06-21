import logging
from typing import Literal

logger = logging.getLogger("risk.margin")

ProductType = Literal["mis", "cnceq", "co"]


class MarginCalculator:
    """NSE margin calculator for different product types.

    NSE margin requirements (approximate, for risk estimation):
    - MIS (intraday): ~20% of order value
    - CNC (delivery): 100% of order value
    - CO (cover order): VAR + ELM (typically 5-10%)
    """

    MIS_MARGIN_PCT = 0.20
    CNC_MARGIN_PCT = 1.00
    CO_MARGIN_PCT = 0.08

    def required_margin(
        self,
        order_value: float,
        product: ProductType = "mis",
        quantity: int = 0,
        price: float = 0.0,
    ) -> float:
        if product == "mis":
            return order_value * self.MIS_MARGIN_PCT
        elif product == "cnceq":
            return order_value * self.CNC_MARGIN_PCT
        elif product == "co":
            return order_value * self.CO_MARGIN_PCT
        return order_value * self.MIS_MARGIN_PCT

    def available_margin(
        self,
        cash_balance: float,
        open_position_margin: float,
        open_position_pnl: float,
    ) -> float:
        return cash_balance - open_position_margin + open_position_pnl

    def check_order(
        self,
        cash_balance: float,
        open_position_margin: float,
        open_position_pnl: float,
        order_value: float,
        product: ProductType = "mis",
        quantity: int = 0,
        price: float = 0.0,
        buffer_pct: float = 0.0,
    ) -> tuple[bool, float, float, float]:
        required = self.required_margin(order_value, product, quantity, price)
        available = self.available_margin(cash_balance, open_position_margin, open_position_pnl)
        needed_with_buffer = required * (1.0 + buffer_pct)
        passed = available >= needed_with_buffer
        return passed, required, available, needed_with_buffer
