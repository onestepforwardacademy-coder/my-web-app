#!/usr/bin/env python3
import sys
import requests

if len(sys.argv) < 2:
    print("ERROR: No token address provided")
    sys.exit(1)

token_address = sys.argv[1]
DEX_API = "https://api.dexscreener.com/token-pairs/v1/solana"
TOKEN_API = "https://lite-api.jup.ag/tokens/v2/search"

def format_num(n):
    if n is None or n == "N/A":
        return "N/A"
    try:
        n = float(n)
        if n >= 1_000_000_000:
            return f"${n/1_000_000_000:.2f}B"
        elif n >= 1_000_000:
            return f"${n/1_000_000:.2f}M"
        elif n >= 1_000:
            return f"${n/1_000:.2f}K"
        else:
            return f"${n:.4f}"
    except:
        return str(n)

def search_token():
    try:
        # Fetch from Dexscreener
        resp = requests.get(f"{DEX_API}/{token_address}", timeout=10)
        if resp.status_code != 200 or not resp.json():
            print(f"ERROR: Token not found on Dexscreener")
            return
        
        pair = resp.json()[0]
        base = pair.get("baseToken", {})
        quote = pair.get("quoteToken", {})
        
        name = base.get("name", "Unknown")
        symbol = base.get("symbol", "???")
        price_usd = pair.get("priceUsd", "N/A")
        price_native = pair.get("priceNative", "N/A")
        
        liq = pair.get("liquidity", {})
        liq_usd = liq.get("usd", 0)
        liq_base = liq.get("base", 0)
        liq_quote = liq.get("quote", 0)
        
        fdv = pair.get("fdv", 0)
        mcap = pair.get("marketCap", 0)
        
        vol = pair.get("volume", {})
        vol_24h = vol.get("h24", 0)
        vol_6h = vol.get("h6", 0)
        vol_1h = vol.get("h1", 0)
        
        chg = pair.get("priceChange", {})
        chg_24h = chg.get("h24", 0)
        chg_6h = chg.get("h6", 0)
        chg_1h = chg.get("h1", 0)
        
        txns = pair.get("txns", {})
        buys_24h = txns.get("h24", {}).get("buys", 0)
        sells_24h = txns.get("h24", {}).get("sells", 0)
        
        pair_addr = pair.get("pairAddress", "N/A")
        dex_id = pair.get("dexId", "N/A")
        
        # Build output
        print("="*42)
        print(f"TOKEN: {name} ({symbol})")
        print("="*42)
        print(f"Address: {token_address[:20]}...")
        print(f"DEX: {dex_id}")
        print(f"Pair: {pair_addr[:20]}...")
        print("-"*42)
        print("PRICE")
        print(f"  USD: ${price_usd}")
        print(f"  SOL: {price_native}")
        print("-"*42)
        print("MARKET")
        print(f"  FDV: {format_num(fdv)}")
        print(f"  MCap: {format_num(mcap)}")
        print(f"  Liquidity: {format_num(liq_usd)}")
        print("-"*42)
        print("VOLUME")
        print(f"  24h: {format_num(vol_24h)}")
        print(f"  6h: {format_num(vol_6h)}")
        print(f"  1h: {format_num(vol_1h)}")
        print("-"*42)
        print("PRICE CHANGE")
        e24 = "" if float(chg_24h or 0) >= 0 else ""
        e6 = "" if float(chg_6h or 0) >= 0 else ""
        e1 = "" if float(chg_1h or 0) >= 0 else ""
        print(f"  24h: {e24} {chg_24h}%")
        print(f"  6h: {e6} {chg_6h}%")
        print(f"  1h: {e1} {chg_1h}%")
        print("-"*42)
        print("TRANSACTIONS (24h)")
        print(f"  Buys: {buys_24h} | Sells: {sells_24h}")
        
        ratio = buys_24h / sells_24h if sells_24h > 0 else 0
        if buys_24h == 0 and sells_24h == 0:
            print("  Status: NO ACTIVITY")
        elif sells_24h == 0:
            print("  Status: POSSIBLE HONEYPOT")
        elif ratio > 2:
            print("  Status: BULLISH")
        elif ratio < 0.5:
            print("  Status: BEARISH")
        else:
            print("  Status: NEUTRAL")
        print("="*42)
        
    except Exception as e:
        print(f"ERROR: {e}")

if __name__ == "__main__":
    search_token()
