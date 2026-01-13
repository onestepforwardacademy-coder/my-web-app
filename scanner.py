# scanner.py
# API-Based Scanner with Scam Detection + SQLite Integration

import time
import requests
import sqlite3
import sys
from datetime import datetime, timezone
from typing import List, Optional, Dict

# Database configuration
DB_PATH = "scanner_data.db"
TOKEN_API = "https://lite-api.jup.ag/tokens/v2/search"
DEX_API_BASE = "https://api.dexscreener.com"
HEADERS = {"User-Agent": "Mozilla/5.0"}

# ----- Database Helpers -----
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS seen_pairs 
        (pair_address TEXT PRIMARY KEY, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)
    ''')
    conn.commit()
    conn.close()

def load_seen_pairs() -> set:
    init_db()
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT pair_address FROM seen_pairs")
        rows = cursor.fetchall()
        conn.close()
        return set(row[0] for row in rows)
    except Exception as e:
        print(f"❌ DB Load Error: {e}", flush=True)
        return set()

def save_seen_pair(pair_address: str) -> None:
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO seen_pairs (pair_address) VALUES (?)", (pair_address,))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"❌ DB Save Error: {e}", flush=True)

# ----- Formatting -----
def format_age_dynamic(created_timestamp_ms: int) -> str:
    created_dt = datetime.fromtimestamp(created_timestamp_ms / 1000, tz=timezone.utc)
    now = datetime.now(timezone.utc)
    delta = now - created_dt
    total_minutes = int(delta.total_seconds() // 60)
    if total_minutes < 60: return f"{total_minutes}m"
    total_hours = total_minutes // 60
    if total_hours < 24: return f"{total_hours}h {total_minutes % 60}m"
    return f"{total_hours // 24}d {total_hours % 24}h"

def format_number(n):
    if n in ["N/A", None]: return "N/A"
    try:
        n = float(n)
        if n >= 1_000_000: return f"${n/1_000_000:.2f}M"
        if n >= 1_000: return f"${n/1_000:.2f}K"
        return f"${n:.2f}"
    except:
        return str(n)

# ----- Dexscreener profile fetch -----
def get_profile_info(token_mint: str) -> Optional[Dict]:
    url = f"https://api.dexscreener.com/latest/dex/search?q={token_mint}"
    try:
        response = requests.get(url, timeout=5)
        data = response.json()
    except Exception:
        return None

    pairs = data.get("pairs")
    if not pairs: return None

    pair = pairs[0]
    info = pair.get("info", {})
    return {
        "token_name": pair.get("baseToken", {}).get("name", "Unknown"),
        "token_symbol": pair.get("baseToken", {}).get("symbol", ""),
        "pair_url": pair.get("url"),
        "image": info.get("imageUrl"),
        "socials": info.get("socials"),
        "price_usd": pair.get("priceUsd", "0"),
        "liquidity": pair.get("liquidity", {}).get("usd", 0),
        "market_cap": pair.get("marketCap", 0),
        "pair_created_at": pair.get("pairCreatedAt", 0)
    }

# ----- Jupiter Token Info (Audit Data) -----
def fetch_jupiter_token_info(mint_address: str) -> Optional[Dict]:
    try:
        resp = requests.get(f"{TOKEN_API}?query={mint_address}", headers=HEADERS, timeout=5)
        if resp.status_code != 200: return None
        data = resp.json()
        return data[0] if data else None
    except:
        return None

# ----- DEX Info (Honeypot Check) -----
def fetch_dex_info(token_address: str) -> Optional[Dict]:
    try:
        url = f"{DEX_API_BASE}/token-pairs/v1/solana/{token_address}"
        resp = requests.get(url, timeout=5)
        if resp.status_code != 200 or not resp.json(): return None
        
        pair = resp.json()[0]
        txns = pair.get("txns", {})
        
        buys_total = sum(txns.get(i, {}).get('buys', 0) for i in ["h24", "h6", "h1"])
        sells_total = sum(txns.get(i, {}).get('sells', 0) for i in ["h24", "h6", "h1"])
        
        liquidity_usd = pair.get('liquidity', {}).get('usd') or 0
        market_cap = pair.get('marketCap') or 0
        liq_ratio = (liquidity_usd / market_cap * 100) if market_cap else 0
        
        return {
            'honeypot': buys_total == 0 or sells_total == 0,
            'buys_24h': txns.get('h24', {}).get('buys', 0),
            'sells_24h': txns.get('h24', {}).get('sells', 0),
            'liq_vs_mcap_pct': liq_ratio
        }
    except:
        return None

# ----- Safety Score Calculator -----
def calculate_safety_score(token_info: Optional[Dict], dex_info: Optional[Dict]) -> tuple:
    score = 50
    warnings = []
    
    if token_info:
        audit = token_info.get('audit', {})
        
        if audit.get('mintAuthorityDisabled'):
            score += 20
        else:
            score -= 15
            warnings.append("Mint authority NOT disabled")
        
        if audit.get('freezeAuthorityDisabled'):
            score += 15
        else:
            score -= 10
            warnings.append("Freeze authority NOT disabled")
        
        top_holders = audit.get('topHoldersPercentage', 0)
        if top_holders > 50:
            score -= 20
            warnings.append(f"Top holders own {top_holders:.1f}%")
        elif top_holders > 30:
            score -= 10
        else:
            score += 10
        
        snipers = audit.get('snipersHoldingPercentage', 0)
        if snipers > 20:
            score -= 15
            warnings.append(f"Snipers hold {snipers:.1f}%")
    
    if dex_info:
        if dex_info.get('honeypot'):
            score -= 30
            warnings.append("Possible HONEYPOT")
        else:
            score += 10
        
        liq_ratio = dex_info.get('liq_vs_mcap_pct', 0)
        if liq_ratio < 5:
            score -= 15
            warnings.append(f"Low liquidity ({liq_ratio:.1f}%)")
    
    score = max(0, min(100, score))
    return score, warnings

# ----- Collector (same as original) -----
new_pairs_to_buy: List[str] = []

def collect_new_pair(token_mint: str) -> None:
    if token_mint not in new_pairs_to_buy:
        new_pairs_to_buy.append(token_mint)

# ----- Main Scanner (API-Based) -----
def run_scan_and_search() -> List[str]:
    global new_pairs_to_buy
    new_pairs_to_buy = []
    
    print(f"\n🚀 Starting Scan [{datetime.now().strftime('%H:%M:%S')}]...", flush=True)
    
    # Fetch latest token profiles from Dexscreener
    url = "https://api.dexscreener.com/token-profiles/latest/v1"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        tokens = response.json()
        print(f"📡 Fetched {len(tokens)} tokens from API", flush=True)
    except Exception as e:
        print(f"❌ API Error: {e}", flush=True)
        return []
    
    seen_pairs = load_seen_pairs()
    new_count = 0
    appeared_before_count = 0
    
    for token in tokens:
        chain = token.get("chainId", "")
        token_address = token.get("tokenAddress", "")
        
        # Filter: Solana + ends with pump
        if chain != "solana" or not token_address.endswith("pump"):
            continue
        
        # Check if NEW or APPEARED BEFORE
        is_new = token_address not in seen_pairs
        status_label = "🆕 NEW" if is_new else "🔄 APPEARED BEFORE"
        
        # Get pair details
        detail_url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
        try:
            detail_resp = requests.get(detail_url, timeout=5)
            detail_data = detail_resp.json()
            pairs = detail_data.get("pairs", [])
            
            if not pairs: continue
            pair = pairs[0]
            
            # Filter: pumpswap only
            if pair.get("dexId") != "pumpswap":
                continue
            
            pair_address = pair.get("pairAddress", "")
            base_token = pair.get("baseToken", {})
            name = base_token.get("name", "Unknown")
            symbol = base_token.get("symbol", "")
            price_usd = pair.get("priceUsd", "0")
            liquidity = pair.get("liquidity", {}).get("usd", 0)
            market_cap = pair.get("marketCap", 0)
            created_at = pair.get("pairCreatedAt", 0)
            age = format_age_dynamic(created_at) if created_at else "Unknown"
            
            # Fetch safety data
            token_info = fetch_jupiter_token_info(token_address)
            dex_info = fetch_dex_info(token_address)
            safety_score, warnings = calculate_safety_score(token_info, dex_info)
            
            # Safety label
            if safety_score >= 70:
                safety_label = "SAFE"
                safety_emoji = "🟢"
            elif safety_score >= 40:
                safety_label = "MEDIUM"
                safety_emoji = "🟡"
            else:
                safety_label = "RISKY"
                safety_emoji = "🔴"
            
            honeypot_status = "⚠️ HONEYPOT" if dex_info and dex_info.get('honeypot') else "✅ OK"
            
            # Print token info
            print("="*55, flush=True)
            print(f"{status_label}: {name} ({symbol})", flush=True)
            print(f"📍 Address: {token_address}", flush=True)
            print(f"💰 Price: ${price_usd} | Liq: {format_number(liquidity)} | MCap: {format_number(market_cap)}", flush=True)
            print(f"⏳ Age: {age}", flush=True)
            print(f"🍯 Honeypot: {honeypot_status}", flush=True)
            print(f"🛡️ Safety: {safety_emoji} {safety_score}/100 ({safety_label})", flush=True)
            
            if token_info:
                audit = token_info.get('audit', {})
                mint_ok = "✅" if audit.get('mintAuthorityDisabled') else "❌"
                freeze_ok = "✅" if audit.get('freezeAuthorityDisabled') else "❌"
                print(f"🔐 Mint: {mint_ok} | Freeze: {freeze_ok}", flush=True)
            
            if warnings:
                print(f"⚠️ Warnings: {', '.join(warnings)}", flush=True)
            
            print(f"🔗 https://dexscreener.com/solana/{token_address}", flush=True)
            
            # Only save and collect NEW tokens
            if is_new:
                save_seen_pair(token_address)
                collect_new_pair(token_address)
                new_count += 1
            else:
                appeared_before_count += 1
            
            time.sleep(0.3)
            
        except Exception as e:
            continue
    
    print(f"\n🏁 Scan Complete. {new_count} NEW | {appeared_before_count} APPEARED BEFORE", flush=True)
    return new_pairs_to_buy

if __name__ == "__main__":
    run_scan_and_search()
