import os, json, time
from datetime import datetime, timezone
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestTradeRequest, StockBarsRequest
from alpaca.data.timeframe import TimeFrame

CONFIG = {
 "AAPL": {"max_open": 1, "min_profit": 0.003, "stop_loss": -0.03, "max_hold_h": 24, "daily_loss_limit": -10},
 "TTWO": {"max_open": 1, "min_profit": 0.004, "peak_gain": 0.02, "drop_from_peak": 0.005, "stop_loss": -0.035, "max_hold_h": 168, "daily_loss_limit": -10},
}

SLIPPAGE = 0.001
FEE = 0.0005
BREAKEVEN = (SLIPPAGE + FEE) * 2
STATE_FILE = "state.json"

# keep your old env names
trading = TradingClient(os.getenv("ALPACA_API_KEY") or os.getenv("APCA_API_KEY_ID"), os.getenv("ALPACA_SECRET_KEY") or os.getenv("APCA_API_SECRET_KEY"), paper=True)
data_client = StockHistoricalDataClient(os.getenv("ALPACA_API_KEY") or os.getenv("APCA_API_KEY_ID"), os.getenv("ALPACA_SECRET_KEY") or os.getenv("APCA_API_SECRET_KEY"))

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                s = json.load(f)
                for sym in CONFIG:
                    s.setdefault(sym, {"positions": [], "daily_pnl": 0.0, "daily_date": ""})
                    s[sym].setdefault("positions", [])
                    s[sym].setdefault("daily_pnl", 0.0)
                    s[sym].setdefault("daily_date", "")
                return s
        except:
            pass
    return {s: {"positions": [], "daily_pnl": 0.0, "daily_date": ""} for s in CONFIG}

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

def get_context(sym):
    try:
        req = StockBarsRequest(symbol_or_symbols=sym, timeframe=TimeFrame.Day, limit=20)
        bars = data_client.get_stock_bars(req).df
        if bars.empty: return None, None
        sym_bars = bars.loc[sym] if sym in bars.index.get_level_values(0) else bars
        high_20 = sym_bars['high'].max()
        sma_10 = sym_bars['close'].tail(10).mean()
        return high_20, sma_10
    except:
        return None, None

state = load_state()
today_str = datetime.now(timezone.utc).date().isoformat()

try:
    for o in trading.get_orders(filter=GetOrdersRequest(status=QueryOrderStatus.OPEN)):
        trading.cancel_order_by_id(o.id)
        time.sleep(0.2)
except:
    pass

now_ts = datetime.now(timezone.utc).timestamp()

for symbol, cfg in CONFIG.items():
    if state[symbol]["daily_date"]!= today_str:
        state[symbol]["daily_date"] = today_str
        state[symbol]["daily_pnl"] = 0.0

    if state[symbol]["daily_pnl"] <= cfg["daily_loss_limit"]:
        print(f"{symbol} DAILY STOP {state[symbol]['daily_pnl']:.2f} - skip today")
        continue

    price = get_price(symbol)
    if not price:
        continue

    # SELL
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
            if peak >= cfg["peak_gain"] and drop >= cfg["drop_from_peak"]:
                sell = True
                reason = f"TTWO peak +{peak*100:.1f}% drop {drop*100:.1f}%"
        if hold_h >= cfg["max_hold_h"]:
            sell = True
            reason = f"max hold {hold_h:.1f}h"

        if sell:
            pnl_dollars = (price - entry) - (BREAKEVEN * entry)
            state[symbol]["daily_pnl"] += pnl_dollars
            print(f"SELL {symbol} 1 - {reason} daily {state[symbol]['daily_pnl']:.2f}")
            try:
                trading.submit_order(MarketOrderRequest(symbol=symbol, qty=1, side=OrderSide.SELL, time_in_force=TimeInForce.DAY))
                state[symbol]["positions"].pop(idx)
                time.sleep(1)
            except Exception as e:
                print(f"Sell err {e}")
            break

    # BUY - ALWAYS 1 SHARE ONLY
    if len(state[symbol]["positions"]) < cfg["max_open"]:
        high_20, sma_10 = get_context(symbol)
        if high_20 and price:
            print(f"BUY CHECK {symbol} price {price:.2f} high {high_20:.2f} sma {sma_10:.2f}")
            trading.submit_order(MarketOrderRequest(symbol=symbol, qty=1, side=OrderSide.BUY, time_in_force=TimeInForce.DAY))
            state[symbol]["positions"].append({"entry": now_ts, "entry_price": price, "max_price": price})
            time.sleep(1)

save_state(state)
print("Done - 1 share max, daily stop active")
