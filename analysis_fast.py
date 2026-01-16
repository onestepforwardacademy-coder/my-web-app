#!/usr/bin/env python3
import sys
import requests

if len(sys.argv) < 2:
    print("ERROR: No token address")
    sys.exit(1)

token = sys.argv[1]

def format_num(n):
    if n is None: return "N/A"
    n = float(n)
    if n >= 1e9: return f"{n/1e9:.2f}B"
    if n >= 1e6: return f"{n/1e6:.2f}M"
    if n >= 1e3: return f"{n/1e3:.2f}K"
    return f"{n:.4f}"

try:
    # Dexscreener data
    r = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{token}", timeout=10)
    data = r.json()
    pair = data.get("pairs", [{}])[0] if data.get("pairs") else {}
    
    name = pair.get("baseToken", {}).get("name", "Unknown")
    symbol = pair.get("baseToken", {}).get("symbol", "???")
    price = pair.get("priceUsd", "0")
    mcap = pair.get("marketCap") or pair.get("fdv", 0)
    liq = pair.get("liquidity", {}).get("usd", 0)
    vol24 = pair.get("volume", {}).get("h24", 0)
    chg24 = pair.get("priceChange", {}).get("h24", 0)
    chg1h = pair.get("priceChange", {}).get("h1", 0)
    txns = pair.get("txns", {}).get("h24", {})
    buys = txns.get("buys", 0)
    sells = txns.get("sells", 0)
    created = pair.get("pairCreatedAt", 0)
    dex = pair.get("dexId", "unknown")
    
    # Calculate age
    if created:
        import time
        age_hrs = (time.time() * 1000 - created) / 3600000
        if age_hrs < 24:
            age_str = f"{age_hrs:.1f} hours"
        else:
            age_str = f"{age_hrs/24:.1f} days"
    else:
        age_str = "Unknown"
    
    # Safety score calculation
    score = 100
    warnings = []
    
    if liq and float(liq) < 10000:
        score -= 30
        warnings.append("LOW LIQUIDITY")
    if mcap and float(mcap) < 50000:
        score -= 20
        warnings.append("LOW MCAP")
    if buys + sells < 100:
        score -= 15
        warnings.append("LOW ACTIVITY")
    if created and age_hrs < 1:
        score -= 25
        warnings.append("VERY NEW (<1hr)")
    if sells > buys * 2:
        score -= 20
        warnings.append("HIGH SELL PRESSURE")
    
    # Risk level
    if score >= 80:
        risk = "LOW RISK"
        emoji = "🟢"
    elif score >= 50:
        risk = "MEDIUM RISK"
        emoji = "🟡"
    else:
        risk = "HIGH RISK"
        emoji = "🔴"
    
    print(f"""
{'='*45}
{emoji} TOKEN ANALYSIS: {name} ({symbol})
{'='*45}
Address: {token[:20]}...

📊 MARKET DATA
  Price: ${price}
  MCap: ${format_num(mcap)}
  Liquidity: ${format_num(liq)}
  24h Volume: ${format_num(vol24)}
  DEX: {dex}
  Age: {age_str}

📈 PRICE CHANGES
  1h: {chg1h}%
  24h: {chg24}%

🔄 TRANSACTIONS (24h)
  Buys: {buys} | Sells: {sells}
  Ratio: {buys/(sells or 1):.2f}

{'='*45}
{emoji} SAFETY SCORE: {score}/100 - {risk}
{'='*45}""")
    
    if warnings:
        print("⚠️ WARNINGS:")
        for w in warnings:
            print(f"  - {w}")
    
except Exception as e:
    print(f"ERROR: {e}")
