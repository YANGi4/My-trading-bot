import os
print("=== DEBUG SECRETS ===")
k1 = os.getenv("ALPACA_API_KEY")
k2 = os.getenv("ALPACA_SECRET_KEY")
k3 = os.getenv("ALPACA_API_SECRET")
base = os.getenv("ALPACA_BASE_URL")
print(f"ALPACA_API_KEY exists: {bool(k1)} prefix: {(k1 or '')[:6]} len:{len(k1 or '')}")
print(f"ALPACA_SECRET_KEY exists: {bool(k2)} len:{len(k2 or '')}")
print(f"ALPACA_API_SECRET exists: {bool(k3)} len:{len(k3 or '')}")
print(f"ALPACA_BASE_URL: '{base}'")
if not k1:
    print("ERROR: ALPACA_API_KEY secret is MISSING in GitHub Settings!")
