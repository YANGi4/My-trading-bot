import os, json, time
from datetime import datetime, timezone, timedelta
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestTradeRequest, StockBarsRequest
from alpaca.data.timeframe import TimeFrame

CONFIG = {
    "AAPL": {"max_open": 2, "min_profit": 0.003, "stop_loss": -0.05, "max_hold_h": 24},
    "TTWO": {"max_open": 2, "min_profit": 0.003, "peak_gain": 0.20, "drop_from_peak": 0.08, "stop_loss": -0.07, "max_hold_h": 168},
}

SLIPPAGE = 0.001
FEE = 0.0005
BREAKEVEN = (SLIPPAGE + FEE) * 2

STATE_FILE = "state.json"
trading = TradingClient(os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_SECRET_KEY"), paper=True)
data_client = StockHistoricalDataClient(os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_SECRET_KEY"))

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                s = json.load(f)
                for sym in list(s.keys()):
                    if isinstance(s[sym], dict) and "positions" not in s[sym]:
                        if "entry_price" in s[sym]:
                            s[sym] = {"positions": [s[sym]]}
                        else:
                            s[sym] = {"positions": []}
                return s
        except:
            return {}
    return {}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)
    os.system("git config --global user.email 'bunny@runner.com'")
    os.system("git config --global user.name 'BunnyRunner'")
    os.system("git pull --rebase --autostash")
    os.system(f"git add {STATE_FILE}")
    os.system(f'git commit -m "save {int(time.time())}" || echo no changes')
    os.system("git push")

def get_price(sym):
    try:
        req = StockLatestTradeRequest(symbol_or_symbols=sym)
        return float(data_client.get_stock_latest_trade(req)[sym].price)
    except:
        return None

def get_positions():
    try:
        pos = trading.get_all_positions()
        return {p.symbol: float(p.qty) for p in pos}
    except:
        return {}

def decide_buy_qty(symbol, current_price):
    """
    Bot decides 1 or 2 depending on market.
    Strong dip = buy 2 at once, Normal = buy 1
    """
    try:
        # get last 20 days
        req = StockBarsRequest(symbol_or_symbols=symbol, timeframe=TimeFrame.Day, limit=20)
        bars = data_client.get_stock_bars(req).df
        if bars.empty:
            return 1
        
        # bars is multi-index, filter for symbol
        if symbol in bars.index.get_level_values(0):
            sym_bars = bars.loc[symbol]
        else:
            sym_bars = bars
        
        recent_high = sym_bars['high'].max()
        sma_10 = sym_bars['close'].tail(10).mean()
        
        drop_from_high = (current_price - recent_high) / recent_high
        drop_from_sma = (current_price - sma_10) / sma_10
        
        print(f"  {symbol} market check: price {current_price:.2f} recent_high {recent_high:.2f} ({drop_from_high*100:.2f}%) SMA10 {sma_10:.2f} ({drop_from_sma*100:.2f}%)")
        
        # AAPL thresholds
        if symbol == "AAPL":
            # strong if >1.5% below high or >1% below SMA
            if drop_from_high < -0.015 or drop_from_sma < -0.01:
                print(f"  -> STRONG BUY signal for {symbol}, will buy 2")
                return 2
        else:  # TTWO more volatile
            if drop_from_high < -0.03 or drop_from_sma < -0.02:
                print(f"  -> STRONG BUY signal for {symbol}, will buy 2")
                return 2
        
        print(f"  -> NORMAL buy for {symbol}, will buy 1")
        return 1
        
    except Exception as e:
        print(f"  Market check failed {e}, default buy 1")
        return 1

state = load_state()
positions = get_positions()
print(f"Positions {positions}")

try:
    for o in trading.get_orders():
        if str(o.status) in ["new", "accepted"]:
            trading.cancel_order_by_id(o.id)
            time.sleep(0.2)
except:
    pass

now_ts = datetime.now(timezone.utc).timestamp()

# SELL 1 by 1
for symbol, cfg in CONFIG.items():
    if symbol not in state or not state[symbol].get("positions"):
        continue
    price = get_price(symbol)
    if not price:
        continue

    for idx, pos in enumerate(list(state[symbol]["positions"])):
        entry = pos.get("entry_price", price)
        max_p = pos.get("max_price", price)
        if price > max_p:
            pos["max_price"] = price
            max_p = price

        gross = (price - entry) / entry if entry else 0
        real = gross - BREAKEVEN
        hold_h = (now_ts - pos.get("entry", now_ts)) / 3600

        sell = False
        reason = ""
        if real >= cfg["min_profit"]:
            sell = True
            reason = f"profit {real*100:.2f}%"
        if gross <= cfg["stop_loss"]:
            sell = True
            reason = f"STOP {gross*100:.2f}%"
        if symbol == "TTWO":
            peak = (max_p - entry) / entry if entry else 0
            drop = (max_p - price) / max_p if max_p else 0
            if peak >= cfg["peak_gain"]:
                if drop >= cfg["drop_from_peak"]:
                    sell = True
                    reason = f"TTWO peak +{peak*100:.1f}% drop {drop*100:.1f}%"
                else:
                    if real < 0.15:
                        sell = False
        if hold_h >= cfg["max_hold_h"]:
            sell = True
            reason = f"max hold {hold_h:.1f}h"

        if sell:
            print(f"SELL {symbol} 1 share pos {idx+1} - {reason}")
            try:
                trading.submit_order(MarketOrderRequest(symbol=symbol, qty=1, side=OrderSide.SELL, time_in_force=TimeInForce.DAY))
                state[symbol]["positions"].pop(idx)
                if len(state[symbol]["positions"]) == 0:
                    del state[symbol]
                time.sleep(1)
            except Exception as e:
                print(f"Sell err {e}")
            break

time.sleep(2)
positions = get_positions()

# BUY - bot decides 1 or 2 depending on market
for symbol, cfg in CONFIG.items():
    cur_qty = int(positions.get(symbol, 0))
    max_open = cfg["max_open"]
    tracked = len(state.get(symbol, {}).get("positions", []))
    if cur_qty < tracked:
        state[symbol]["positions"] = state[symbol]["positions"][:cur_qty]
        tracked = cur_qty

    remaining = max_open - tracked
    if remaining <= 0:
        print(f"{symbol} {tracked}/{max_open} full - skip")
        continue

    price = get_price(symbol)
    if not price:
        continue

    # BOT DECIDES QTY BASED ON MARKET
    decided_qty = decide_buy_qty(symbol, price)
    qty_to_buy = min(decided_qty, remaining)

    print(f"BUY {symbol} {qty_to_buy} share(s) - pos {tracked+1}-{tracked+qty_to_buy}/{max_open} @ {price} (bot decided {decided_qty}, remaining {remaining})")
    try:
        trading.submit_order(MarketOrderRequest(symbol=symbol, qty=qty_to_buy, side=OrderSide.BUY, time_in_force=TimeInForce.DAY))
        if symbol not in state:
            state[symbol] = {"positions": []}
        for _ in range(qty_to_buy):
            state[symbol]["positions"].append({"entry": now_ts, "entry_price": price, "max_price": price})
        time.sleep(1)
    except Exception as e:
        print(f"Buy err {e}")

save_state(state)
print(f"Done - bot can buy 1 or 2 at once depending on market")
