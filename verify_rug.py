#!/usr/bin/env python3
import sys
import re
from playwright.sync_api import sync_playwright

if len(sys.argv) < 2:
    print("ERROR: No token address provided")
    sys.exit(1)

token_address = sys.argv[1]
url = f"https://ave.ai/token/{token_address}-solana?from=Home"

def verify_dev_rug():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
        )
        
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        page = context.new_page()

        try:
            print(f"Checking: {token_address}")
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(15000)

            try:
                page.keyboard.press("Escape")
                page.wait_for_timeout(1000)
            except:
                pass

            rug_percent = None
            dev_info = {}
            
            page_content = page.content()
            all_text = page.inner_text("body")
            
            # Extract Rug Pull percentage
            rug_match = re.search(r'Rug\s*Pull[^%]*?([0-9]+(?:\.[0-9]+)?)\s*%', page_content, re.IGNORECASE)
            if rug_match:
                rug_percent = float(rug_match.group(1))
            
            if rug_percent is None:
                rug_match = re.search(r'Rug\s*Pull[^%]*?([0-9]+(?:\.[0-9]+)?)\s*%', all_text, re.IGNORECASE)
                if rug_match:
                    rug_percent = float(rug_match.group(1))

            # Extract other dev metrics
            dev_match = re.search(r'Dev\s*(?:Creator)?[^%]*?([0-9]+(?:\.[0-9]+)?)\s*%', all_text, re.IGNORECASE)
            if dev_match:
                dev_info['dev_holding'] = dev_match.group(1) + "%"
            
            top10_match = re.search(r'Top\s*10[^%]*?([0-9]+(?:\.[0-9]+)?)\s*%', all_text, re.IGNORECASE)
            if top10_match:
                dev_info['top10_holding'] = top10_match.group(1) + "%"
            
            # Build output
            print("\n" + "="*40)
            print("DEV RUG HISTORY VERIFICATION")
            print("="*40)
            print(f"Token: {token_address[:20]}...")
            print(f"Source: ave.ai")
            print("-"*40)
            
            if rug_percent is not None:
                status = "HIGH RISK" if rug_percent > 55 else "MEDIUM" if rug_percent > 30 else "LOW RISK"
                emoji = "" if rug_percent > 55 else "" if rug_percent > 30 else ""
                print(f"Rug Pull Risk: {rug_percent}% {emoji} {status}")
            else:
                print("Rug Pull Risk: Unable to fetch")
            
            if dev_info.get('dev_holding'):
                print(f"Dev Holding: {dev_info['dev_holding']}")
            if dev_info.get('top10_holding'):
                print(f"Top 10 Holders: {dev_info['top10_holding']}")
            
            print("-"*40)
            if rug_percent is not None and rug_percent > 55:
                print("VERDICT: AVOID - High rug risk")
            elif rug_percent is not None and rug_percent <= 55:
                print("VERDICT: ACCEPTABLE - Moderate risk")
            else:
                print("VERDICT: UNKNOWN - Manual check needed")
            print("="*40)

        except Exception as e:
            print(f"ERROR: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    verify_dev_rug()
