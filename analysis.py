import requests
import sys
import asyncio
import cv2
import numpy as np
import os
from datetime import datetime, timezone
from playwright.async_api import async_playwright

TOKEN_API = "https://lite-api.jup.ag/tokens/v2/search"
HEADERS = {"User-Agent": "Mozilla/5.0"}
CHAIN = "solana"
DEX_API_BASE = "https://api.dexscreener.com"

def format_number(n):
    if n in ["N/A", None]: return "N/A"
    try:
        n = float(n)
        if n >= 1_000_000_000: return f"{n/1_000_000_000:.2f}B"
        elif n >= 1_000_000: return f"{n/1_000_000:.2f}M"
        elif n >= 1_000: return f"{n/1_000:.2f}K"
        elif n < 0.01: return f"{n:.6f}"
        else: return f"{n:.4f}"
    except: return str(n)

async def capture_chart(token_mint, filename="chart.png"):
    url = f"https://dexscreener.com/solana/{token_mint}?embed=1&theme=dark"
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
            page = await browser.new_page()
            await page.set_viewport_size({"width": 1400, "height": 1800})
            await page.goto(url)
            await asyncio.sleep(20)
            await page.screenshot(path=filename, full_page=True)
            await browser.close()
            return filename
    except: return None

def check_liquidity_lock(image_path):
    if not os.path.exists(image_path): return "❌ Detection Failed"
    img = cv2.imread(image_path)
    if img is None: return "❌ Detection Failed"
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([35, 40, 40]), np.array([95, 255, 255]))
    return "🔒 Locked" if cv2.countNonZero(mask) > 10 else "❌ No Lock Found"

async def main():
    if len(sys.argv) < 2: return
    mint = sys.argv[1]
    r1 = requests.get(f"{TOKEN_API}?query={mint}", headers=HEADERS)
    tinfo = r1.json()[0] if r1.status_code == 200 and r1.json() else {}
    r2 = requests.get(f"{DEX_API_BASE}/token-pairs/v1/{CHAIN}/{mint}")
    dinfo = r2.json()[0] if r2.status_code == 200 and r2.json() else {}
    chart_file = f"chart_{mint}.png"
    chart = await capture_chart(mint, chart_file)
    lock = check_liquidity_lock(chart_file) if chart else "❌ Screenshot Failed"
    print(f"💎 *TOKEN ANALYSIS: {tinfo.get('name', 'UNKNOWN')}*")
    print(f"🔤 Symbol: {tinfo.get('symbol', 'N/A')}")
    print(f"🆔 Mint: `{mint}`")
    print(f"💵 Price: ${format_number(tinfo.get('usdPrice'))}")
    print(f"📊 MCap: ${format_number(tinfo.get('mcap'))}")
    print(f"💧 Liquidity: ${format_number(tinfo.get('liquidity'))}")
    print(f"🔒 *Liquidity Lock:* {lock}")
    audit = tinfo.get('audit', {})
    print(f"🛡️ *Audit:* Mint Authority: {'✅ Disabled' if audit.get('mintAuthorityDisabled') else '❌ Enabled'} | Freeze Authority: {'✅ Disabled' if audit.get('freezeAuthorityDisabled') else '❌ Enabled'}")
    print(f"👥 Holders: {tinfo.get('holderCount', 'N/A')}")

if __name__ == "__main__": asyncio.run(main())
