from dataclasses import dataclass
from typing import Any, Literal


@dataclass
class TransactionCostModel:
    brokerage_pct: float = 0.0003  # 0.03%
    brokerage_flat: float = 20.0  # Max ₹20
    stt_pct_buy_cnc: float = 0.001  # 0.1% for CNC buy
    stt_pct_sell_cnc: float = 0.001  # 0.1% for CNC sell
    stt_pct_sell_mis: float = 0.00025  # 0.025% for MIS sell
    exchange_txn_pct: float = 0.0000345  # 0.00345%
    gst_pct: float = 0.18  # 18% GST
    sebi_pct: float = 0.000001  # 0.0001% (₹10 / Crore)
    stamp_duty_pct_cnc: float = 0.00015  # 0.015% for CNC buy
    stamp_duty_pct_mis: float = 0.00003  # 0.003% for MIS buy
    slippage_bps: float = 5.0  # 5 basis points default slippage

    def total_cost(
        self,
        side: Literal["buy", "sell"],
        quantity: int,
        price: float,
        product: Literal["mis", "cnc", "nrml"] = "mis",
    ) -> float:
        """Calculates total transaction taxes and charges on the trade in ₹."""
        value = price * quantity
        if value <= 0 or quantity <= 0:
            return 0.0

        # 1. Brokerage
        brokerage = min(value * self.brokerage_pct, self.brokerage_flat)

        # 2. Exchange Transaction Charges
        exchange_txn = value * self.exchange_txn_pct

        # 3. GST on (Brokerage + Exchange Txn)
        gst = (brokerage + exchange_txn) * self.gst_pct

        # 4. SEBI Turnover Fees
        sebi = value * self.sebi_pct

        # 5. Securities Transaction Tax (STT)
        stt = 0.0
        if product == "mis":
            if side == "sell":
                stt = value * self.stt_pct_sell_mis
        else:  # cnc / delivery / positional
            stt = value * (self.stt_pct_sell_cnc if side == "sell" else self.stt_pct_buy_cnc)

        # 6. Stamp Duty
        stamp_duty = 0.0
        if side == "buy":
            if product == "mis":
                stamp_duty = value * self.stamp_duty_pct_mis
            else:
                stamp_duty = value * self.stamp_duty_pct_cnc

        return brokerage + exchange_txn + gst + sebi + stt + stamp_duty

    def effective_fill_price(self, side: Literal["buy", "sell"], price: float) -> float:
        """Adjusts the price to account for expected market slippage."""
        slippage = price * (self.slippage_bps / 10000.0)
        if side == "buy":
            return price + slippage
        else:
            return price - slippage

    def effective_fill_price_with_depth(
        self,
        side: Literal["buy", "sell"],
        price: float,
        quantity: int,
        depth: dict[str, list[dict[str, Any]]] | None = None,
    ) -> float:
        """Calculate volume-weighted fill price sweeping through order book depth levels."""
        if not depth or not depth.get("buy") or not depth.get("sell") or quantity <= 0:
            return self.effective_fill_price(side, price)

        levels = depth["sell"] if side == "buy" else depth["buy"]
        remaining_qty = quantity
        total_value = 0.0
        filled_qty = 0

        for level in levels:
            lvl_price = float(level.get("price", price))
            lvl_qty = int(level.get("quantity", 0))
            if lvl_qty <= 0:
                continue

            fill = min(remaining_qty, lvl_qty)
            total_value += fill * lvl_price
            filled_qty += fill
            remaining_qty -= fill

            if remaining_qty <= 0:
                break

        if filled_qty > 0:
            avg_price = total_value / filled_qty
        else:
            avg_price = price

        if remaining_qty > 0:
            # Order exceeds total book depth. Apply 10bps penalty beyond worst level.
            worst_price = float(levels[-1].get("price", price))
            penalty_pct = 0.0010
            penalty_price = worst_price * (
                1.0 + penalty_pct if side == "buy" else 1.0 - penalty_pct
            )
            total_value += remaining_qty * penalty_price
            avg_price = total_value / quantity

        return avg_price
