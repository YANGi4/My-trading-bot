import os, json, time, datetime
import yfinance as yf
import alpaca_trade_api as tradeapi
from datetime import timezone

CONFIG = {
    "AAPL": {"stop":5.0, "take":3.5, "trailing":1.2, "breakeven":1.2, "max_hold_h":12, "max_open":2, "max_daily":12, "cooldown_m":20, "interval":"15m", "period":"5d", "conf":55},
    "TTWO": {"stop":6.0, "take":4.5, "trailing":1.5, "breakeven":1.5, "max_hold_h":24, "max_open":2, "max_daily":8, "cooldown_m":30, "interval":"60m", "period":"10d", "conf":60}
}
COMMISSION=0.02; SLIPPAGE_PCT=0.0005

# FIX BASE URL - remove /v2 if user added it
raw_base = os.getenv("ALPACA_BASE_URL") or "https://paper-api.alpaca.markets"
base = raw_base.strip().rstrip("/")
if base.endswith("/v2"): base = base[:-3].rstrip("/")
print(f"Using base: {base} (from secret {raw_base})")

key=os.getenv("ALPACA_API_KEY")
sec=os.getenv("ALPACA_SECRET_KEY") or os.getenv("ALPACA_API_SECRET")
api=tradeapi.REST(key, sec, base)

# EMERGENCY
if os.path.exists("EMERGENCY_STOP") or os.getenv("EMERGENCY_STOP")=="1":
    print("!!! EMERGENCY - SELL ALL!!!")
    try:
        api.cancel_all_orders()
        for p in api.list_positions():
            api.submit_order(symbol=p.symbol, qty=abs(int(float(p.qty))), side="sell", type="market", time_in_force="day")
            print(f"SOLD {p.symbol}")
    except Exception as e: print(e)
    exit(0)

try:
    with open("state.json","r") as f: STATE=json.load(f)
except: STATE={}
def save():
    with open("state.json","w") as f: json.dump(STATE,f)

def market_open():
    try:
        return api.get_clock().is_open
    except Exception as e:
        print(f"Clock check failed ({e}) - assuming OPEN for testing")
        return True # don't crash, assume open

def get_data(sym):
    c=CONFIG[sym]
    df=yf.download(sym, period=c["period"], interval=c["interval"], progress=False, auto_adjust=True)
    if len(df)<50: return None
    df['SMA9']=df['Close'].rolling(9).mean()
    df['SMA50']=df['Close'].rolling(50).mean()
    delta=df['Close'].diff()
    gain=delta.where(delta>0,0).rolling(14).mean()
    loss=-delta.where(delta<0,0).rolling(14).mean()
    df['RSI']=100-(100/(1+gain/loss))
    df['EMA12']=df['Close'].ewm(12).mean()
    df['EMA26']=df['Close'].ewm(26).mean()
    df['MACD']=df['EMA12']-df['EMA26']
    df['SIG']=df['MACD'].ewm(9).mean()
    return df

def check_exits():
    for p in api.list_positions():
        sym=p.symbol
        if sym not in CONFIG: continue
        cur=float(p.current_price)*(1-SLIPPAGE_PCT)
        avg=float(p.avg_entry_price)
        pnl=(cur-avg)/avg*100
        s=STATE.get(sym, {"max_price":cur, "entry":time.time(), "last_loss":0})
        s["max_price"]=max(s.get("max_price",cur), cur)
        STATE[sym]=s
        hold_h=(time.time()-s["entry"])/3600
        drop=(s["max_price"]-cur)/s["max_price"]*100
        cfg=CONFIG[sym]
        sell=False; reason=""
        if pnl <= -cfg["stop"]: sell=True; reason=f"Stop {pnl:.2f}%"
        elif pnl >= cfg["take"]: sell=True; reason=f"Take {pnl:.2f}%"
        elif hold_h >= cfg["max_hold_h"]: sell=True; reason=f"MaxHold {hold_h:.1f}h"
        elif pnl > cfg["breakeven"] and drop >= cfg["trailing"]: sell=True; reason=f"Trailing {drop:.2f}%"
        if sell:
            api.submit_order(symbol=sym, qty=abs(int(float(p.qty))), side="sell", type="market", time_in_force="day")
            print(f"SELL {sym} {reason}")
            if pnl < 0: STATE[sym]["last_loss"]=time.time()
            STATE[sym].pop("max_price",None)
    save()

def check_entries():
    acct=api.get_account()
    cash=float(acct.cash); equity=float(acct.equity)
    print(f"Cash ${cash:.2f} Equity ${equity:.2f}")
    positions={p.symbol: int(float(p.qty)) for p in api.list_positions()}
    today=[o for o in api.list_orders(status="closed", limit=100) if o.filled_at and o.filled_at.date()==datetime.datetime.now(timezone.utc).date()]
    for sym,cfg in CONFIG.items():
        if positions.get(sym,0) >= cfg["max_open"]: continue
        if len([o for o in today if o.symbol==sym]) >= cfg["max_daily"]: continue
        last_loss=STATE.get(sym,{}).get("last_loss",0)
        if time.time()-last_loss < cfg["cooldown_m"]*60: continue
        df=get_data(sym)
        if df is None: continue
        close=float(df['Close'].iloc[-1])
        sma9=float(df['SMA9'].iloc[-1]); sma50=float(df['SMA50'].iloc[-1])
        rsi=float(df['RSI'].iloc[-1]); macd=float(df['MACD'].iloc[-1]); sig=float(df['SIG'].iloc[-1])
        score=0
        if close > sma50: score+=20
        if close < sma9: score+=20
        if close > float(df['Close'].iloc[-2]): score+=20
        if macd < sig: score+=20
        if sym=="TTWO": score+=20
        print(f"{sym} Score {score}% need {cfg['conf']}% RSI {rsi:.1f}")
        if score >= cfg["conf"]:
            order_cost=close*1*(1+SLIPPAGE_PCT)+COMMISSION
            if order_cost > cash: print(f"{sym} skip cash"); continue
            api.submit_order(symbol=sym, qty=1, side="buy", type="market", time_in_force="day")
            print(f"BUY {sym} 1")
            STATE[sym]={"max_price":close, "entry":time.time(), "last_loss":STATE.get(sym,{}).get("last_loss",0)}
            save()

if not market_open():
    print("Market closed - will still run for test")
    check_entries()
    check_exits()
else:
    check_entries()
    for i in range(2): # short test - 2 mins
        time.sleep(10)
        check_exits()
