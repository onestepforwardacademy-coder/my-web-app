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
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True, 
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
        )
        
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        try:
            print(f"\n🔎 Checking token: {token_address}")
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            
            print("⏳ Waiting for page data...")
            page.wait_for_timeout(15000)

            # Dismiss any modal
            try:
                page.keyboard.press("Escape")
                page.wait_for_timeout(1000)
            except:
                pass

            # Try multiple selectors for Rug Pull percentage
            rug_percent = None
            
            # Method 1: Look for text containing "Rug Pull" and get nearby percentage
            try:
                page_content = page.content()
                
                # Find all percentages near "Rug Pull" text
                rug_match = re.search(r'Rug\s*Pull[^%]*?([0-9]+(?:\.[0-9]+)?)\s*%', page_content, re.IGNORECASE)
                if rug_match:
                    rug_percent = float(rug_match.group(1))
            except:
                pass
            
            # Method 2: Use XPath if Method 1 failed
            if rug_percent is None:
                try:
                    selectors = [
                        "//*[contains(text(),'Rug Pull')]/following::*[contains(text(),'%')]",
                        "//*[contains(text(),'Rug')]/following-sibling::*[contains(text(),'%')]",
                        "//div[contains(@class,'rug')]//span[contains(text(),'%')]",
                    ]
                    
                    for sel in selectors:
                        try:
                            elem = page.locator(sel).first
                            if elem.is_visible(timeout=3000):
                                text = elem.inner_text().strip()
                                match = re.search(r'([0-9]+(?:\.[0-9]+)?)%', text)
                                if match:
                                    rug_percent = float(match.group(1))
                                    break
                        except:
                            continue
                except:
                    pass
            
            # Method 3: Screenshot and parse all visible text
            if rug_percent is None:
                try:
                    all_text = page.inner_text("body")
                    rug_match = re.search(r'Rug\s*Pull[^%]*?([0-9]+(?:\.[0-9]+)?)\s*%', all_text, re.IGNORECASE)
                    if rug_match:
                        rug_percent = float(rug_match.group(1))
                except:
                    pass

            if rug_percent is not None:
                print(f"\nRug Pull Percentage: {rug_percent}%")
                
                if rug_percent <= 55:
                    print("DECISION: BUY")
                else:
                    print("DECISION: SKIP")
            else:
                print("ERROR: Rug Pull Percentage not found")
                print("DECISION: SKIP")

        except Exception as e:
            print(f"ERROR: {e}")
            print("DECISION: SKIP")
        finally:
            browser.close()

if __name__ == "__main__":
    check_token()
