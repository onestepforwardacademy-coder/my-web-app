# main.py
import sys
import time
import re
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

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
options.add_argument("--headless=new")
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")
options.add_argument("--disable-gpu")
options.add_argument("--window-size=1920,1080")
# Crucial: Spoof a real browser to avoid "Bot Detected" screens
options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
options.add_experimental_option("excludeSwitches", ["enable-automation"])
options.add_experimental_option('useAutomationExtension', False)

# -------------------------------------------------
# 3. Start Driver (Dynamic Pathing)
# -------------------------------------------------
# Selenium 4.x automatically finds the driver; no path needed
driver = webdriver.Chrome(options=options)

try:
    print(f"\n🔎 Checking token: {token_address}")
    driver.get(url)
    
    # Ave.ai needs time to render Javascript
    print("⏳ Waiting for page to stabilize...")
    time.sleep(12)

    # -------------------------------------------------
    # 4. Dismiss Popups (The Logic Fix)
    # -------------------------------------------------
    try:
        # Use a broad ESCAPE key hit to clear any overlays
        driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
        time.sleep(1)
    except:
        pass

    # -------------------------------------------------
    # 5. Extract Rug Pull % (Advanced XPATH)
    # -------------------------------------------------
    # We look for the text "Rug Pull" and find the very next element containing '%'
    RUG_XPATH = "//*[contains(text(),'Rug Pull')]/following::*[contains(text(),'%')][1]"
    
    print("📊 Searching for Rug Pull element...")
    wait = WebDriverWait(driver, 20)
    percent_element = wait.until(EC.presence_of_element_located((By.XPATH, RUG_XPATH)))
    
    raw_text = percent_element.text.strip()
    print(f"🔍 Raw text found: {raw_text}")

    # Regex to extract just the number
    match = re.search(r'([0-9]+(?:\.[0-9]+)?)%', raw_text)

    if not match:
        # Fallback: Sometimes it's inside a different child element
        print("⚠️ Direct match failed, trying broader search...")
        raw_text = driver.find_element(By.XPATH, "//*[contains(text(),'Rug Pull')]/..").text
        match = re.search(r'([0-9]+(?:\.[0-9]+)?)%', raw_text)

    if match:
        rug_percent = float(match.group(1))
        print(f"\nRug Pull Percentage: {rug_percent}%")
        
        # -------------------------------------------------
        # 6. FINAL OUTPUT (STRICT FORMAT)
        # -------------------------------------------------
        if 0 <= rug_percent <= 55:
            print("DECISION: BUY")
        else:
            print("DECISION: SKIP")
    else:
        print("ERROR: Rug Pull Percentage not found in text")

except Exception as e:
    print(f"❌ ERROR: {str(e)}")
finally:
    driver.quit()
