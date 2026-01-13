# scanner.py
# Playwright (Stable Fix) + OCR + Dexscreener search utilities + SQLite Integration

import time
import re
import requests
import os
import sqlite3
import sys
from datetime import datetime, timezone
from PIL import Image as PILImage, ImageEnhance
import pytesseract
from typing import List, Tuple, Optional, Dict

# Switch to Playwright for the "Forever Fix"
from playwright.sync_api import sync_playwright

# Database configuration
DB_PATH = "scanner_data.db"

# Force Tesseract Path for Remote Servers
pytesseract.pytesseract.tesseract_cmd = r'/usr/bin/tesseract'

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

# ----- formatting -----
def format_age_dynamic(created_timestamp_ms: int) -> str:
    created_dt = datetime.fromtimestamp(created_timestamp_ms / 1000, tz=timezone.utc)
    now = datetime.now(timezone.utc)
    delta = now - created_dt
    total_minutes = int(delta.total_seconds() // 60)
    if total_minutes < 60: return f"{total_minutes}m"
    total_hours = total_minutes // 60
    if total_hours < 24: return f"{total_hours}h {total_minutes % 60}m"
    return f"{total_hours // 24}d {total_hours % 24}h"

# ----- Dexscreener profile fetch -----
def get_profile_info(token_mint: str) -> Optional[Dict]:
    url = f"https://api.dexscreener.com/latest/dex/search?q={token_mint}"
    try:
        # Added 5s timeout to prevent hanging
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
        "socials": info.get("socials")
    }

# ----- Collector -----
new_pairs_to_buy: List[str] = []

def collect_new_pair(token_mint: str) -> None:
    if token_mint not in new_pairs_to_buy:
        new_pairs_to_buy.append(token_mint)

# ----- Search Logic -----
def search_solana_by_mint(token_mint: str) -> None:
    url = f"https://api.dexscreener.com/latest/dex/search?q={token_mint}"
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"❌ API Error for {token_mint}: {e}", flush=True)
        return

    pairs = data.get("pairs", [])
    seen_pairs = load_seen_pairs()

    for p in pairs:
        if p.get("chainId") == "solana" and p.get("dexId") == "pumpswap":
            pair_address = p.get("pairAddress")
            token_mint_address = p.get("baseToken", {}).get("address")
            
            if not token_mint_address.endswith("pump") or pair_address in seen_pairs:
                continue

            profile = get_profile_info(token_mint_address)
            if profile:
                print(f"🆕 NEW: {profile['token_name']} ({profile['token_symbol']})", flush=True)
                save_seen_pair(pair_address)
                collect_new_pair(token_mint_address)

# ----- THE FOREVER FIX: Playwright Engine -----
def run_selenium_screenshot(screenshot_path: str = "/tmp/dexscreener_full_screenshot.png", headless: bool = True) -> str:
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
        )
        context = browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        try:
            url = "https://dexscreener.com/?rankBy=pairAge&order=asc&chainIds=solana&dexIds=pumpswap,pumpfun&maxAge=2&profile=1"
            print(f"🚀 Navigating to Dexscreener...", flush=True)
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            print("⏳ Page Loaded. Rendering table...", flush=True)
            page.wait_for_timeout(10000)

            for _ in range(2):
                page.mouse.wheel(0, 2000)
                page.wait_for_timeout(1000)

            page.screenshot(path=screenshot_path, full_page=True)
            print(f"✅ Screenshot saved: {screenshot_path}", flush=True)
        except Exception as e:
            print(f"❌ Playwright Error: {e}", flush=True)
        finally:
            browser.close()
    return screenshot_path

# ----- OCR Engine -----
def ocr_extract_pair_symbols(screenshot_path: str) -> List[str]:
    print("🔍 Processing OCR...", flush=True)
    img = PILImage.open(screenshot_path).convert('L')
    img = img.resize((img.width*2, img.height*2))
    img = ImageEnhance.Contrast(img).enhance(2.0)

    # Added PSM config for better table reading
    text = pytesseract.image_to_string(img, config='--psm 6')
    
    pair_symbols = list(set(re.findall(r'([A-Za-z0-9]{3,10})\s*/', text)))
    print(f"🎯 Symbols Found: {pair_symbols}", flush=True)
    return pair_symbols

def run_scan_and_search() -> List[str]:
    global new_pairs_to_buy
    new_pairs_to_buy = []

    shot = run_selenium_screenshot()
    symbols = ocr_extract_pair_symbols(shot)
    
    if not symbols:
        print("📭 No symbols detected in OCR.", flush=True)
        return []

    for sym in symbols:
        print(f"🔎 API Search: {sym}", flush=True)
        search_solana_by_mint(sym)
        time.sleep(0.5)

    print("🏁 Scan Complete.", flush=True)
    return symbols

if __name__ == "__main__":
    run_scan_and_search()
