from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import re
import time
import sys  # <-- added

# -----------------------------
# NEW: read token from command line
token = sys.argv[1]  # token address passed from Node.js
url = f"https://ave.ai/token/{token}-solana?from=Home"
# -----------------------------

# Paths to Replit's Chromium + Chromedriver
CHROME_PATH = "/nix/store/zi4f80l169xlmivz8vja8wlphq74qqk0-chromium-125.0.6422.141/bin/chromium"
CHROMEDRIVER_PATH = "/nix/store/3qnxr5x6gw3k9a9i7d0akz0m6bksbwff-chromedriver-125.0.6422.141/bin/chromedriver"

# Chrome options
options = Options()
options.binary_location = CHROME_PATH
options.add_argument("--headless=new")
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")
options.add_argument("--disable-gpu")
options.add_argument("--disable-infobars")
options.add_argument("--disable-blink-features=AutomationControlled")
options.add_argument("--window-size=1920,1080")

# Start driver
service = Service(CHROMEDRIVER_PATH)
driver = webdriver.Chrome(service=service, options=options)

# Target URL
driver.get(url)

print("Navigating to page and waiting for dynamic content...")
time.sleep(10)

# --- Try dismissing pop-up ---
BUTTON_LOCATOR = (By.XPATH, "//*[contains(text(), 'Start experiencing')]")

try:
    driver.find_element(By.TAG_NAME, 'body').send_keys(Keys.ESCAPE)
    time.sleep(2)
    WebDriverWait(driver, 2).until(EC.invisibility_of_element_located(BUTTON_LOCATOR))
    print("Pop-up dismissed.")
except:
    try:
        wait = WebDriverWait(driver, 5)
        start_button = wait.until(EC.element_to_be_clickable(BUTTON_LOCATOR))
        driver.execute_script("arguments[0].click();", start_button)
        time.sleep(2)
        print("Pop-up dismissed via fallback click.")
    except:
        print("Modal not present or could not be dismissed.")

# --- Extract Rug Pull Percentage ---
RUG_PULL_PERCENT_XPATH = "//*[contains(text(), 'Rug Pull')]/following::*[contains(text(), '%')][1]"
rug_pull_percentage = "N/A"

try:
    print("\nExtracting Rug Pull percentage...")
    wait_percent = WebDriverWait(driver, 20)
    percent_element = wait_percent.until(EC.visibility_of_element_located((By.XPATH, RUG_PULL_PERCENT_XPATH)))

    full_text = percent_element.text.strip()
    match = re.search(r'[\+\-]?\d+(\.\d+)?%', full_text)

    if match:
        rug_pull_percentage = match.group(0)
    else:
        rug_pull_percentage = full_text

    print(f"✅ Rug Pull Percentage: {rug_pull_percentage}")

    # --- Add recommendation based on percentage ---
    percent_value = float(rug_pull_percentage.replace("%", ""))
    if 0 <= percent_value <= 55:
        print("🟢 Safe to buy")
    elif 56 <= percent_value <= 100:
        print("🔴 Scam token, don't buy")
    else:
        print("⚠️ Unexpected rug pull value")

except TimeoutException:
    print("❌ Timed out waiting for Rug Pull percentage.")
except NoSuchElementException:
    print("❌ Could not locate Rug Pull element.")
except Exception as e:
    print(f"Unexpected error: {e}")

driver.quit()
