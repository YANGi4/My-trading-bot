import os, json, time
from datetime import datetime, timezone
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestTradeRequest

CONFIG = {
 # RESET VERSION - clean start, 1 share max, realistic fees
 # Sell = green after fees, Rebuy = dip OR breakout OR timeout
 "AAPL": {"min_profit": 0.0005, "stop_loss": -0.03, "max_hold_h": 24, "daily_loss_limit": -10, "rebuy_dip": 0.005, "rebuy_timeout_h": 24, "breakout_buy": 0.01},
 "TTWO": {"min_profit": 0.0005, "peak_gain": 0.02, "drop_from_peak": 0.005, "stop_loss": -0.035, "max_hold_h": 168, "daily_loss_limit": -10, "rebuy_dip": 0.008, "rebuy_timeout_h": 48, "breakout_buy": 0.015},
}

SLIPPAGE = 0.0004  # 0.04% per side
FEE = 0.0001      # 0.01% per side
BREAKEVEN = (SLIPPAGE + FEE) * 2  # 0.001 = 0.1% total
STATE_FILE = "state.json"

trading = TradingClient(os.getenv("ALPACA_API_KEY") or os.getenv("APCA_API_KEY_ID"), os.getenv("ALPACA_SECRET_KEY") or os.getenv("APCA_API_SECRET_KEY"), paper=True)
data_client = StockHistoricalDataClient(os.getenv("ALPACA_API_KEY") or os.getenv("APCA_API_KEY_ID"), os.getenv("ALPACA_SECRET_KEY") or os.getenv("APCA_API_SECRET_KEY"))

def load_state():
    # RESET STATE - no positions array anymore, Alpaca is truth
    default = {"daily_pnl": 0.0, "daily_date": "", "last_sell_price": None, "last_sell_time": 0, "entry_price": None, "max_price": None, "entry_time": 0}
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                s = json.load(f)
                for sym in CONFIG:
                    s.setdefault(sym, default.copy())
                    for k, v in default.items():
                        s[sym].setdefault(k, v)
                return s
        except:
            pass
    return {s: default.copy() for s in CONFIG}

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

def get_fill(order_id):
    try:
        time.sleep(2)
        o = trading.get_order_by_id(order_id)
        if o.filled_avg_price:
            return float(o.filled_avg_price)
    except:
        pass
    return None

state = load_state()

# DON'T TRADE WHEN MARKET CLOSED
try:
    clock = trading.get_clock()
    if not clock.is_open:
        print(f"Market closed - next open {clock.next_open} - skipping")
        exit()
    else:
        print("Market open - trading")
except SystemExit:
    raise
except Exception as e:
    print(f"Clock check failed {e}")

today = datetime.now(timezone.utc).date().isoformat()
now_ts = datetime.now(timezone.utc).timestamp()

# REAL POSITIONS FROM ALPACA - THIS FIXES 3 AAPL BUG
try:
    real = {p.symbol: {"qty": float(p.qty), "avg": float(p.avg_entry_price)} for p in trading.get_all_positions()}
except:
    real = {}
print(f"REAL Alpaca positions: {real}")

for symbol, cfg in CONFIG.items():
    if state[symbol]["daily_date"] != today:
        state[symbol]["daily_date"] = today
        state[symbol]["daily_pnl"] = 0.0
    if state[symbol]["daily_pnl"] <= cfg["daily_loss_limit"]:
        print(f"{symbol} DAILY STOP {state[symbol]['daily_pnl']:.2f}")
        continue

    price = get_price(symbol)
    if not price:
        continue

    # SELL - uses REAL Alpaca avg
    if symbol in real:
        entry = real[symbol]["avg"]
        qty = real[symbol]["qty"]
        if state[symbol]["max_price"] is None:
            state[symbol]["max_price"] = entry
        if price > state[symbol]["max_price"]:
            state[symbol]["max_price"] = price
        max_p = state[symbol]["max_price"]
        entry_time = state[symbol].get("entry_time", 0)
        hold_h = (now_ts - entry_time) / 3600 if entry_time else 0
        gross = (price - entry) / entry
        real_profit = gross - BREAKEVEN
        sell = False; reason = ""
        if real_profit >= cfg["min_profit"]:
            sell = True; reason = f"GREEN AFTER FEES real={real_profit*100:.3f}% gross={gross*100:.3f}%"
        if gross <= cfg["stop_loss"]:
            sell = True; reason = f"STOP {gross*100:.2f}%"
        if symbol == "TTWO":
            peak = (max_p - entry) / entry; drop = (max_p - price) / max_p if max_p else 0
            if peak >= cfg["peak_gain"] and drop >= cfg["drop_from_peak"]:
                sell = True; reason = f"TTWO peak {peak*100:.1f}% drop {drop*100:.1f}%"
        if entry_time and hold_h >= cfg["max_hold_h"]:
            sell = True; reason = f"max hold {hold_h:.1f}h"
        if sell:
            print(f"SELL {symbol} {qty} @ {price:.2f} from {entry:.2f} - {reason}")
            try:
                order = trading.submit_order(MarketOrderRequest(symbol=symbol, qty=qty, side=OrderSide.SELL, time_in_force=TimeInForce.DAY))
                fill = get_fill(order.id) or price
                state[symbol]["daily_pnl"] += (fill - entry) * qty - (BREAKEVEN * entry * qty)
                state[symbol]["last_sell_price"] = fill
                state[symbol]["last_sell_time"] = now_ts
                state[symbol]["entry_price"] = None
                state[symbol]["max_price"] = None
                state[symbol]["entry_time"] = 0
            except Exception as e:
                print(f"Sell err {e}")
            continue

    # BUY - only if NO real position
    if symbol not in real:
        last_sell = state[symbol].get("last_sell_price")
        last_time = state[symbol].get("last_sell_time", 0)
        if last_sell:
            need = last_sell * (1 - cfg["rebuy_dip"])
            breakout = last_sell * (1 + cfg["breakout_buy"])
            hrs = (now_ts - last_time) / 3600 if last_time else 999
            if price <= need:
                print(f"BUY {symbol} DIP @ {price:.2f}")
            elif price >= breakout:
                print(f"BUY {symbol} BREAKOUT @ {price:.2f} - up {((price-last_sell)/last_sell)*100:.2f}% from {last_sell:.2f}")
            elif hrs >= cfg["rebuy_timeout_h"]:
                print(f"BUY {symbol} TIMEOUT @ {price:.2f} - waited {hrs:.1f}h")
            else:
                print(f"{symbol} NO BUY - last {last_sell:.2f} now {price:.2f} need < {need:.2f} OR > {breakout:.2f} OR wait {cfg['rebuy_timeout_h']}h (waited {hrs:.1f}h)")
                continue
        print(f"BUY {symbol} 1 @ {price:.2f} - last sell was {last_sell}")
        try:
            order = trading.submit_order(MarketOrderRequest(symbol=symbol, qty=1, side=OrderSide.BUY, time_in_force=TimeInForce.DAY))
            fill = get_fill(order.id) or price
            print(f"BUY filled at {fill:.2f}")
            state[symbol]["entry_price"] = fill
            state[symbol]["max_price"] = fill
            state[symbol]["entry_time"] = now_ts
        except Exception as e:
            print(f"Buy err {e}")
    else:
        print(f"{symbol} already holds {real[symbol]['qty']} - no buy")

save_state(state)
print(f"Done - BREAKEVEN {BREAKEVEN*100:.3f}% fees")
