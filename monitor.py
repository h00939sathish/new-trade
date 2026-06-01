import subprocess, json, os, sys, re
from datetime import datetime

WORKDIR = "D:\\projects\\new trade"
STATE_PATH = os.path.join(WORKDIR, "monitor_state.json")
API_URL = "https://new-trade-production.up.railway.app/api/paper-report"
CHAT_ID = "8555799588"

def run(cmd, cwd=WORKDIR):
    try:
        result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=30)
        return result.stdout.strip()
    except Exception:
        return ""

def get_paper_report():
    out = run(["curl", "-s", API_URL])
    if not out:
        return None
    try:
        return json.loads(out)
    except Exception:
        return None

def get_telegram_token():
    out = run([
        "railway", "variables", "list",
        "--service", "new-trade",
        "--environment", "production",
        "--json"
    ])
    if not out:
        return ""
    try:
        data = json.loads(out)
        for item in data:
            if item.get("name") == "telegram_bot_token":
                return item.get("value", "")
    except Exception:
        pass
    return ""

def load_state():
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH) as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "last_trade_count": 0,
        "regime_suppression_active": True,
        "alerted_regime_clear": False,
        "alerted_first_trade": False,
        "alerted_breaches": {},
    }

def save_state(state):
    with open(STATE_PATH, "w") as f:
        json.dump(state, f)

def send_telegram(token, text):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    subprocess.run([
        "curl", "-s", "-X", "POST", url,
        "-d", f"chat_id={CHAT_ID}",
        "-d", f"text={text}"
    ], timeout=15)

def format_risk_breach(entry):
    ts = entry.get("timestamp", "?")
    msg = entry.get("message", "")
    details = entry.get("details", {})

    instrument = details.get("instrument", "?")
    check_name = details.get("check_name", "?")
    passed = details.get("passed", False)
    signal = details.get("signal", {})
    checks = details.get("checks", [])

    # Format basic header
    text = (
        f"⚠️ RISK BREACH\n"
        f"───────────────\n"
        f"Time    : {ts}\n"
        f"Instr.  : {instrument}\n"
        f"Check   : {check_name}\n"
        f"Result  : {'FAIL' if not passed else 'PASS'}\n"
    )

    # Signal info
    if signal:
        strategy = signal.get("strategy", "?")
        direction = signal.get("direction", "?").upper()
        confidence = signal.get("confidence", 0)
        price = signal.get("price", "?")

        text += (
            f"\nSIGNAL:\n"
            f"  Strategy  : {strategy}\n"
            f"  Action    : {direction}\n"
            f"  Confid.   : {confidence*100:.1f}%\n"
            f"  Price     : {price}\n"
        )

        # votes if present
        votes = signal.get("votes", {})
        if votes:
            text += "  Votes:\n"
            for name, info in votes.items():
                vdir = info.get("direction", "?").upper()
                vconf = info.get("confidence", 0)
                text += f"    • {name}: {vdir} ({vconf*100:.1f}%)\n"

        # SL/TP
        sl = signal.get("stop_loss_pct")
        tp = signal.get("take_profit_pct")
        if sl is not None or tp is not None:
            text += f"  SL/TP    : {sl} / {tp}\n"

    # Checks table
    if checks:
        text += "\nCHECKS:\n"
        for c in checks:
            name = c.get("name", "?")
            passed_c = c.get("passed", False)
            status = "PASS" if passed_c else "FAIL"
            text += f"  [{status}] {name}\n"

            # Show key detail for failed liquidity check
            if name == "liquidity" and not passed_c:
                det = c.get("details", {})
                avg = det.get("avg_volume", "?")
                thresh = det.get("threshold", "?")
                samples = det.get("samples", "?")
                text += f"         avg_vol={avg} (need>{thresh}) samples={samples}\n"

            # Show per-trade loss cap
            if name == "per_trade_loss_cap" and passed_c:
                det = c.get("details", {})
                pot = det.get("potential_loss", "?")
                maxl = det.get("max_loss_allowed", "?")
                if isinstance(pot, (int, float)) and isinstance(maxl, (int, float)):
                    text += f"         loss=₹{pot:,.0f} / cap=₹{maxl:,.0f}\n"

    return text

def parse_log_entries(raw):
    entries = []
    for line in raw.splitlines():
        try:
            obj = json.loads(line)
            if "RISK BREACH" in obj.get("message", ""):
                entries.append(obj)
        except Exception:
            pass
    return entries

def main():
    state = load_state()
    report = get_paper_report()
    if report is None:
        return

    trade_count = 0
    portfolio_value = "N/A"
    pnl = "N/A"
    agents_online = "?"
    market_data_active = False
    if isinstance(report, dict):
        trade_count = report.get("trades", 0) or 0
        portfolio_value = report.get("portfolio_value", "N/A")
        pnl = report.get("pnl", "N/A")
        agents_online = report.get("agents_online", "?")
        market_data_active = report.get("market_data_activity_detected", False)

    token = get_telegram_token()

    # Check for new trade
    if trade_count > state["last_trade_count"] and not state["alerted_first_trade"]:
        if token:
            msg = (
                "✅ First paper trade executed!\n"
                f"Total trades: {trade_count}\n"
                f"Portfolio: {portfolio_value}\n"
                f"PnL: {pnl}"
            )
            send_telegram(token, msg)
        state["alerted_first_trade"] = True
        state["last_trade_count"] = trade_count
        save_state(state)
        return

    if trade_count > state["last_trade_count"]:
        state["last_trade_count"] = trade_count
        save_state(state)

    # Check regime instability suppression
    out = run(["railway", "logs", "--lines", "2000", "--json"])
    regime_active = "Regime instability detected" in out

    if not regime_active and state["regime_suppression_active"] and not state["alerted_regime_clear"]:
        if token:
            msg = (
                "🟢 Regime instability cleared.\n"
                "Entry suppression lifted."
            )
            send_telegram(token, msg)
        state["alerted_regime_clear"] = True
        state["regime_suppression_active"] = False
        save_state(state)

    # Check risk breaches
    if not token:
        return

    breach_entries = parse_log_entries(out)
    if not breach_entries:
        return

    alerted = state.get("alerted_breaches", {})
    new_alerts = {}

    for entry in breach_entries:
        msg_text = entry.get("message", "")
        # Use message content as key to dedupe; compact enough for state
        key = msg_text
        if key in alerted:
            continue

        formatted = format_risk_breach(entry)
        send_telegram(token, formatted)
        alerted[key] = datetime.now().isoformat()
        new_alerts[key] = alerted[key]

    if new_alerts:
        state["alerted_breaches"] = alerted
        save_state(state)

if __name__ == "__main__":
    main()
