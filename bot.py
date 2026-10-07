import os, yfinance as yf, pandas as pd
import alpaca_trade_api as tradeapi

print("=== AUTONOMOUS LIVE BOT ===")
key = os.getenv("ALPACA_API_KEY")
sec = os.getenv("ALPACA_SECRET_KEY") or os.getenv("ALPACA_API_SECRET")
base = os.getenv("ALPACA_BASE_URL") or "https://paper-api.alpaca.markets"
api = tradeapi.REST(key, sec, base)

acct = api.get_account()
print(f"Equity: ${acct.equity} Cash: ${acct.cash}")

symbols = ["AAPL","MSFT","NVDA","TSLA","SPY"]
for sym in symbols:
    df = yf.download(sym, period="1mo", interval="1d", progress=False)
    close = df['Close']
    delta = close.diff()
    gain = delta.where(delta>0,0).rolling(14).mean()
    loss = -delta.where(delta<0,0).rolling(14).mean()
    rs = gain/loss
    rsi = 100 - (100/(1+rs))
    rsi_last = float(rsi.iloc[-1])
    price = float(close.iloc[-1])
    print(f"{sym} RSI:{rsi_last:.1f} Price:${price:.2f}")
    
    # Loose buy: RSI < 70 = always buys on first run
    if rsi_last < 70:
        try:
            api.submit_order(symbol=sym, qty=1, side="buy", type="market", time_in_force="day")
            print(f"BUY {sym} SENT")
        except Exception as e:
            print(f"{sym} buy skip: {e}")
    print("---")

print("BOT FINISHED - Check Alpaca positions")
