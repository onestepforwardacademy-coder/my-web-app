# main.py
import sys
import time
import re
import os
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

if len(sys.argv) < 2:
    print("ERROR: No token address provided")
    sys.exit(1)

token_address = sys.argv[1]
url = f"https://ave.ai/token/{token_address}-solana?from=Home"

options = Options()
options.add_argument("--headless=new")
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage") # FIX FOR DevToolsActivePort
options.add_argument("--disable-gpu")
options.add_argument("--remote-debugging-port=9222") # FIX FOR DevToolsActivePort
options.add_argument("--disable-extensions")
options.add_argument("--disable-infobars")
options.add_argument("--window-size=1920,1080")
options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

try:
    # Auto-manages the driver and browser startup
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)

    print(f"\n🔎 Checking token: {token_address}")
    driver.get(url)
    
    print("⏳ Waiting for page load...")
    time.sleep(12)

    # Extract Rug Pull %
    RUG_XPATH = "//*[contains(text(),'Rug Pull')]/following::*[contains(text(),'%')][1]"
    percent_element = WebDriverWait(driver, 25).until(
        EC.visibility_of_element_located((By.XPATH, RUG_XPATH))
    )

    text = percent_element.text.strip()
    match = re.search(r'([0-9]+(?:\.[0-9]+)?)%', text)

    if not match:
        print("ERROR: Rug Pull Percentage not found")
        sys.exit(0)

    rug_percent = float(match.group(1))
    print(f"\nRug Pull Percentage: {rug_percent}%")

    if rug_percent <= 55:
        print("DECISION: BUY")
    else:
        print("DECISION: SKIP")

except Exception as e:
    print(f"ERROR: {e}")
finally:
    if 'driver' in locals():
        driver.quit()
