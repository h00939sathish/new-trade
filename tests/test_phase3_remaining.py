import os
import sqlite3
import tempfile

import pytest

from src.risk.kelly_sizing import KellySizer
from src.strategies.microstructure import OrderFlowImbalanceStrategy
from src.utils.vault import load_secure_secret


def test_load_secure_secret_fallback():
    os.environ["TRA_TEST_SECRET"] = "supersecret"
    os.environ["TRA_VAULT_PROVIDER"] = ""
    val = load_secure_secret("TRA_TEST_SECRET")
    assert val == "supersecret"


@pytest.mark.asyncio
async def test_microstructure_ofi():
    strat = OrderFlowImbalanceStrategy(ofi_window=2, threshold=0.5)

    depth1 = {
        "buy": [{"quantity": 100, "price": 99.0}],
        "sell": [{"quantity": 50, "price": 101.0}],
    }
    res1 = await strat.evaluate("TEST", prices=[100.0], depth=depth1, bid=99.0, ask=101.0)
    assert res1 is None

    depth2 = {
        "buy": [{"quantity": 500, "price": 99.0}],
        "sell": [{"quantity": 50, "price": 101.0}],
    }
    res2 = await strat.evaluate("TEST", prices=[100.0], depth=depth2, bid=99.0, ask=101.0)
    assert res2 is not None
    assert res2["direction"] == "long"
    assert res2["features"]["ofi"] > 0


def test_kelly_sizer_calculation():
    sizer = KellySizer()
    f_star = sizer.calculate_kelly_fraction(0.6, 2.0)
    assert abs(f_star - 0.4) < 0.001


def test_kelly_sizer_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        sizer = KellySizer(db_path=db_path)
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE orders (event_id TEXT, strategy TEXT)")
        conn.execute(
            "CREATE TABLE fills (order_id TEXT, instrument TEXT, side TEXT, fill_price REAL, fill_quantity INTEGER, filled_at TEXT)"
        )

        for i in range(5):
            conn.execute("INSERT INTO orders VALUES (?, 'test_strat')", (f"o_buy_{i}",))
            conn.execute(
                "INSERT INTO fills VALUES (?, 'TEST', 'buy', 100.0, 10, '2023-01-01')",
                (f"o_buy_{i}",),
            )
            conn.execute("INSERT INTO orders VALUES (?, 'test_strat')", (f"o_sell_{i}",))
            conn.execute(
                "INSERT INTO fills VALUES (?, 'TEST', 'sell', 110.0, 10, '2023-01-02')",
                (f"o_sell_{i}",),
            )

        conn.commit()
        conn.close()

        p, b = sizer.get_strategy_performance("test_strat", default_p=0.5, default_b=1.5)
        assert p == 1.0
        assert b == 1.5
    finally:
        if os.path.exists(db_path):
            os.remove(db_path)
