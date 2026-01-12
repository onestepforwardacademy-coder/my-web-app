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

def check_token():
    # 'with' statement ensures the browser closes even if the script fails
    with sync_playwright() as p:
        # Optimized launch for VPS (No GPU, No Sandbox)
        browser = p.chromium.launch(
            headless=True, 
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        
        # Create context with a real-looking browser identity
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        try:
            print(f"\n🔎 Checking token: {token_address}")
            page.goto(url, wait_until="load", timeout=60000)
            
            print("⏳ Waiting for page load and data...")
            # Match your original 12s sleep
            page.wait_for_timeout(12000)

            # Dismiss modal by pressing Escape
            page.keyboard.press("Escape")

            # Extract Rug Pull %
            # .first handles the "strict mode violation" if multiple % elements exist
            RUG_XPATH = "//*[contains(text(),'Rug Pull')]/following::*[contains(text(),'%')][1]"
            rug_locator = page.locator(RUG_XPATH).first

            # Wait up to 25s for the element to be visible
            rug_locator.wait_for(state="visible", timeout=25000)

            text = rug_locator.inner_text().strip()
            match = re.search(r'([0-9]+(?:\.[0-9]+)?)%', text)

            if not match:
                print("ERROR: Rug Pull Percentage not found in element text")
                return

            rug_percent = float(match.group(1))
            print(f"\nRug Pull Percentage: {rug_percent}%")

            if rug_percent <= 55:
                print("DECISION: BUY")
            else:
                print("DECISION: SKIP")

        except Exception as e:
            print(f"ERROR: {e}")
        finally:
            # Clean up processes to save VPS RAM
            browser.close()

if __name__ == "__main__":
    check_token()
