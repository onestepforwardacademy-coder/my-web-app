# scanner.py
# Playwright (Stable Fix) + OCR + Dexscreener search utilities

import time
import re
import requests
import os
from datetime import datetime, timezone
from PIL import Image as PILImage, ImageEnhance
import pytesseract
from typing import List, Tuple, Optional, Dict

# Switch to Playwright for the "Forever Fix"
from playwright.sync_api import sync_playwright

SEEN_PAIRS_FILE = "seen_pairs.txt"

# ----- memory helpers -----
def load_seen_pairs() -> set:
    try:
        with open(SEEN_PAIRS_FILE, "r") as f:
            return set(line.strip() for line in f.readlines())
    except FileNotFoundError:
        return set()

def save_seen_pair(pair_address: str) -> None:
    with open(SEEN_PAIRS_FILE, "a") as f:
        f.write(pair_address + "\n")

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
    pump_pairs = [p for p in sol_pairs if p.get("dexId") == "pumpswap"]

    final_pairs: List[Tuple[dict, dict]] = []
    for p in pump_pairs:
        pair_created_at = p.get("pairCreatedAt")
        if not pair_created_at:
            continue
        age_minutes = (datetime.now(timezone.utc) -
                       datetime.fromtimestamp(pair_created_at / 1000, tz=timezone.utc)).total_seconds() / 60
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
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        
        context = browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        # SPEED OPTIMIZATION: Block heavy assets that are not needed for OCR
        page.route("**/*.{png,jpg,jpeg,svg,gif,webp,css,woff,pdf}", lambda route: route.abort())

        try:
            url = "https://dexscreener.com/?rankBy=pairAge&order=asc&chainIds=solana&dexIds=pumpswap,pumpfun&maxAge=2&profile=1"
            
            # Using 'domcontentloaded' is much faster than 'networkidle'
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            
            # SMART WAIT: Wait for the actual token table instead of a 7s timer
            page.wait_for_selector(".ds-dex-table-row", timeout=15000)

            # Full height scroll logic - kept but reduced timeout for speed
            for _ in range(3):
                page.mouse.wheel(0, 4000)
                page.wait_for_timeout(500) # Reduced from 1500 to 500

            # Take high-def screenshot
            page.screenshot(path=screenshot_path, full_page=True)
            print(f"✅ Success: Screenshot saved to {screenshot_path}")

        except Exception as e:
            print(f"❌ Screenshot Error: {e}")
        finally:
            browser.close()

    return screenshot_path

def ocr_extract_pair_symbols(screenshot_path: str) -> List[str]:
    img = PILImage.open(screenshot_path)
    img = img.convert('L') 
    img = img.resize((img.width*2, img.height*2))
    enhancer = ImageEnhance.Contrast(img)
    img = enhancer.enhance(2.0)

    # Added config for sparse text detection (much faster for tables)
    text = pytesseract.image_to_string(img, config='--psm 11')
    lines = text.splitlines()

    pair_symbols: List[str] = []
    pattern = re.compile(r'([A-Za-z0-9]+)\s*/')

    for line in lines:
        line = line.strip()
        matches = pattern.findall(line)
        for match in matches:
            pair_symbols.append(match.upper())

    pair_symbols = list(dict.fromkeys(pair_symbols))
    return pair_symbols

def run_scan_and_search() -> List[str]:
    global new_pairs_to_buy
    new_pairs_to_buy = []

    shot = run_selenium_screenshot()
    pair_symbols = ocr_extract_pair_symbols(shot)
    print(f"✅ Found {len(pair_symbols)} total pair symbols. Searching profiles...\n")

    # Use a set to avoid searching the same token twice if OCR finds it multiple times
    for token in set(pair_symbols):
        search_solana_by_mint(token)

    return pair_symbols
