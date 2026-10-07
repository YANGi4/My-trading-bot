import os
import alpaca_trade_api as tradeapi
print("=== FORCE BUY TEST #10 ===")
key = os.getenv("ALPACA_API_KEY")
sec = os.getenv("ALPACA_SECRET_KEY") or os.getenv("ALPACA_API_SECRET")
base = os.getenv("ALPACA_BASE_URL") or "https://paper-api.alpaca.markets"
api = tradeapi.REST(key, sec, base)
print(f"Cash: {api.get_account().cash}")
print(f"Positions: {len(api.list_positions())}")
o = api.submit_order(symbol="AAPL", qty=1, side="buy", type="market", time_in_force="day")
print(f"ORDER SENT: {o.id} - CHECK YOUR ALPACA NOW!")
