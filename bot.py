# bot.py
# Orchestrator: buy/sell logic, tracking, and main continuous loop.
# Uses scanner.py to scan tokens and main.py for Rug Pull check via subprocess

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
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction
from typing import Dict

# --- NEW IMPORTS FOR ATA CLOSURE & BURN ---
from solders.pubkey import Pubkey
from solders.message import MessageV0
from solders.hash import Hash
from spl.token.instructions import (
    close_account, CloseAccountParams, 
    get_associated_token_address,
    burn, BurnParams # Added Burn to handle dust
)
from spl.token.constants import TOKEN_PROGRAM_ID
# ----------------------------------
import scanner  # local import

# -------------------------------------------------
# Command-line arguments
# -------------------------------------------------
if len(sys.argv) < 4:
    print("❌ Usage: python3 bot.py <BASE58_PRIVATE_KEY> <TP_MULTIPLIER> <BUY_AMOUNT_SOL>")
    sys.exit(1)

PRIVATE_KEY_BASE58 = sys.argv[1]
TAKE_PROFIT_MULTIPLIER = float(sys.argv[2])
BUY_AMOUNT_SOL = float(sys.argv[3])

RPC = os.getenv("RPC_URL", "https://api.mainnet-beta.solana.com")

SCAN_INTERVAL = 30
MONITOR_INTERVAL = 5

# --- JUPITER API CONSTANTS ---
JUP_TOKEN_API = "https://lite-api.jup.ag/tokens/v2/search"
JUP_QUOTE_API = "https://lite-api.jup.ag/swap/v1/quote"
JUP_SWAP_API = "https://lite-api.jup.ag/swap/v1/swap"
HEADERS = {"User-Agent": "Mozilla/5.0"}

tracked_tokens: Dict[str, Dict] = {}

# -------------------------------------------------
# Helpers
# -------------------------------------------------
def fetch_jupiter_token_info(mint_address):
    """Integrated Jupiter API stats fetcher"""
    try:
        resp = requests.get(f"{JUP_TOKEN_API}?query={mint_address}", headers=HEADERS, timeout=10)
        if resp.status_code != 200:
            return None
        data = resp.json()
        return data[0] if data else None
    except Exception:
        return None

def close_ata_reclaim_rent(token_mint: str):
    """Closes ATA to get back the ~0.002 SOL rent fee. Burns any 'dust' first."""
    pass

def get_token_price(token_address: str):
    try:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
        data = requests.get(url, timeout=10).json()
        return float(data["pairs"][0]["priceUsd"])
    except Exception:
        return None

def get_actual_token_balance_info(public_key_str: str, token_mint: str):
    """Fetches exact balance and decimal info."""
    payload = {
        "jsonrpc": "2.0", "id": 1, "method": "getTokenAccountsByOwner",
        "params": [
            public_key_str,
            {"mint": token_mint},
            {"encoding": "jsonParsed"}
        ]
    }
    try:
        res = requests.post(RPC, json=payload, timeout=10).json()
        accounts = res.get("result", {}).get("value", [])
        if not accounts:
            return {"amount": 0, "decimals": 0, "ata": None, "program_id": TOKEN_PROGRAM_ID}

        acc_data = accounts[0]
        token_info = acc_data["account"]["data"]["parsed"]["info"]["tokenAmount"]
        return {
            "amount": int(token_info["amount"]), 
            "decimals": token_info["decimals"],
            "ui_amount": token_info["uiAmount"],
            "ata": Pubkey.from_string(acc_data["pubkey"]),
            "program_id": Pubkey.from_string(acc_data["account"]["owner"])
        }
    except Exception:
        return {"amount": 0, "decimals": 0, "ata": None, "program_id": TOKEN_PROGRAM_ID}

def get_actual_token_balance(public_key_str: str, token_mint: str):
    """Original helper kept for backward compatibility in sell_swap."""
    info = get_actual_token_balance_info(public_key_str, token_mint)
    return int(info["amount"])

# -------------------------------------------------
# Jupiter BUY
# -------------------------------------------------
def buy_swap(token_mint: str) -> bool:
    print(f"\n🟢 BUYING {token_mint}")

    keypair = Keypair.from_bytes(base58.b58decode(PRIVATE_KEY_BASE58))
    public_key = str(keypair.pubkey())

    AMOUNT = int(BUY_AMOUNT_SOL * 1_000_000_000)

    quote_url = (
        f"{JUP_QUOTE_API}"
        f"?inputMint=So11111111111111111111111111111111111111112"
        f"&outputMint={token_mint}"
        f"&amount={AMOUNT}"
        f"&slippageBps=500" 
    )

    try:
        quote = requests.get(quote_url, timeout=10).json()
        if "error" in quote:
            print("❌ Jupiter quote failed")
            return False

        swap_tx = requests.post(
            JUP_SWAP_API,
            json={
                "quoteResponse": quote,
                "userPublicKey": public_key,
                "wrapAndUnwrapSol": True
            },
            timeout=20
        ).json()

        if "swapTransaction" not in swap_tx:
            print("❌ Swap TX missing")
            return False

        tx = VersionedTransaction.from_bytes(base64.b64decode(swap_tx["swapTransaction"]))
        signed = VersionedTransaction(tx.message, [keypair])
        signed_bs58 = base58.b58encode(bytes(signed)).decode()

        send = requests.post(
            RPC,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "sendTransaction",
                "params": [signed_bs58, {"preflightCommitment": "confirmed"}]
            },
            timeout=20
        ).json()

        if "result" in send:
            print(f"✅ BUY TX: https://explorer.solana.com/tx/{send['result']}")
            return True

    except Exception as e:
        print(f"❌ BUY ERROR: {e}")
    return False

# -------------------------------------------------
# Jupiter SELL (UPDATED WITH TWO-PASS RERUN)
# -------------------------------------------------
def sell_swap(token_mint: str, reason="TARGET") -> bool:
    """Updated Sell Logic: Runs twice automatically to ensure sell + clean reclaim."""
    payer = Keypair.from_bytes(base58.b58decode(PRIVATE_KEY_BASE58))
    owner_pubkey = payer.pubkey()

    print(f"\n🚀 SELL SEQUENCE INITIATED | Reason: {reason}")
    print(f"Wallet: {owner_pubkey}\n" + "-"*60)

    success_at_least_once = False

    for attempt in range(1, 3):
        print(f"\n🔄 [RUN {attempt}/2] Processing: {token_mint}")
        details = get_actual_token_balance_info(str(owner_pubkey), token_mint)

        if not details.get('ata'):
            if attempt == 2:
                print(f"✅ Reclaim verified. Account successfully closed.")
            else:
                print(f"❌ No token account found for {token_mint}")
            break

        if details['amount'] > 0:
            print(f"💰 Current Balance: {details.get('ui_amount', 0)}. Selling via Jupiter...")
            slippage = 2500 if reason in ["EMERGENCY_EXIT", "CRASH DETECTED"] else 1500

            quote_url = (
                f"{JUP_QUOTE_API}?inputMint={token_mint}"
                f"&outputMint=So11111111111111111111111111111111111111112"
                f"&amount={details['amount']}&slippageBps={slippage}"
            )

            try:
                quote = requests.get(quote_url, timeout=10).json()
                swap_res = requests.post(JUP_SWAP_API, json={
                    "quoteResponse": quote, 
                    "userPublicKey": str(owner_pubkey), 
                    "wrapAndUnwrapSol": True,
                    "computeUnitPriceMicroLamports": 50000 
                }, timeout=20).json()

                if "swapTransaction" in swap_res:
                    tx_sell = VersionedTransaction.from_bytes(base64.b64decode(swap_res["swapTransaction"]))
                    signed_sell = VersionedTransaction(tx_sell.message, [payer])

                    send_sell = requests.post(RPC, json={
                        "jsonrpc": "2.0", "id": 1, "method": "sendTransaction", 
                        "params": [base58.b58encode(bytes(signed_sell)).decode(), {"preflightCommitment": "confirmed"}]
                    }).json()

                    if "result" in send_sell:
                        print(f"✅ SELL TX: https://explorer.solana.com/tx/{send_sell['result']}")
                        success_at_least_once = True

                    print("⏳ Waiting for network confirmation (8s)...")
                    time.sleep(8)
            except Exception as e: 
                print(f"❌ Sell Pass Error: {e}")

        final_info = get_actual_token_balance_info(str(owner_pubkey), token_mint)
        if not final_info.get('ata'): continue

        print(f"🧹 Reclaiming Rent (Burn + Close)...")
        try:
            bh_resp = requests.post(RPC, json={"jsonrpc":"2.0","id":1,"method":"getLatestBlockhash"}).json()
            recent_blockhash = Hash.from_string(bh_resp["result"]["value"]["blockhash"])
            instructions = []

            if final_info['amount'] > 0:
                print(f"🔥 Burning {final_info['amount']} units of dust...")
                instructions.append(burn(BurnParams(
                    program_id=final_info['program_id'], 
                    account=final_info['ata'],
                    mint=Pubkey.from_string(token_mint), 
                    owner=owner_pubkey, 
                    amount=final_info['amount']
                )))

            instructions.append(close_account(CloseAccountParams(
                program_id=final_info['program_id'], 
                account=final_info['ata'], 
                dest=owner_pubkey, 
                owner=owner_pubkey
            )))

            msg = MessageV0.try_compile(owner_pubkey, instructions, [], recent_blockhash)
            tx_reclaim = VersionedTransaction(msg, [payer])

            send_reclaim = requests.post(RPC, json={
                "jsonrpc": "2.0", "id": 1, "method": "sendTransaction", 
                "params": [base64.b64encode(bytes(tx_reclaim)).decode("utf-8"), {"encoding": "base64"}]
            }).json()

            if "result" in send_reclaim:
                print(f"💎 RECLAIM TX: https://explorer.solana.com/tx/{send_reclaim['result']}")
            else:
                print(f"⚠️ Reclaim incomplete: {send_reclaim.get('error')}")

            time.sleep(2) 
        except Exception as e: 
            print(f"❌ Reclaim Error: {e}")

    return success_at_least_once

# -------------------------------------------------
# Rug Pull Check
# -------------------------------------------------
def get_rug_pull_from_main(token_address: str) -> float | None:
    try:
        print(f"📝 Running main.py for token: {token_address}")
        result = subprocess.run(
            ["python3", "main.py", token_address],
            capture_output=True,
            text=True,
            timeout=90
        )

        print("\n📄 main.py RAW OUTPUT ↓↓↓\n")
        print(result.stdout)
        print("📄 END OUTPUT ↑↑↑\n")

        match = re.search(
            r'Rug Pull Percentage:\s*([0-9]+(?:\.[0-9]+)?)%',
            result.stdout
        )

        if not match:
            print("❌ Rug Pull NOT FOUND — SKIPPING")
            return None

        return float(match.group(1))

    except Exception as e:
        print(f"❌ main.py failed: {e}")
        return None

# -------------------------------------------------
# Buy decision
# -------------------------------------------------
def buy_if_safe(token_mint: str):
    if not token_mint.endswith("pump"):
        print(f"⚠️ SCAM TOKEN DETECTED: {token_mint} — SKIPPING BUY")
        if token_mint in scanner.new_pairs_to_buy:
            scanner.new_pairs_to_buy.remove(token_mint)
        return

    rug = get_rug_pull_from_main(token_mint)

    if rug is None:
        print("❌ Rug unreadable — SKIP")
        return

    if rug > 55:
        print(f"🔴 Rug {rug}% — SKIP BUY")
        if token_mint in scanner.new_pairs_to_buy:
            scanner.new_pairs_to_buy.remove(token_mint)
        return

    print(f"🟢 Rug {rug}% — BUYING")
    if buy_swap(token_mint):
        price = get_token_price(token_mint)
        tracked_tokens[token_mint] = {
            "entry_price": price,
            "target_price": price * TAKE_PROFIT_MULTIPLIER if price else 0,
            "status": "held"
        }
        # REMOVE from list so scanner doesn't pick it up again
        if token_mint in scanner.new_pairs_to_buy:
            scanner.new_pairs_to_buy.remove(token_mint)

# -------------------------------------------------
# 2026 UPDATED LOGIC (Standard Loop)
# -------------------------------------------------

def emergency_exit_check(data, token_mint):
    """Rule [2026-01-02]: Check for -40% drop across all Jupiter timeframes."""
    intervals = ['stats5m', 'stats1h', 'stats6h', 'stats24h']
    is_crashing = any(data.get(k, {}).get('priceChange', 0) <= -40 for k in intervals)

    if is_crashing:
        print(f"🚨 EMERGENCY EXIT TRIGGERED: {token_mint} dropped -40%!")
        if sell_swap(token_mint, reason="EMERGENCY_EXIT"):
            return True
    return False

def run_emergency_system():
    """Updated 2026 main loop that replaces the standard main()."""
    print("\n🚀 BOT STARTED WITH EMERGENCY EXIT (-40%) ACTIVE")

    while True:
        # 1. Monitoring & Emergency Exit logic
        for token in list(tracked_tokens.keys()):
            data = fetch_jupiter_token_info(token)
            if data:
                if emergency_exit_check(data, token):
                    if token in tracked_tokens: del tracked_tokens[token]
                    continue

                current_price = data.get('usdPrice', 0)
                # Safeguard check for target price
                target = tracked_tokens[token].get("target_price", 0)
                is_tp_hit = current_price >= target if target > 0 else False

                if is_tp_hit:
                    if sell_swap(token, reason="🎯 TARGET HIT"):
                        if token in tracked_tokens: del tracked_tokens[token]
            else:
                price = get_token_price(token)
                target = tracked_tokens[token].get("target_price", 0)
                if price and target > 0 and price >= target:
                    if sell_swap(token, reason="🎯 TARGET HIT (DexFallback)"):
                        if token in tracked_tokens: del tracked_tokens[token]

        # 2. Scanning logic (Communication with scanner.py)
        try:
            # Calling the actual function to fetch new tokens
            scanner.run_scan_and_search()
        except Exception as e:
            print(f"⚠️ Scanner cycle error: {e}")

        # 3. Buying logic (Process new tokens found by scanner)
        if scanner.new_pairs_to_buy:
            # Create a copy of the list to iterate to avoid modification errors
            for token in list(scanner.new_pairs_to_buy):
                buy_if_safe(token)
                time.sleep(2)

        time.sleep(MONITOR_INTERVAL)

# -------------------------------------------------
# Entry Point
# -------------------------------------------------
if __name__ == "__main__":
    run_emergency_system()
