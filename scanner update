# scanner.py
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

# Playwright Engine
from playwright.sync_api import sync_playwright

# Database configuration
DB_PATH = "scanner_data.db"

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
        print(f"❌ DB Load Error: {e}")
        return set()

def save_seen_pair(pair_address: str) -> None:
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO seen_pairs (pair_address) VALUES (?)", (pair_address,))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"❌ DB Save Error: {e}")

# ----- Dexscreener API Fetch -----
def get_profile_info(token_mint: str) -> Optional[Dict]:
    url = f"https://api.dexscreener.com/latest/dex/search?q={token_mint}"
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
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
    except:
        return None

# ----- Search Logic -----
new_pairs_to_buy: List[str] = []

def search_solana_by_mint(token_mint: str) -> None:
    print(f"📡 API Check: {token_mint}")
    url = f"https://api.dexscreener.com/latest/dex/search?q={token_mint}"
    try:
        r = requests.get(url, timeout=10)
        data = r.json()
    except:
        return

    pairs = data.get("pairs", [])
    seen_pairs = load_seen_pairs()

    for p in pairs:
        if p.get("chainId") == "solana" and p.get("dexId") == "pumpswap":
            pair_addr = p.get("pairAddress")
            mint_addr = p.get("baseToken", {}).get("address")

            if pair_addr in seen_pairs:
                continue

            if not mint_addr.endswith("pump"):
                continue

            print(f"🌟 Found New: {mint_addr}")
            save_seen_pair(pair_addr)
            if mint_addr not in new_pairs_to_buy:
                new_pairs_to_buy.append(mint_addr)

# ----- Playwright Screenshot (The "No Output" Fix) -----
def run_selenium_screenshot(screenshot_path: str = "scan.png") -> str:
    print("🚀 Starting Playwright Browser...")
    with sync_playwright() as p:
        # Args added to bypass VPS detection
        browser = p.chromium.launch(headless=True, args=[
            "--no-sandbox", 
            "--disable-setuid-sandbox",
            "--disable-blink-features=AutomationControlled"
        ])
        
        context = browser.new_context(
            viewport={'width': 1280, 'height': 1000},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        try:
            target_url = "https://dexscreener.com/?rankBy=pairAge&order=asc&chainIds=solana&dexIds=pumpswap,pumpfun&maxAge=2&profile=1"
            print(f"🌐 Loading: {target_url}")
            
            # Using 'domcontentloaded' instead of 'networkidle' to prevent hanging
            page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
            
            print("⏳ Waiting for Dexscreener table...")
            page.wait_for_timeout(10000) # Give it 10s to load tokens
            
            page.screenshot(path=screenshot_path)
            print(f"📸 Screenshot Captured: {screenshot_path}")
            
        except Exception as e:
            print(f"❌ Playwright Failed: {e}")
        finally:
            browser.close()
            
    return screenshot_path

# ----- OCR Logic -----
def ocr_extract_pair_symbols(screenshot_path: str) -> List[str]:
    print("🔍 OCR Reading...")
    if not os.path.exists(screenshot_path):
        print("❌ Error: Screenshot file not found!")
        return []

    img = PILImage.open(screenshot_path).convert('L')
    img = ImageEnhance.Contrast(img).enhance(2.0)
    
    text = pytesseract.image_to_string(img)
    print(f"📝 Raw OCR Data Length: {len(text)}")
    
    symbols = list(set(re.findall(r'([A-Z0-9]{3,10})\s*/', text)))
    print(f"✅ Found Symbols: {symbols}")
    return symbols

# ----- Main Run -----
def run_scan_and_search() -> List[str]:
    global new_pairs_to_buy
    new_pairs_to_buy = []
    
    print(f"\n--- SCAN START [{datetime.now().strftime('%H:%M:%S')}] ---")
    
    path = run_selenium_screenshot()
    symbols = ocr_extract_pair_symbols(path)
    
    for s in symbols:
        search_solana_by_mint(s)
        
    print(f"--- SCAN FINISHED ---\n")
    return new_pairs_to_buy

# This part ensures it runs when you type 'python3 scanner.py'
if __name__ == "__main__":
    run_scan_and_search()
