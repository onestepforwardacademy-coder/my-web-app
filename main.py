# main.py
# Selenium Rug Pull checker for ave.ai
# Output format is STRICTLY designed for bot.py parsing

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
from selenium.common.exceptions import TimeoutException, NoSuchElementException

# -------------------------------------------------
# Validate argument
# -------------------------------------------------
if len(sys.argv) < 2:
    print("ERROR: No token address provided")
    sys.exit(1)

token_address = sys.argv[1]
url = f"https://ave.ai/token/{token_address}-solana?from=Home"

# -------------------------------------------------
# Chromium paths (DIRECT VPS PATHS)
# -------------------------------------------------
# We use 'google-chrome-stable' which is the actual filename on Ubuntu
CHROME_PATH = "/usr/bin/google-chrome-stable"
CHROMEDRIVER_PATH = "/usr/bin/chromedriver"

# -------------------------------------------------
# Chrome options
# -------------------------------------------------
options = Options()
options.binary_location = CHROME_PATH
options.add_argument("--headless=new")
options.add_argument("--no-sandbox")            # Fixes permission issues on VPS
options.add_argument("--disable-dev-shm-usage")  # Fixes memory/session issues
options.add_argument("--disable-gpu")
options.add_argument("--disable-blink-features=AutomationControlled")
options.add_argument("--window-size=1920,1080")
options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# -------------------------------------------------
# Start driver
# -------------------------------------------------
service = Service(CHROMEDRIVER_PATH)
driver = webdriver.Chrome(service=service, options=options)

try:
    print(f"\n🔎 Checking token: {token_address}")
    print(f"🌐 URL: {url}")

    driver.get(url)
    print("⏳ Waiting for page load...")
    time.sleep(12)

    # -------------------------------------------------
    # Dismiss modal if present
    # -------------------------------------------------
    try:
        driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
        print("🪟 Modal dismissed (ESC)")
    except:
        pass

    # -------------------------------------------------
    # Extract Rug Pull %
    # -------------------------------------------------
    print("\n📊 Extracting Rug Pull percentage...")

    RUG_XPATH = "//*[contains(text(),'Rug Pull')]/following::*[contains(text(),'%')][1]"

    percent_element = WebDriverWait(driver, 25).until(
        EC.visibility_of_element_located((By.XPATH, RUG_XPATH))
    )

    text = percent_element.text.strip()
    print(f"🔍 Raw text: {text}")

    match = re.search(r'([0-9]+(?:\.[0-9]+)?)%', text)

    if not match:
        print("ERROR: Rug Pull Percentage not found")
        sys.exit(0)

    rug_percent = float(match.group(1))

    # -------------------------------------------------
    # FINAL OUTPUT
    # -------------------------------------------------
    print(f"\nRug Pull Percentage: {rug_percent}%")

    if 0 <= rug_percent <= 55:
        print("DECISION: BUY")
    else:
        print("DECISION: SKIP")

except TimeoutException:
    print("ERROR: Timeout while extracting Rug Pull")
except Exception as e:
    print(f"ERROR: {e}")
finally:
    driver.quit()
