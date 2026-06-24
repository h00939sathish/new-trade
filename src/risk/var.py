import os
from collections import deque
from typing import Any


def compute_var_95(price_history: deque[float], position_value: float) -> dict[str, Any]:
    if len(price_history) < 20:
        return {"passed": True, "var_95_pct": 0.0, "var_loss": 0.0, "reason": "insufficient data"}

    h = list(price_history)
    returns = []
    for i in range(1, len(h)):
        if h[i - 1] > 0:
            returns.append((h[i] - h[i - 1]) / h[i - 1])

    if len(returns) < 20:
        return {"passed": True, "var_95_pct": 0.0, "var_loss": 0.0, "reason": "insufficient returns"}

    sorted_ret = sorted(returns)
    var_idx = max(0, int(len(sorted_ret) * 0.05) - 1)
    var_95_pct = abs(sorted_ret[var_idx])
    var_loss = position_value * var_95_pct
    return {
        "passed": True,
        "var_95_pct": var_95_pct,
        "var_loss": var_loss,
        "returns_sample": len(returns),
    }


def check_var_limit(
    var_result: dict[str, Any],
    capital: float,
    max_var_pct: float | None = None,
) -> dict[str, Any]:
    if max_var_pct is None:
        max_var_pct = float(os.environ.get("TRA_RISK_MAX_VAR_PER_SYMBOL", "0.05"))

    if not var_result.get("passed"):
        return {"name": "var_95", "passed": True, "details": var_result}

    var_loss = var_result.get("var_loss", 0.0)
    max_var_loss = capital * max_var_pct

    return {
        "name": "var_95",
        "passed": var_loss <= max_var_loss,
        "details": {
            **var_result,
            "max_var_loss": max_var_loss,
            "max_var_pct": max_var_pct,
        },
    }
