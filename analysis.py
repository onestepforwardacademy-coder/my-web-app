import sys
import requests
from datetime import datetime, timezone
import cv2
import numpy as np
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import time

# ===================== JUPITER & DEXSCREENER INFO =====================
TOKEN_API = "https://lite-api.jup.ag/tokens/v2/search"
HEADERS = {"User-Agent": "Mozilla/5.0"}
CHAIN = "solana"
DEX_API_BASE = "https://api.dexscreener.com"

# === Helper functions (same as before) ===
def format_number(n):
    if n in ["N/A", None]:
        return "N/A"
    try:
        n = float(n)
        if n >= 1_000_000_000:
            return f"{n/1_000_000_000:.2f}B"
        elif n >= 1_000_000:
            return f"{n/1_000_000:.2f}M"
        elif n >= 1_000:
            return f"{n/1_000:.2f}K"
        elif n < 0.01:
            return f"{n:.6f}"
        else:
            return f"{n:.4f}"
    except:
        return str(n)

def timestamp_to_date(ts):
    try:
        return datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    except:
        return "N/A"

def token_age(created_ts):
    try:
        created_dt = datetime.fromtimestamp(created_ts / 1000, tz=timezone.utc)
        now = datetime.now(timezone.utc)
        delta = now - created_dt
        minutes = int(delta.total_seconds() / 60)
        hours = int(delta.total_seconds() / 3600)
        days = delta.days
        months = days // 30
        years = days // 365
        if minutes < 60:
            return f"{minutes} minutes"
        elif hours < 24:
            return f"{hours} hours"
        elif days < 30:
            return f"{days} days"
        elif months < 12:
            return f"{months} months"
        else:
            return f"{years} years"
    except:
        return "N/A"

def fetch_jupiter_token_info(mint_address):
    resp = requests.get(f"{TOKEN_API}?query={mint_address}", headers=HEADERS)
    if resp.status_code != 200:
        return None
    data = resp.json()
    return data[0] if data else None

def fetch_dex_info(token_address):
    url = f"{DEX_API_BASE}/token-pairs/v1/{CHAIN}/{token_address}"
    resp = requests.get(url)
    if resp.status_code != 200 or not resp.json():
        return None
    pair = resp.json()[0]
    extra_info = {}
    created_ts = pair.get("pairCreatedAt")
    extra_info['pair_address'] = pair.get("pairAddress")
    extra_info['pair_created_at'] = timestamp_to_date(created_ts)
    extra_info['token_age'] = token_age(created_ts)
    extra_info['quote_token_logo'] = pair.get("quoteToken", {}).get("logo")
    extra_info['transactions'] = pair.get("txns", {})
    extra_info['price_change'] = pair.get("priceChange", {})
    extra_info['volume'] = pair.get("volume", {})

    txns = pair.get("txns", {})
    buys_total = sum(txns.get(i, {}).get('buys', 0) for i in ["h24","h6","h1"])
    sells_total = sum(txns.get(i, {}).get('sells', 0) for i in ["h24","h6","h1"])
    extra_info['honeypot'] = False if buys_total and sells_total else True
    extra_info['swap_ok'] = True if buys_total and sells_total else False

    liquidity_usd = pair.get('liquidity', {}).get('usd') or 0
    market_cap = pair.get('marketCap') or 0
    extra_info['liq_vs_marketcap_percent'] = (liquidity_usd / market_cap * 100) if market_cap else 0

    return extra_info

# ===================== SELENIUM CHART CAPTURE =====================
def capture_chart(token_mint, filename="chart.png"):
    url = f"https://dexscreener.com/solana/{token_mint}?embed=1&theme=dark"
    try:
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--window-size=1400,1800")

        driver = webdriver.Chrome(options=chrome_options)
        driver.get(url)
        time.sleep(20)
        driver.save_screenshot(filename)
        driver.quit()
        return filename
    except Exception as e:
        print(f"Selenium error: {e}")
        return None

# ===================== LIQUIDITY LOCK DETECTION =====================
def check_liquidity_lock(image_path):
    img = cv2.imread(image_path)
    if img is None:
        return "❌ Lock detection failed: image not found"

    h, w, _ = img.shape
    lock_coord = (1148, 326)
    search_radius = 15

    x1 = max(lock_coord[0] - search_radius, 0)
    y1 = max(lock_coord[1] - search_radius, 0)
    x2 = min(lock_coord[0] + search_radius, w)
    y2 = min(lock_coord[1] + search_radius, h)

    lock_area = img[y1:y2, x1:x2]
    hsv = cv2.cvtColor(lock_area, cv2.COLOR_BGR2HSV)

    lower_green = np.array([35, 40, 40])
    upper_green = np.array([95, 255, 255])
    mask = cv2.inRange(hsv, lower_green, upper_green)
    green_pixels = cv2.countNonZero(mask)

    return "🔒 Locked" if green_pixels > 5 else "❌ No Lock Found"

# ===================== SAFETY SCORE FUNCTION =====================
def calculate_safety_score(token_info, dex_info, lock_status):
    score = 100
    warnings = []

    if lock_status != "🔒 Locked":
        score -= 50
        warnings.append("Liquidity is not locked! High risk.")

    if dex_info.get('honeypot'):
        score = 0
        warnings.append("❌ Avoid! This token is likely a honeypot and not tradable.")

    audit = token_info.get('audit', {}) if token_info else {}
    if not audit.get('mintAuthorityDisabled', False):
        score -= 10
        warnings.append("Mint authority not disabled! Risk of minting more tokens.")

    if not audit.get('freezeAuthorityDisabled', False):
        score -= 5
        warnings.append("Freeze authority not disabled! Tokens could be frozen.")

    top_holders_percent = audit.get('topHoldersPercentage', 0)
    if top_holders_percent > 30:
        score -= 5
        warnings.append(f"⚠️ Top holders own {top_holders_percent:.2f}% of this token.")

    snipers_percent = audit.get('snipersHoldingPercentage', 0)
    if snipers_percent > 30:
        score -= 10
        warnings.append(f"⚠️ Bots or large holders own {snipers_percent:.2f}% of this token.")

    dex_txns = dex_info.get('transactions', {})
    buys = sum(dex_txns.get(i, {}).get('buys', 0) for i in ["h24","h6","h1"])
    sells = sum(dex_txns.get(i, {}).get('sells', 0) for i in ["h24","h6","h1"])
    total_tx = buys + sells
    if total_tx < 10:
        score -= 10
        warnings.append("Very low trading activity! Risk of illiquidity.")

    score = max(0, min(100, score))
    return round(score, 2), warnings

# ===================== MAIN FUNCTION ===============================
def main():
    import sys
    sys.stdout.reconfigure(line_buffering=True)  # ensure live output

    # Accept token from command-line
    if len(sys.argv) > 1:
        token_mint = sys.argv[1].strip()
    else:
        token_mint = input("Enter Solana token mint address: ").strip()

    screenshot_path = capture_chart(token_mint)
    token_info = fetch_jupiter_token_info(token_mint)
    dex_info = fetch_dex_info(token_mint)

    lock_status = check_liquidity_lock(screenshot_path) if screenshot_path else "❌ Screenshot failed"

    output_lines = []

    # ==== TOKEN INFO ====
    if token_info:
        output_lines.append(f"💎 Token Name: {token_info.get('name')}")
        output_lines.append(f"🔤 Symbol: {token_info.get('symbol')}")
        output_lines.append(f"🆔 Mint Address: {token_mint}")
        output_lines.append(f"🔢 Decimals: {token_info.get('decimals')}")
        output_lines.append(f"🖼 Icon: {token_info.get('icon')}")
        output_lines.append(f"🐦 Twitter/X: {token_info.get('twitter')}")
        output_lines.append(f"👨‍💻 Developer: {token_info.get('dev')}")
        output_lines.append(f"🚀 Launchpad: {token_info.get('launchpad')}")
        output_lines.append(f"💰 Circulating Supply: {format_number(token_info.get('circSupply'))}")
        output_lines.append(f"📦 Total Supply: {format_number(token_info.get('totalSupply'))}")
        output_lines.append(f"💎 FDV: {format_number(token_info.get('fdv'))}")
        output_lines.append(f"📊 Market Cap: {format_number(token_info.get('mcap'))}")
        output_lines.append(f"🌱 Organic Score: {token_info.get('organicScore')} ({token_info.get('organicScoreLabel')})")
        audit = token_info.get('audit', {})
        output_lines.append(f"🛡 MintAuthorityDisabled: {audit.get('mintAuthorityDisabled')}")
        output_lines.append(f"🛡 FreezeAuthorityDisabled: {audit.get('freezeAuthorityDisabled')}")
        output_lines.append(f"🛡 TopHoldersPercentage: {audit.get('topHoldersPercentage')}")
        output_lines.append(f"🛡 SnipersHoldingPercentage: {audit.get('snipersHoldingPercentage')}")

    # ==== DEX INFO ====
    if dex_info:
        output_lines.append(f"\n💎 --- DEX Info --- 💎")
        output_lines.append(f"🆔 Pair Address: {dex_info['pair_address']}")
        output_lines.append(f"⏳ Pair Created At: {dex_info['pair_created_at']}")
        output_lines.append(f"🕒 Token Age: {dex_info['token_age']}")
        for interval in ["h24","h6","h1"]:
            change = dex_info['price_change'].get(interval)
            emoji = "🟢" if change and float(change) > 0 else "🔴" if change and float(change) < 0 else "⚪"
            output_lines.append(f"{interval} Price Change: {emoji} {format_number(change)}%")
            buys = dex_info['transactions'].get(interval, {}).get('buys',0)
            sells = dex_info['transactions'].get(interval, {}).get('sells',0)
            output_lines.append(f"{interval} → 🟢 Buys: {buys} | 🔴 Sells: {sells}")
        output_lines.append(f"Honeypot: {'⚠️ Possible honeypot' if dex_info['honeypot'] else '✅ Not honeypot'}")
        output_lines.append(f"Swap: {'⚠️ Issue' if not dex_info['swap_ok'] else '✅ OK'}")
        output_lines.append(f"Liquidity vs Market Cap: {dex_info['liq_vs_marketcap_percent']:.2f}%")

    # ==== LIQUIDITY LOCK ====
    output_lines.append(f"\n🛡 Liquidity Lock Status: {lock_status}")

    # ==== SAFETY SCORE ====
    safety_score, safety_warnings = calculate_safety_score(token_info, dex_info, lock_status)
    if safety_score >= 70:
        score_display = f"🟢 {safety_score}/100 (Good)"
    elif safety_score >= 40:
        score_display = f"🟡 {safety_score}/100 (Medium)"
    else:
        score_display = f"🔴 {safety_score}/100 (Bad)"
    output_lines.append(f"\n🛡 Safety Score: {score_display}")

    if safety_warnings:
        output_lines.append("⚠️ Warnings:")
        for w in safety_warnings:
            output_lines.append(f"- {w}")

    print("\n".join(output_lines))

# ===================== RUN SCRIPT ==================================
if __name__ == "__main__":
    main()
