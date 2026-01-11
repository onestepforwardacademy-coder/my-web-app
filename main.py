# main.py
# Selenium Rug Pull checker for ave.ai
# Optimized for VPS environment (Ubuntu)

import sys
import time
import re
import os
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

# -------------------------------------------------
# 1. Setup & Arguments
# -------------------------------------------------
if len(sys.argv) < 2:
    print("ERROR: No token address provided")
    sys.exit(1)

token_address = sys.argv[1]
url = f"https://ave.ai/token/{token_address}-solana?from=Home"

# -------------------------------------------------
# 2. Chrome Options (VPS Optimized)
# -------------------------------------------------
options = Options()

# FORCE THE BINARY PATH (Fixes SessionNotCreated error)
options.binary_location = "/usr/bin/google-chrome"

options.add_argument("--headless=new")
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")
options.add_argument("--disable-gpu")
options.add_argument("--window-size=1920,1080")

# Bypass bot detection
options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
options.add_experimental_option("excludeSwitches", ["enable-automation"])
options.add_experimental_option('useAutomationExtension', False)

# -------------------------------------------------
# 3. Start Driver
# -------------------------------------------------
try:
    driver = webdriver.Chrome(options=options)
except Exception as e:
    print(f"❌ CRITICAL ERROR: Could not start Chrome. {e}")
    sys.exit(1)

try:
    print(f"\n🔎 Checking token: {token_address}")
    driver.get(url)
    
    # Ave.ai is heavy on Javascript; needs a long wait
    print("⏳ Waiting 12s for page to stabilize...")
    time.sleep(12)

    # -------------------------------------------------
    # 4. Dismiss Popups/Modals
    # -------------------------------------------------
    try:
        driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
        time.sleep(1)
    except:
        pass

    # -------------------------------------------------
    # 5. Extract Rug Pull %
    # -------------------------------------------------
    # Search for "Rug Pull" text and find the next percentage value
    RUG_XPATH = "//*[contains(text(),'Rug Pull')]/following::*[contains(text(),'%')][1]"
    
    print("📊 Searching for Rug Pull data...")
    wait = WebDriverWait(driver, 20)
    percent_element = wait.until(EC.presence_of_element_located((By.XPATH, RUG_XPATH)))
    
    raw_text = percent_element.text.strip()
    print(f"🔍 Raw text found: {raw_text}")

    # Extract number (e.g., "15.5%" -> 15.5)
    match = re.search(r'([0-9]+(?:\.[0-9]+)?)%', raw_text)

    if match:
        rug_percent = float(match.group(1))
        print(f"\nRug Pull Percentage: {rug_percent}%")
        
        # -------------------------------------------------
        # 6. FINAL OUTPUT (STRICT FORMAT FOR BOT.PY)
        # -------------------------------------------------
        if 0 <= rug_percent <= 55:
            print("DECISION: BUY")
        else:
            print("DECISION: SKIP")
    else:
        print("ERROR: Rug Pull Percentage not found in text.")

except TimeoutException:
    print("❌ ERROR: Timeout. Page took too long or element missing.")
except Exception as e:
    print(f"❌ ERROR: {str(e)}")
finally:
    driver.quit()
