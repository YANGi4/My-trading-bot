import os, json, time, datetime
import yfinance as yf
import alpaca_trade_api as tradeapi
from datetime import timezone, timedelta

# === YOUR SETTINGS ===
CONFIG = {
    "AAPL": {"stop":5.0, "take":3.5, "trailing":1.2, "breakeven":1.2, "max_hold_h":12, "max_open":2, "max_daily":12, "cooldown_m":20, "interval":"15m", "period":"5d", "conf":55},
    "TTWO": {"stop":6.0, "take":4.5, "trailing":1.5, "breakeven":1.5, "max_hold_h":24, "max_open":2, "max_daily":8, "cooldown_m":30, "interval":"60m", "period":"10d", "conf":60}
}
COMMISSION = 0.02 # $0.02 per share - Alpaca is $0 but we add for realism
SLIPPAGE_PCT = 0.0005 # 0.05% slippage per trade - realistic
LEVERAGE_OFF = True

key = os.getenv("ALPACA_API_KEY")
sec = os.getenv("ALPACA_SECRET_KEY") or os.getenv("ALPACA_API_SECRET")
base = os.getenv("ALPACA_BASE_URL") or "https://paper-api.alpaca.markets"
api = tradeapi.REST(key, sec, base)

# === EMERGENCY SHUTDOWN CHECK ===
if os.path.exists("EMERGENCY_STOP") or os.getenv("EMERGENCY_STOP")=="1":
    print("!!! EMERGENCY SHUTDOWN ACTIVATED!!!")
    try:
        for p in api.list_positions():
            api.submit_order(symbol=p.symbol, qty=abs(int(float(p.qty))), side="sell", type="market", time_in_force="day")
            print(f"LIQUIDATED {p.symbol}")
    except Exception as e: print(f"Liquidate error {e}")
    print("All closed. Delete EMERGENCY_STOP file to resume.")
    exit(0)

# STATE
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

# EXITS every 1 min
def check_exits():
    for p in api.list_positions():
        sym=p.symbol
        if sym not in CONFIG: continue
        cur=float(p.current_price)*(1-SLIPPAGE_PCT) # slippage included
        avg=float(p.avg_entry_price)
        pnl=(cur-avg)/avg*100
        cfg=CONFIG[sym]
        s=STATE.get(sym, {"max_price":cur, "entry":time.time(), "last_loss":0})
        s["max_price"]=max(s.get("max_price",cur), cur)
        STATE[sym]=s

        hold_h=(time.time()-s["entry"])/3600
        drop=(s["max_price"]-cur)/s["max_price"]*100

        sell=False; reason=""
        if pnl <= -cfg["stop"]: sell=True; reason=f"Stop {pnl:.2f}%"
        elif pnl >= cfg["take"]: sell=True; reason=f"Take {pnl:.2f}%"
        elif hold_h >= cfg["max_hold_h"]: sell=True; reason=f"MaxHold {hold_h:.1f}h >= {cfg['max_hold_h']}h" # 12h / 1day as you asked
        elif pnl > cfg["breakeven"] and drop >= cfg["trailing"]: sell=True; reason=f"Trailing -{drop:.2f}%"

        if sell:
            cost_with_fees = cur*abs(float(p.qty)) - COMMISSION*abs(float(p.qty))
            api.submit_order(symbol=sym, qty=abs(int(float(p.qty))), side="sell", type="market", time_in_force="day")
            print(f"SELL {sym} PNL {pnl:.2f}% {reason} Net~${cost_with_fees:.2f} (incl ${COMMISSION} comm + {SLIPPAGE_PCT*100}% slip)")
            if pnl < 0: STATE[sym]["last_loss"]=time.time() # countdown after loss
            else: STATE[sym].pop("last_loss",None)
            STATE[sym].pop("max_price",None)
    save()

# ENTRIES every 15min
def check_entries():
    acct=api.get_account()
    cash=float(acct.cash)
    equity=float(acct.equity)
    print(f"Cash ${cash:.2f} Equity ${equity:.2f} - Leverage OFF: {LEVERAGE_OFF}")

    positions={p.symbol: int(float(p.qty)) for p in api.list_positions()}
    today_orders=[o for o in api.list_orders(status="closed", limit=100) if o.filled_at and o.filled_at.date()==datetime.datetime.now(timezone.utc).date()]

    for sym,cfg in CONFIG.items():
        if positions.get(sym,0) >= cfg["max_open"]: continue
        if len([o for o in today_orders if o.symbol==sym]) >= cfg["max_daily"]: continue

        # Countdown after loss: AAPL 20min / TTWO 30min
        last_loss=STATE.get(sym,{}).get("last_loss",0)
        cooldown=cfg["cooldown_m"]*60
        if time.time()-last_loss < cooldown:
            print(f"{sym} cooldown {int((cooldown - (time.time()-last_loss))/60)}m left after loss"); continue

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
        if sym=="TTWO": score+=20 # placeholder for GTA VI news - we count as catalyst

        print(f"{sym} Score {score}% need {cfg['conf']}% RSI {rsi:.1f}")

        if score >= cfg["conf"]:
            # Leverage OFF check - never spend more than equity
            order_cost = close*1*(1+SLIPPAGE_PCT) + COMMISSION
            if LEVERAGE_OFF and order_cost > cash:
                print(f"{sym} skip: Need ${order_cost:.2f} but cash ${cash:.2f} - Leverage OFF")
                continue
            if LEVERAGE_OFF and (positions.get(sym,0)*close + order_cost) > equity:
                print(f"{sym} skip: Would exceed equity ${equity:.2f}")
                continue

            api.submit_order(symbol=sym, qty=1, side="buy", type="market", time_in_force="day")
            print(f"BUY {sym} 1 @ ~${close:.2f} + slip/comm")
            STATE[sym]={"max_price":close, "entry":time.time(), "last_loss":STATE.get(sym,{}).get("last_loss",0)}
            save()

# MAIN - Entry 15min + Exit 1min loop for 15min = meets your spec
if not api.get_clock().is_open:
    print("Market closed 9:30-4 ET / 20:30-03:00 BKK")
else:
    check_entries()
    for i in range(14):
        time.sleep(60)
        check_exits()
