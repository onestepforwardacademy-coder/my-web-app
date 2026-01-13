# scanner.py
# Playwright (Stable Fix) + OCR + Dexscreener search utilities

import time
import re
import requests
import os
import sqlite3
from datetime import datetime, timezone
from PIL import Image as PILImage, ImageEnhance, ImageOps
import pytesseract
from typing import List, Tuple, Optional, Dict

# Switch to Playwright for the "Forever Fix"
from playwright.sync_api import sync_playwright
# NEW: Import stealth to bypass bot protection
try:
    from playwright_stealth import stealth_sync
except ImportError:
    stealth_sync = None

# Database path on your VPS
DB_PATH = "/root/my-web-app/scanner_data.db"

# ----- memory helpers -----
def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute('CREATE TABLE IF NOT EXISTS seen_pairs (pair_address TEXT PRIMARY KEY, found_at DATETIME DEFAULT CURRENT_TIMESTAMP)')
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
        print(f"❌ DB Load Error: {e}")
        return set()

def save_seen_pair(pair_address: str) -> None:
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("INSERT OR IGNORE INTO seen_pairs (pair_address) VALUES (?)", (pair_address,))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"❌ DB Save Error: {e}")

# ----- formatting -----
def format_age_dynamic(created_timestamp_ms: int) -> str:
    created_dt = datetime.fromtimestamp(created_timestamp_ms / 1000, tz=timezone.utc)
    now = datetime.now(timezone.utc)
    delta = now - created_dt
    total_minutes = int(delta.total_seconds() // 60)
    if total_minutes < 60:
        return f"{total_minutes}m"
    total_hours = total_minutes // 60
    minutes = total_minutes % 60
    if total_hours < 24:
        return f"{total_hours}h {minutes}m"
    return f"{total_hours // 24}d"

# ----- Dexscreener profile fetch -----
def get_profile_info(token_mint: str) -> Optional[Dict]:
    url = f"https://api.dexscreener.com/latest/dex/search?q={token_mint}"
    try:
        response = requests.get(url, timeout=10)
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

# ----- Collector / public list -----
new_pairs_to_buy: List[str] = []

def collect_new_pair(token_mint: str) -> None:
    if token_mint not in new_pairs_to_buy:
        new_pairs_to_buy.append(token_mint)

# ----- Dexscreener search for Solana mint -----
def search_solana_by_mint(token_mint: str) -> None:
    url = f"https://api.dexscreener.com/latest/dex/search?q={token_mint}"
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"❌ Failed to fetch Dexscreener data for {token_mint}: {e}")
        return

    pairs = data.get("pairs", [])
    sol_pairs = [p for p in pairs if p.get("chainId") == "solana"]
    pump_pairs = [p for p in sol_pairs if p.get("dexId") in ["pumpswap", "pumpfun"]]

    final_pairs: List[Tuple[dict, dict]] = []
    for p in pump_pairs:
        pair_created_at = p.get("pairCreatedAt")
        if not pair_created_at: continue
        age_minutes = (datetime.now(timezone.utc) - datetime.fromtimestamp(pair_created_at / 1000, tz=timezone.utc)).total_seconds() / 60
        if age_minutes > 120: continue
        
        token_mint_address = p.get("baseToken", {}).get("address")
        profile = get_profile_info(token_mint_address)
        if profile:
            final_pairs.append((p, profile))

    seen_pairs = load_seen_pairs()
    for i, (p, profile) in enumerate(final_pairs, 1):
        pair_address = p.get("pairAddress")
        token_mint = p.get("baseToken", {}).get("address")
        
        if not token_mint.endswith("pump"): continue

        if pair_address in seen_pairs:
            print(f"♻️ {profile['token_symbol']} APPEARED BEFORE")
        else:
            print(f"🆕 NEW TOKEN: {profile['token_symbol']}")
            save_seen_pair(pair_address)
            collect_new_pair(token_mint)

# ----- THE FOREVER FIX: Playwright Engine -----
def run_selenium_screenshot(
    screenshot_path: str = "/tmp/dexscreener_full_screenshot.png",
    headless: bool = True
) -> str:
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"]
        )
        
        context = browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        if stealth_sync:
            stealth_sync(page)

        try:
            url = "https://dexscreener.com/?rankBy=pairAge&order=asc&chainIds=solana&dexIds=pumpswap,pumpfun&maxAge=2&profile=1"
            
            # FIX 1: Changed 'networkidle' to 'domcontentloaded' to avoid forever-hanging
            print(f"🚀 Navigating to Dexscreener...")
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            
            # FIX 2: Wait for table with a strict timeout
            print("⏳ Waiting for data table...")
            try:
                # Wait up to 20 seconds for the table rows
                page.wait_for_selector('a.ds-dex-table-row', timeout=20000)
                print("✅ Table rows detected!")
            except:
                print("⚠️ Table didn't load in 20s. Likely blocked or challenge page.")
                # FIX 3: Save a debug view to see what's happening
                page.screenshot(path="/tmp/debug_view.png")
                print("📸 Check /tmp/debug_view.png to see what the bot sees.")

            page.wait_for_timeout(3000) 

            # Take high-def screenshot
            page.screenshot(path=screenshot_path, full_page=True)
            print(f"✅ Success: Screenshot saved to {screenshot_path}")

        except Exception as e:
            print(f"❌ Screenshot Error: {e}")
        finally:
            browser.close()

    return screenshot_path

def ocr_extract_pair_symbols(screenshot_path: str) -> List[str]:
    print("🔍 Analyzing screenshot for symbols...")
    try:
        img = PILImage.open(screenshot_path).convert('L')
        img = img.resize((img.width * 3, img.height * 3), resample=PILImage.LANCZOS)
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(2.5)
        
        # PSM 11 is good for sparse text like tables
        custom_config = r'--psm 11 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789/'
        text = pytesseract.image_to_string(img, config=custom_config)
        
        pattern = re.compile(r'([A-Z0-9]{3,})\s*/')
        pair_symbols = list(dict.fromkeys(pattern.findall(text.upper())))
        return pair_symbols
    except Exception as e:
        print(f"❌ OCR Process Error: {e}")
        return []

def run_scan_and_search() -> List[str]:
    init_db()
    global new_pairs_to_buy
    new_pairs_to_buy = []

    shot = run_selenium_screenshot()
    if not os.path.exists(shot) or os.path.getsize(shot) == 0:
        return []

    pair_symbols = ocr_extract_pair_symbols(shot)
    if not pair_symbols:
        print("⚠️ No symbols found. The table might be empty.")
        return []

    print(f"✅ Found {len(pair_symbols)} potential symbols. Searching...\n")
    for token in pair_symbols:
        search_solana_by_mint(token)

    return new_pairs_to_buy

if __name__ == "__main__":
    run_scan_and_search()
