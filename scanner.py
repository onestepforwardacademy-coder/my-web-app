# scanner.py
# Playwright (Stable Fix) + OCR + Dexscreener search utilities

import time
import re
import requests
import os
import sqlite3 # Updated: Added for database support
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
    # If not installed, we skip it but recommend installing it
    stealth_sync = None

# Updated: Database path on your VPS
DB_PATH = "/root/my-web-app/scanner_data.db"

# ----- memory helpers (Updated to use SQLite) -----
def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute('CREATE TABLE IF NOT EXISTS seen_pairs (pair_address TEXT PRIMARY KEY, found_at DATETIME DEFAULT CURRENT_TIMESTAMP)')
    conn.close()

def load_seen_pairs() -> set:
    """Updated: Fetches seen pairs from Database instead of txt file"""
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
    """Updated: Saves seen pair to Database instead of txt file"""
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
    total_days = total_hours // 24
    hours = total_hours % 24
    if total_days < 30:
        return f"{total_days}d {hours}h"
    total_months = total_days // 30
    days = total_days % 30
    if total_months < 12:
        return f"{total_months}m {days}d"
    years = total_months // 12
    months = total_months % 12
    return f"{years}y {months}m"

# ----- Dexscreener profile fetch -----
def get_profile_info(token_mint: str) -> Optional[Dict]:
    url = f"https://api.dexscreener.com/latest/dex/search?q={token_mint}"
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
    except Exception:
        return None

    pairs = data.get("pairs")
    if not pairs:
        return None

    pair = pairs[0]
    info = pair.get("info", {})

    token_name = pair.get("baseToken", {}).get("name", "Unknown")
    token_symbol = pair.get("baseToken", {}).get("symbol", "")
    pair_url = pair.get("url")

    return {
        "token_name": token_name,
        "token_symbol": token_symbol,
        "pair_url": pair_url,
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
    # Adjusting dexId check as pump.fun pairs often use 'pumpswap' or 'pumpfun'
    pump_pairs = [p for p in sol_pairs if p.get("dexId") in ["pumpswap", "pumpfun"]]

    final_pairs: List[Tuple[dict, dict]] = []
    for p in pump_pairs:
        pair_created_at = p.get("pairCreatedAt")
        if not pair_created_at:
            continue
        age_minutes = (datetime.now(timezone.utc) -
                       datetime.fromtimestamp(pair_created_at / 1000, tz=timezone.utc)).total_seconds() / 60
        # Filter for tokens created in the last 120 minutes
        if age_minutes > 120:
            continue

        pair_address = p.get("pairAddress")
        token_mint_address = p.get("baseToken", {}).get("address")
        profile = get_profile_info(token_mint_address)
        if profile:
            final_pairs.append((p, profile))

    if not final_pairs:
        return

    seen_pairs = load_seen_pairs()

    for i, (p, profile) in enumerate(final_pairs, 1):
        pair_address = p.get("pairAddress")
        token_mint = p.get("baseToken", {}).get("address")
        dex = p.get("dexId")
        url = p.get("url")
        token_age = format_age_dynamic(p.get("pairCreatedAt"))

        if not token_mint.endswith("pump"):
            print(f"⚠️ SCAM TOKEN DETECTED: {token_mint} — do NOT buy!")
            continue

        if pair_address in seen_pairs:
            print("♻️ APPEARED BEFORE")
        else:
            print("🆕 NEW")
            save_seen_pair(pair_address)
            collect_new_pair(token_mint)

        print(f"{i}. Token Address (copyable): {token_mint}")
        print(f"    DEX: {dex}")
        print(f"    Token Age: {token_age}")
        print(f"    URL: {url}")
        if profile:
            print(f"    ✅ Profile FOUND on Dexscreener!")
            print(f"     🪙 Token: {profile['token_name']} ({profile['token_symbol']})")
            print(f"     🌐 Pair URL: {profile['pair_url']}")
            if profile['image']:
                print(f"     📸 Image: {profile['image']}")
            if profile['socials']:
                print(f"     🔗 Socials: {profile['socials']}")
        print("")

# ----- THE FOREVER FIX: Playwright Engine -----
def run_selenium_screenshot(
    screenshot_path: str = "/tmp/dexscreener_full_screenshot.png",
    headless: bool = True
) -> str:
    """
    Enhanced with 'networkidle' and Stealth to prevent blank results.
    """
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

        # Apply stealth if installed
        if stealth_sync:
            stealth_sync(page)

        try:
            url = "https://dexscreener.com/?rankBy=pairAge&order=asc&chainIds=solana&dexIds=pumpswap,pumpfun&maxAge=2&profile=1"
            
            # 1. Navigate - Using networkidle to ensure full load
            print(f"🚀 Navigating to Dexscreener...")
            page.goto(url, wait_until="networkidle", timeout=90000)
            
            # 2. WAIT FOR SELECTOR: Ensures table actually loaded
            print("⏳ Waiting for data table rows to appear...")
            try:
                page.wait_for_selector('a.ds-dex-table-row', timeout=30000)
                print("✅ Table rows detected!")
            except:
                print("⚠️ Timeout waiting for table rows. Taking screenshot anyway.")

            page.wait_for_timeout(5000) # Extra safety buffer

            # Full height scroll to trigger lazy loading
            for _ in range(2):
                page.mouse.wheel(0, 2000)
                page.wait_for_timeout(1000)

            # Take high-def screenshot
            page.screenshot(path=screenshot_path, full_page=True)
            print(f"✅ Success: Screenshot saved to {screenshot_path}")

        except Exception as e:
            print(f"❌ Screenshot Error: {e}")
        finally:
            browser.close()

    return screenshot_path

def ocr_extract_pair_symbols(screenshot_path: str) -> List[str]:
    """
    Improved OCR with grayscale, resizing, and contrast enhancement.
    """
    print("🔍 Analyzing screenshot for symbols...")
    try:
        img = PILImage.open(screenshot_path)
        
        # 1. Convert to Grayscale
        img = img.convert('L') 
        
        # 2. Rescale Up (3x) to make small fonts clearer
        img = img.resize((img.width * 3, img.height * 3), resample=PILImage.LANCZOS)
        
        # 3. Increase Contrast
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(2.5)
        
        # 4. Use PSM 11 for Sparse Text (Tables) and whitelist common symbol chars
        custom_config = r'--psm 11 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789/'
        text = pytesseract.image_to_string(img, config=custom_config)
        
        if not text.strip():
            print("⚠️ Tesseract could not read any text. Check image quality.")
            return []

        lines = text.splitlines()
        pair_symbols: List[str] = []
        # Pattern looks for symbols followed by a slash (e.g., "SOL/")
        pattern = re.compile(r'([A-Z0-9]{3,})\s*/')

        for line in lines:
            matches = pattern.findall(line.upper())
            for match in matches:
                pair_symbols.append(match)

        # Remove duplicates
        pair_symbols = list(dict.fromkeys(pair_symbols))
        return pair_symbols
    except Exception as e:
        print(f"❌ OCR Process Error: {e}")
        return []

def run_scan_and_search() -> List[str]:
    init_db() # Ensure DB is created
    global new_pairs_to_buy
    new_pairs_to_buy = []

    shot = run_selenium_screenshot()
    
    # Check if file exists before processing
    if not os.path.exists(shot) or os.path.getsize(shot) == 0:
        print("❌ Screenshot failed or is empty. Check Playwright logs.")
        return []

    pair_symbols = ocr_extract_pair_symbols(shot)
    
    # Validation check
    if not pair_symbols:
        print("⚠️ No symbols found in this scan. The site might be blocking or empty.")
        return []

    print(f"✅ Found {len(pair_symbols)} total potential symbols. Searching profiles...\n")
    
    for token in pair_symbols:
        # Search by symbol (though Search by Mint is safer if we had the mint)
        # Note: OCR currently gets symbols (SOL, PEPE). Dex API search handles symbols.
        search_solana_by_mint(token)

    return new_pairs_to_buy

# ----- EXECUTION TRIGGER -----
if __name__ == "__main__":
    run_scan_and_search()
