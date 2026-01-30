import os
import sys
import time
import json
import base58
import base64
import requests
import subprocess
import re
from datetime import datetime, timezone
from typing import Dict
import scanner

if len(sys.argv) < 4:
    print("âŒ Usage: python3 bot.py <BASE58_PRIVATE_KEY> <TP_MULTIPLIER> <BUY_AMOUNT_SOL>")
    sys.exit(1)

PRIVATE_KEY_BASE58 = sys.argv[1]
TAKE_PROFIT_MULTIPLIER = float(sys.argv[2])
BUY_AMOUNT_SOL = float(sys.argv[3])
RPC = os.getenv("RPC_URL", "https://api.mainnet-beta.solana.com")
SCAN_INTERVAL = 30
MONITOR_INTERVAL = 5
HEADERS = {"User-Agent": "Mozilla/5.0"}
tracked_tokens: Dict[str, Dict] = {}

def get_token_price(token_address):
    try:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
        resp = requests.get(url, timeout=10)
        data = resp.json()
        pair = data.get("pairs", [{}])[0]
        return {
            "price": float(pair.get("priceUsd", 0)),
            "h24": float(pair.get("priceChange", {}).get("h24", 0))
        }
    except Exception:
        return None

def sell_for_all_users(token_mint, reason="AUTO SELL"):
    print(f"ðŸš€ SELLING {token_mint} FOR ALL USERS - Reason: {reason}")
    
    try:
        with open("active_users.json", "r") as f:
            active_users = json.load(f)
    except:
        active_users = []

    for user in active_users:
        user_id = user.get("chatId")
        secret = user.get("secret")
        print(f"[*] Executing sell for User {user_id}...")
        try:
            # 1. Execute Sell
            subprocess.run(["python3", "execute_sell.py", secret, token_mint], capture_output=True, text=True)
            print(f"âœ… Sell logic triggered for User {user_id}")
            
            # 2. Execute Reclaim (background to not block selling for others)
            subprocess.Popen(["python3", "reclaim.py", secret, token_mint])
            print(f"ðŸ§¹ Reclaim process started for User {user_id}")
        except Exception as e:
            print(f"[-] Sell/Reclaim failed for User {user_id}: {e}")
            
    return True

def buy_for_all_users(token_mint):
    print(f"ðŸ”Ž Analysing token: {token_mint} using main.py")
    try:
        analysis_proc = subprocess.run(["python3", "main.py", token_mint], capture_output=True, text=True, timeout=90)
        analysis_output = analysis_proc.stdout
        print(analysis_output)
        
        if "DECISION: BUY" not in analysis_output:
            print(f"â­ï¸ SKIP: {token_mint} (Analysis did not confirm BUY)")
            return False
            
        print(f"âœ… CONFIRMED: {token_mint} passed rug check.")
    except Exception as e:
        print(f"âŒ Analysis error for {token_mint}: {e}")
        return False

    try:
        with open("active_users.json", "r") as f:
            active_users = json.load(f)
    except:
        active_users = []

    if not active_users:
        print("[-] No active users to buy for.")
        return False

    price_data = get_token_price(token_mint)
    if not price_data:
        return False
        
    entry_price = price_data["price"]
    
    print(f"ðŸš€ OPPORTUNITY FOUND: {token_mint} | Buying for {len(active_users)} users sequentially...")

    for user in active_users:
        user_id = user.get("chatId")
        secret = user.get("secret")
        amount = user.get("buyAmount", 0.001)
        target_mult = user.get("target", 2.0)
        
        print(f"[*] Buying {amount} SOL for User {user_id}...")
        try:
            subprocess.run(["python3", "execute_buy.py", secret, token_mint, str(amount)], capture_output=True, text=True)
            
            target_price = entry_price * target_mult
            # Track using mint as key since we want to sell for everyone when mint hits target
            if token_mint not in tracked_tokens:
                tracked_tokens[token_mint] = {
                    "mint": token_mint,
                    "target_price": target_price,
                    "buy_time": time.time()
                }
            print(f"OPPORTUNITY BOUGHT {token_mint}")
        except Exception as e:
            print(f"[-] Buy failed for User {user_id}: {e}")

    return True

def emergency_exit_check(data, mint):
    price_change_24h = data.get("h24", 0)
    if price_change_24h <= -2:
        print(f"EMERGENCY EXIT TRIGGERED: {mint} (24h drop: {price_change_24h}%)")
        return sell_for_all_users(mint, reason="ðŸš¨ EMERGENCY EXIT")
    return False

def run_emergency_system():
    print("\nðŸš€ BOT STARTED WITH MULTI-USER SYNCED TRADING LOGIC")
    while True:
        # Monitor existing trades
        for mint in list(tracked_tokens.keys()):
            token_info = tracked_tokens[mint]
            data = get_token_price(mint)
            if data:
                if emergency_exit_check(data, mint):
                    del tracked_tokens[mint]
                    continue
                current_price = data.get("price", 0)
                if current_price >= token_info["target_price"]:
                    if sell_for_all_users(mint, reason="ðŸŽ¯ TARGET HIT"):
                        del tracked_tokens[mint]

        # Scan for new opportunities
        if scanner.new_pairs_to_buy:
            for token in list(scanner.new_pairs_to_buy):
                buy_for_all_users(token)
                time.sleep(2)
        
        try:
            scanner.run_scan_and_search()
        except:
            pass
        
        time.sleep(MONITOR_INTERVAL)

if __name__ == "__main__":
    run_emergency_system()
