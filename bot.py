import os
import alpaca_trade_api as tradeapi
print("=== FORCE BUY TEST ===")
key = os.getenv("ALPACA_API_KEY") or os.getenv("APCA_API_KEY_ID")
sec = os.getenv("ALPACA_SECRET_KEY") or os.getenv("ALPACA_API_SECRET")
base = os.getenv("ALPACA_BASE_URL") or "https://paper-api.alpaca.markets"
api = tradeapi.REST(key, sec, base)
print(f"Cash: {api.get_account().cash}")
pos = api.list_positions()
print(f"Positions before: {len(pos)}")
if len(pos)==0:
    o=api.submit_order(symbol="AAPL", qty=1, side="buy", type="market", time_in_force="day")
    print(f"ORDER SENT: {o.id}")
else:
    print("Already has position")
