import requests
import sys
def format_num(n):
    try:
        n = float(n)
        if n >= 1e9: return f"{n/1e9:.2f}B"
        if n >= 1e6: return f"{n/1e6:.2f}M"
        if n >= 1e3: return f"{n/1e3:.2f}K"
        return f"{n:.2f}"
    except: return "0"
def search():
    if len(sys.argv) < 2: return
    addr = sys.argv[1]
    r = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{addr}")
    if r.status_code != 200 or not r.json().get('pairs'):
        print("❌ *Token Not Found*")
        return
    p = r.json()['pairs'][0]
    base = p['baseToken']
    print(f"🚀 *TOKEN FOUND: {base['name']} ({base['symbol']})*")
    print(f"📍 `Address: {addr}`")
    print(f"💰 *Price:* `${p['priceUsd']}`")
    print(f"💧 *Liquidity:* `${format_num(p['liquidity']['usd'])}`")
    print(f"📊 *MCap:* `${format_num(p['marketCap'])}`")
    print(f"📈 *24h Change:* `{p['priceChange']['h24']}%`")
    print(f"🔄 *24h Vol:* `${format_num(p['volume']['h24'])}`")
    print(f"🔗 [View on Dexscreener](https://dexscreener.com/solana/{addr})")
if __name__ == "__main__": search()
