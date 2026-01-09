import requests

# ===================== JUPITER API SNIPPET =====================
TOKEN_API = "https://lite-api.jup.ag/tokens/v2/search"
HEADERS = {"User-Agent": "Mozilla/5.0"}

def fetch_jupiter_token_info(mint_address):
    resp = requests.get(f"{TOKEN_API}?query={mint_address}", headers=HEADERS)
    if resp.status_code != 200:
        return None
    data = resp.json()
    return data[0] if data else None

# ===================== EXECUTION & FORMATTING =====================
token_mint = "8y45AJzCUBSZL1UDFQRzCKovQBLQFudBrpPeg5yNpump"
data = fetch_jupiter_token_info(token_mint)

if data:
    print(f"Token: {data.get('name')} ({data.get('symbol')})")
    print("-" * 30)

    # Accessing the price change for different timeframes
    intervals = ['stats5m', 'stats1h', 'stats6h', 'stats24h']
    labels = ['5 Minutes', '1 Hour', '6 Hours', '24 Hours']

    for key, label in zip(intervals, labels):
        stats = data.get(key, {})
        change = stats.get('priceChange', 0)

        # Adding a plus sign for positive numbers and rounding to 2 decimals
        prefix = "+" if change > 0 else ""
        print(f"Price Change ({label}): {prefix}{change:.2f}%")
else:
    print("No data found for this mint address.")