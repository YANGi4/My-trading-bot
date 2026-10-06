
import yfinance as yf, json, os
from datetime import datetime
import pytz

QTY = 1
RISK = {
  "AAPL": {"SL":0.05, "TP":0.035, "CONF":0.55},
  "TTWO": {"SL":0.06, "TP":0.045, "CONF":0.60}
}

def is_market_open():
    et = datetime.now(pytz.timezone('US/Eastern'))
    return et.weekday() < 5 and 9.5 <= et.hour + et.minute/60 < 16

def get_rsi(series, period=14):
    delta = series.diff()
    gain = delta.where(delta>0,0).rolling(period).mean()
    loss = -delta.where(delta<0,0).rolling(period).mean()
    rs = gain/loss
    return 100 - (100/(1+rs))

def run():
    if not os.path.exists("paper_ledger.json"):
        return
    with open("paper_ledger.json") as f:
        ledger = json.load(f)

    if not is_market_open():
        print("Market closed ET")
        return

    for ticker in ["AAPL","TTWO"]:
        interval = "15m" if ticker=="AAPL" else "60m"
        df = yf.download(ticker, period="5d", interval=interval, auto_adjust=True, progress=False)
        if df.empty:
            continue
        close = df['Close']
        price = float(close.iloc[-1])
        rsi = float(get_rsi(close).iloc[-1])

        # Confidence = simple RSI logic for school
        conf = 0.58 if rsi < 40 else 0.3
        if ticker=="TTWO":
            # GTA news check - simplified
            conf = 0.65 if rsi < 45 else conf

        # ENTRY every 1 min
        open_pos = [p for p in ledger["positions"] if p["symbol"]==ticker]
        if conf >= RISK[ticker]["CONF"] and len(open_pos) < 1:
            if ledger.get(f"daily_trades_{ticker}",0) < 6 and ledger.get("total_trades_today",0) < 12:
                ledger["positions"].append({"symbol":ticker,"entry":price,"shares":QTY,"time":str(datetime.now())})
                ledger["cash"] -= price
                ledger[f"daily_trades_{ticker}"] = ledger.get(f"daily_trades_{ticker}",0)+1
                ledger["total_trades_today"] = ledger.get("total_trades_today",0)+1
                ledger["trade_history"].append({"action":"BUY","symbol":ticker,"price":price,"time":str(datetime.now())})
                print(f"BUY 1 {ticker} @ {price}")

        # EXIT every 1 min
        for pos in ledger["positions"][:]:
            if pos["symbol"] != ticker:
                continue
            pnl = (price - pos["entry"])/pos["entry"]
            if pnl <= -RISK[ticker]["SL"] or pnl >= RISK[ticker]["TP"]:
                ledger["cash"] += price
                ledger["positions"].remove(pos)
                ledger["trade_history"].append({"action":"SELL","symbol":ticker,"price":price,"pnl":pnl,"time":str(datetime.now())})
                print(f"SELL {ticker} @ {price} pnl {pnl:.2%}")

    ledger["equity"] = ledger["cash"] + sum([p["entry"]*p["shares"] for p in ledger["positions"]])
    with open("paper_ledger.json","w") as f:
        json.dump(ledger,f,indent=2)

if __name__=="__main__":
    run()
