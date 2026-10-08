import os, json, time
import yfinance as yf
import alpaca_trade_api as tradeapi

CONFIG = {
    "AAPL": {
        "stop": 100, "take": 100, "trailing": 100, "breakeven": 100,
        "max_hold_h": 1, # 1h auto sell
        "max_open": 1, "max_daily": 24, "cooldown_m": 0,
        "interval": "60m", "period": "5d", "conf": 50
    },
    "TTWO": {
        "stop": 10.0,
        "take": 100,
        "trailing": 12.0, # 12% drop from peak
        "breakeven": 20.0, # needs +20% first
        "max_hold_h": 8760, # 1 year
        "max_open": 1, "max_daily": 2, "cooldown_m": 30,
        "interval": "60m", "period": "10d", "conf": 60
    }
}
SLIPPAGE_PCT=0.0005

raw_base = os.getenv("ALPACA_BASE_URL") or "https://paper-api.alpaca.markets"
base = raw_base.strip().rstrip("/")
if base.endswith("/v2"): base = base[:-3].rstrip("/")
api = tradeapi.REST(os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_SECRET_KEY") or os.getenv("ALPACA_API_SECRET"), base)

try:
    with open("state.json","r") as f: STATE=json.load(f)
except: STATE={}
def save():
    with open("state.json","w") as f: json.dump(STATE,f)

def get_data(sym):
    c=CONFIG[sym]
    df=yf.download(sym, period=c["period"], interval=c["interval"], progress=False, auto_adjust=True)
    if len(df)<50: return None
    df['SMA9']=df['Close'].rolling(9).mean()
    df['SMA20']=df['Close'].rolling(20).mean()
    df['SMA50']=df['Close'].rolling(50).mean()
    df['HIGH20']=df['Close'].rolling(20).max()
    delta=df['Close'].diff()
    gain=delta.where(delta>0,0).rolling(14).mean()
    loss=-delta.where(delta<0,0).rolling(14).mean()
    df['RSI']=100-(100/(1+gain/loss))
    return df

def check_exits():
    for p in api.list_positions():
        sym=p.symbol
        if sym not in CONFIG: continue
        df=get_data(sym)
        cur=float(p.current_price)*(1-SLIPPAGE_PCT)
        avg=float(p.avg_entry_price)
        pnl=(cur-avg)/avg*100

        if sym not in STATE or "entry" not in STATE[sym]:
            try:
                orders=api.list_orders(status="closed", symbols=[sym], limit=20)
                buys=[o for o in orders if o.side=="buy" and o.status=="filled"]
                if buys:
                    oldest=sorted(buys, key=lambda x: x.filled_at)[0]
                    STATE[sym]={"max_price":cur, "entry":oldest.filled_at.timestamp()}
            except: STATE[sym]={"max_price":cur, "entry":time.time()}

        s=STATE[sym]
        s["max_price"]=max(s.get("max_price",cur), cur)
        hold_h=(time.time()-s["entry"])/3600
        drop=(s["max_price"]-cur)/s["max_price"]*100
        cfg=CONFIG[sym]

        sell=False; reason=""
        if sym=="AAPL":
            if hold_h >= cfg["max_hold_h"]:
                sell=True; reason=f"AAPL 1H TIME UP {hold_h:.1f}h"
        else:
            rsi = float(df['RSI'].iloc[-1]) if df is not None else 50
            if pnl <= -cfg["stop"]:
                sell=True; reason=f"TTWO Stop {pnl:.1f}%"
            elif pnl > cfg["breakeven"] and drop >= cfg["trailing"]:
                if rsi > 75 and cur > float(df['SMA20'].iloc[-1]):
                    print(f"TTWO GTA6 HYPE RSI {rsi:.1f} - HOLDING")
                else:
                    sell=True; reason=f"TTWO PEAK SELL +{pnl:.1f}% drop {drop:.1f}% from ${s['max_price']:.2f}"

        if sell:
            api.submit_order(symbol=sym, qty=abs(int(float(p.qty))), side="sell", type="market", time_in_force="day")
            print(f"SELL {sym} {reason}")
            STATE.pop(sym,None)
    save()

def check_entries():
    pos={p.symbol: int(float(p.qty)) for p in api.list_positions()}
    for sym,cfg in CONFIG.items():
        if pos.get(sym,0) >= cfg["max_open"]: continue
        df=get_data(sym)
        if df is None: continue
        close=float(df['Close'].iloc[-1])
        sma20=float(df['SMA20'].iloc[-1]); sma50=float(df['SMA50'].iloc[-1])
        high20=float(df['HIGH20'].iloc[-1]); rsi=float(df['RSI'].iloc[-1])
        dip_pct=(high20-close)/high20*100

        if sym=="AAPL":
            score = (30 if close > sma50 else 0) + (30 if rsi < 65 else 0) + 20
            buy = score >= cfg["conf"]
        else:
            score=0
            if close < sma20: score+=20
            if close < sma50*0.98: score+=30
            if rsi < 40: score+=30
            if dip_pct > 4: score+=20
            print(f"TTWO DIP check ${close:.2f} dip {dip_pct:.1f}% RSI {rsi:.1f} score {score}%")
            buy = score >= cfg["conf"]

        if buy:
            api.submit_order(symbol=sym, qty=1, side="buy", type="market", time_in_force="day")
            STATE[sym]={"max_price":close, "entry":time.time()}
            save()
            print(f"BUY {sym} 1")

check_exits()
check_entries()
