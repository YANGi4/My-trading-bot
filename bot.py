
import os
import json
import yfinance as yf
from datetime import datetime, timezone

try:
    import alpaca_trade_api as tradeapi
    ALPACA_AVAILABLE = True
except:
    ALPACA_AVAILABLE = False

SYMBOLS = {
    "AAPL": {"interval": "15m", "sl": 0.05, "tp": 0.035, "conf": 0.55, "rsi_period": 14},
    "TTWO": {"interval": "60m", "sl": 0.06, "tp": 0.045, "conf": 0.60, "rsi_period": 14}
}
MAX_TRADES_PER_DAY = 6
MAX_OPEN = 4
QTY = 1
STARTING_BALANCE = 10000.0  # <-- YOUR SCHOOL SPEC
LEDGER_FILE = "paper_ledger.json"

def get_rsi(prices, period=14):
    delta = prices.diff()
    gain = delta.where(delta > 0, 0).rolling(window=period).mean()
    loss = -delta.where(delta < 0, 0).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def get_confidence(rsi_last):
    if rsi_last < 30: return 0.68
    if rsi_last > 70: return 0.65
    if rsi_last < 40: return 0.60
    if rsi_last > 60: return 0.58
    return 0.50

def load_ledger():
    try:
        with open(LEDGER_FILE, "r") as f:
            d = json.load(f)
            # Force 10k if file has wrong balance
            if d.get("cash", 0) > 20000: 
                d["cash"] = STARTING_BALANCE
                d["equity"] = STARTING_BALANCE
            return d
    except:
        return {"cash": STARTING_BALANCE, "equity": STARTING_BALANCE, "positions": [], "trade_history": [], "daily_counts": {}}

def save_ledger(ledger):
    with open(LEDGER_FILE, "w") as f:
        json.dump(ledger, f, indent=2)

def is_market_open():
    now = datetime.now(timezone.utc)
    if now.weekday() >= 5: return False
    hour = now.hour + now.minute/60
    return 13.5 <= hour <= 20.0

def main():
    print(f"=== BOT START {datetime.now(timezone.utc)} | BALANCE ${STARTING_BALANCE} ===")
    api_key = os.getenv("ALPACA_API_KEY") or os.getenv("APCA_API_KEY_ID")
    secret = os.getenv("ALPACA_SECRET_KEY") or os.getenv("APCA_API_SECRET_KEY")
    base_url = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
    
    use_alpaca = ALPACA_AVAILABLE and api_key and secret
    api = None
    
    if use_alpaca:
        print(f"Using Alpaca PAPER - will enforce ${STARTING_BALANCE} school limit")
        api = tradeapi.REST(api_key, secret, base_url, api_version='v2')
        try:
            account = api.get_account()
            print(f"Alpaca Raw Equity: ${account.equity} (we will simulate ${STARTING_BALANCE} limit)")
            # NOTE: Reset your Alpaca Paper account to $10k in dashboard for professor to see $10k
            # Dashboard -> Overview -> Reset Account -> $10,000
        except Exception as e:
            print(f"Alpaca auth failed, fallback to local: {e}")
            use_alpaca = False
    else:
        print(f"Using LOCAL paper ledger ${STARTING_BALANCE}")

    if not is_market_open():
        print("Market closed ET (8:30pm-3am BKK)")
        return

    ledger = load_ledger()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    if use_alpaca:
        try:
            positions = api.list_positions()
            open_symbols = [p.symbol for p in positions]
            # Enforce $10k school limit: only allow 4 open max = ~$1000 exposure, well within $10k
            if len(positions) >= MAX_OPEN:
                print(f"Max open {MAX_OPEN} reached")
                return
            # Also check buying power - don't use full $100k, simulate $10k
            account = api.get_account()
            # If Alpaca still has $100k, we limit by position count and 1 share qty so max exposure ~$1000
            print(f"Open: {open_symbols} | Sim Balance: ${STARTING_BALANCE}")
        except Exception as e:
            print(f"Error: {e}")
            open_symbols = []
    else:
        open_symbols = [p["symbol"] for p in ledger.get("positions", [])]
        if len(open_symbols) >= MAX_OPEN:
            print(f"Max open {MAX_OPEN} reached")
            return
        if ledger["cash"] < 500:  # Need at least $500 for 1 share
            print(f"Cash low ${ledger['cash']:.2f} - stopping (sim ${STARTING_BALANCE} limit)")
            return

    for symbol, cfg in SYMBOLS.items():
        key = f"{today}_{symbol}"
        daily_count = ledger.get("daily_counts", {}).get(key, 0)
        if daily_count >= MAX_TRADES_PER_DAY:
            print(f"{symbol}: Max {MAX_TRADES_PER_DAY}/day reached")
            continue
        if symbol in open_symbols:
            continue

        try:
            yf_interval = "15m" if cfg["interval"] == "15m" else "1h"
            period = "5d" if cfg["interval"] == "15m" else "20d"
            data = yf.download(symbol, period=period, interval=yf_interval, progress=False)
            if len(data) < 30: continue
            close = data["Close"]
            rsi = get_rsi(close, cfg["rsi_period"])
            rsi_last = float(rsi.iloc[-1])
            conf = get_confidence(rsi_last)
            price = float(close.iloc[-1])
            
            print(f"{symbol}: ${price:.2f} RSI {rsi_last:.1f} conf {conf:.2f} need {cfg['conf']}")
            
            if conf >= cfg["conf"] and rsi_last < 65:
                print(f"*** BUY {symbol} 1 share (School Balance ${STARTING_BALANCE}) ***")
                if use_alpaca:
                    try:
                        api.submit_order(
                            symbol=symbol, qty=QTY, side='buy', type='market', time_in_force='day',
                            order_class='bracket',
                            take_profit={'limit_price': round(price * (1+cfg["tp"]), 2)},
                            stop_loss={'stop_price': round(price * (1-cfg["sl"]), 2)}
                        )
                        print(f"Alpaca BUY {symbol} @ ~{price} TP {cfg['tp']*100}% SL {cfg['sl']*100}%")
                        ledger["trade_history"].append({"time": datetime.now(timezone.utc).isoformat(), "symbol": symbol, "action": "BUY", "price": price, "qty": QTY, "reason": f"RSI {rsi_last:.1f} conf {conf:.2f} bal ${STARTING_BALANCE}"})
                        ledger["daily_counts"][key] = daily_count + 1
                    except Exception as e:
                        print(f"Buy fail: {e}")
                else:
                    if ledger["cash"] >= price * QTY:
                        ledger["cash"] -= price * QTY
                        ledger["positions"].append({"symbol": symbol, "entry": price, "qty": QTY, "time": datetime.now(timezone.utc).isoformat()})
                        ledger["trade_history"].append({"time": datetime.now(timezone.utc).isoformat(), "symbol": symbol, "action": "BUY", "price": price, "qty": QTY, "reason": f"RSI {rsi_last:.1f}"})
                        ledger["daily_counts"][key] = daily_count + 1
                        print(f"LOCAL BUY {symbol} @ {price}")
        except Exception as e:
            print(f"Error {symbol}: {e}")

    if not use_alpaca:
        try:
            total = 0
            for pos in ledger["positions"]:
                d = yf.download(pos["symbol"], period="1d", interval="1m", progress=False)
                if len(d)>0: total += float(d["Close"].iloc[-1]) * pos["qty"]
            ledger["equity"] = ledger["cash"] + total
        except: pass
        save_ledger(ledger)
        print(f"Saved: cash ${ledger['cash']:.2f} equity ${ledger['equity']:.2f} (of ${STARTING_BALANCE} start)")
    else:
        save_ledger(ledger)

if __name__ == "__main__":
    main()
