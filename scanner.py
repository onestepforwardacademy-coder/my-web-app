# scanner.py
# Selenium + OCR + Dexscreener search utilities

import time
import re
import requests
import os
from datetime import datetime, timezone
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from PIL import Image as PILImage, ImageEnhance
import pytesseract
from typing import List, Tuple, Optional, Dict

# Keep your existing driver manager import for path fixes
from webdriver_manager.chrome import ChromeDriverManager

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
    if total_minutes < 60: return f"{total_minutes}m"
    total_hours = total_minutes // 60
    if total_hours < 24: return f"{total_hours}h {total_minutes % 60}m"
    return f"{total_hours // 24}d {total_hours % 24}h"

# ----- Dexscreener profile fetch -----
def get_profile_info(token_mint: str) -> Optional[Dict]:
    url = f"https://api.dexscreener.com/latest/dex/search?q={token_mint}"
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
    except Exception: return None

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
        data = r.json()
    except: return

    pairs = data.get("pairs", [])
    seen_pairs = load_seen_pairs()

    for p in pairs:
        if p.get("chainId") != "solana" or p.get("dexId") != "pumpswap": continue
        
        pair_created_at = p.get("pairCreatedAt")
        if not pair_created_at: continue

        age_min = (datetime.now(timezone.utc) - datetime.fromtimestamp(pair_created_at / 1000, tz=timezone.utc)).total_seconds() / 60
        if age_min > 120: continue

        token_mint_address = p.get("baseToken", {}).get("address")
        if not token_mint_address.endswith("pump"): continue

        pair_address = p.get("pairAddress")
        if pair_address in seen_pairs:
            print("♻️ APPEARED BEFORE")
        else:
            print(f"🆕 NEW: {token_mint_address}")
            save_seen_pair(pair_address)
            collect_new_pair(token_mint_address)
            
            profile = get_profile_info(token_mint_address)
            if profile:
                print(f"✅ Profile: {profile['token_name']} ({profile['token_symbol']})")

# ----- Selenium + OCR screenshot and parse -----
def run_selenium_screenshot(screenshot_path: str = "/tmp/dex_shot.png", headless: bool = True) -> str:
    chrome_options = Options()
    
    # YOUR CONFIG: Dynamic Binary Detection
    vps_path = "/usr/bin/google-chrome"
    if os.path.exists(vps_path):
        chrome_options.binary_location = vps_path
    
    if headless:
        chrome_options.add_argument("--headless=new")
    
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu") 
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")

    # 🔥 SPEED FIX: Disable Images & CSS to load Dexscreener instantly
    prefs = {"profile.managed_default_content_settings.images": 2}
    chrome_options.add_experimental_option("prefs", prefs)

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)

    try:
        url = "https://dexscreener.com/?rankBy=pairAge&order=asc&chainIds=solana&dexIds=pumpswap,pumpfun&maxAge=2&profile=1"
        driver.get(url)

        # 🔥 SPEED FIX: Replace fixed time.sleep(6) with Smart Wait
        # This moves the second the table appears
        WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.CLASS_NAME, "ds-dex-table-row")))

        # Simplified Scroll
        driver.execute_script("window.scrollTo(0, 1000);")
        time.sleep(1) 

        driver.save_screenshot(screenshot_path)
        print(f"✅ Screenshot saved: {screenshot_path}")
    finally:
        driver.quit()

    return screenshot_path

def ocr_extract_pair_symbols(screenshot_path: str) -> List[str]:
    img = PILImage.open(screenshot_path).convert('L') 
    img = img.resize((img.width*2, img.height*2))
    img = ImageEnhance.Contrast(img).enhance(2.0)

    # 🔥 SPEED FIX: PSM 11 is optimized for sparse table data
    text = pytesseract.image_to_string(img, config='--psm 11')
    
    pattern = re.compile(r'([A-Za-z0-9]+)\s*/')
    return list(dict.fromkeys([m.upper() for m in pattern.findall(text)]))

def run_scan_and_search() -> List[str]:
    global new_pairs_to_buy
    new_pairs_to_buy = []

    shot = run_selenium_screenshot()
    pair_symbols = ocr_extract_pair_symbols(shot)
    print(f"✅ Found {len(pair_symbols)} pair symbols. Searching profiles...\n")

    for token in set(pair_symbols):
        search_solana_by_mint(token)

    return pair_symbols
