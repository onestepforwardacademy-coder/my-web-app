# main.py
# Playwright (Stable Fix) + Token Rug Check

import sys
import time
import re
from playwright.sync_api import sync_playwright

# 1. Argument Validation
if len(sys.argv) < 2:
    print("ERROR: No token address provided")
    sys.exit(1)

token_address = sys.argv[1]
url = f"https://ave.ai/token/{token_address}-solana?from=Home"

def check_rug_pull():
    # Use the 'with' statement for the "Forever Fix" cleanup
    with sync_playwright() as p:
        # Launch optimized for VPS
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        
        # Set a realistic User Agent
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        try:
            print(f"\n🔎 Checking token: {token_address}")
            
            # Go to URL
            page.goto(url, wait_until="load", timeout=60000)
            
            print("⏳ Waiting for page load and data...")
            # We wait 12 seconds exactly as your original script did
            page.wait_for_timeout(12000)

            # Dismiss modal (Pressing Escape)
            page.keyboard.press("Escape")

            # Extract Rug Pull %
            # We use the same logic: Look for 'Rug Pull' text then find the next '%' text
            try:
                # XPath logic translated to Playwright
                rug_pull_locator = page.locator("//*[contains(text(),'Rug Pull')]/following::*[contains(text(),'%')][1]")
                
                # Wait for it to be visible (up to 25 seconds like your original)
                rug_pull_locator.wait_for(state="visible", timeout=25000)
                
                text = rug_pull_locator.inner_text().strip()
                match = re.search(r'([0-9]+(?:\.[0-9]+)?)%', text)

                if not match:
                    print("ERROR: Rug Pull Percentage not found in text")
                    return

                rug_percent = float(match.group(1))
                print(f"\nRug Pull Percentage: {rug_percent}%")

                if rug_percent <= 55:
                    print("DECISION: BUY")
                else:
                    print("DECISION: SKIP")

            except Exception as e:
                print(f"ERROR: Could not find Rug Pull element: {e}")

        except Exception as e:
            print(f"ERROR during navigation: {e}")
        finally:
            # This ensures the browser process is killed and RAM is freed
            browser.close()

if __name__ == "__main__":
    check_rug_pull()
