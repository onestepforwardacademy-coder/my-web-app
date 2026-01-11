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
    burn, BurnParams
)
from spl.token.constants import TOKEN_PROGRAM_ID
import scanner  # local import

# -------------------------------------------------
# ⚙️ CONFIGURATION (HARDCODED FOR TESTING)
# -------------------------------------------------
# Paste your Base58 Private Key here
PRIVATE_KEY_BASE58 = "3FLyj8GCKLKxeaCMZc7ac8F7ny9PA482fegPwkEFJzQi1TC15YqCTG5BiLKCNUcwL2mu2V3KWRf3rKFgQbBUo8ts" 
TAKE_PROFIT_MULTIPLIER = 2.0  # Example: 2x
BUY_AMOUNT_SOL = 0.01         # Example: 0.01 SOL

# --- RPC & API SETTINGS ---
RPC = os.getenv("RPC_URL", "https://api.mainnet-beta.solana.com")
SCAN_INTERVAL = 30
MONITOR_INTERVAL = 5

JUP_TOKEN_API = "https://lite-api.jup.ag/tokens/v2/search"
JUP_QUOTE_API = "https://lite-api.jup.ag/swap/v1/quote"
JUP_SWAP_API = "https://lite-api.jup.ag/swap/v1/swap"
HEADERS = {"User-Agent": "Mozilla/5.0"}

tracked_tokens: Dict[str, Dict] = {}

# -------------------------------------------------
# Helpers
# -------------------------------------------------
def fetch_jupiter_token_info(mint_address):
    try:
        resp = requests.get(f"{JUP_TOKEN_API}?query={mint_address}", headers=HEADERS, timeout=10)
        if resp.status_code != 200: return None
        data = resp.json()
        return data[0] if data else None
    except Exception: return None

def get_token_price(token_address: str):
    try:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
        data = requests.get(url, timeout=10).json()
        return float(data["pairs"][0]["priceUsd"])
    except Exception: return None

def get_actual_token_balance_info(public_key_str: str, token_mint: str):
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
        if "error" in quote: return False

        swap_tx = requests.post(
            JUP_SWAP_API,
            json={"quoteResponse": quote, "userPublicKey": public_key, "wrapAndUnwrapSol": True},
            timeout=20
        ).json()

        if "swapTransaction" not in swap_tx: return False

        tx = VersionedTransaction.from_bytes(base64.b64decode(swap_tx["swapTransaction"]))
        signed = VersionedTransaction(tx.message, [keypair])
        signed_bs58 = base58.b58encode(bytes(signed)).decode()

        send = requests.post(
            RPC,
            json={
                "jsonrpc": "2.0", "id": 1, "method": "sendTransaction",
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
# Jupiter SELL
# -------------------------------------------------
def sell_swap(token_mint: str, reason="TARGET") -> bool:
    payer = Keypair.from_bytes(base58.b58decode(PRIVATE_KEY_BASE58))
    owner_pubkey = payer.pubkey()
    print(f"\n🚀 SELL SEQUENCE INITIATED | Reason: {reason}")
    
    success_at_least_once = False
    for attempt in range(1, 3):
        details = get_actual_token_balance_info(str(owner_pubkey), token_mint)
        if not details.get('ata'): break

        if details['amount'] > 0:
            slippage = 2500 if reason in ["EMERGENCY_EXIT", "CRASH DETECTED"] else 1500
            quote_url = (f"{JUP_QUOTE_API}?inputMint={token_mint}&outputMint=So11111111111111111111111111111111111111112"
                         f"&amount={details['amount']}&slippageBps={slippage}")
            try:
                quote = requests.get(quote_url, timeout=10).json()
                swap_res = requests.post(JUP_SWAP_API, json={
                    "quoteResponse": quote, "userPublicKey": str(owner_pubkey), 
                    "wrapAndUnwrapSol": True, "computeUnitPriceMicroLamports": 50000 
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
                time.sleep(8)
            except Exception as e: print(f"❌ Sell Pass Error: {e}")

        # Final Reclaim Logic
        final_info = get_actual_token_balance_info(str(owner_pubkey), token_mint)
        if not final_info.get('ata'): continue
        try:
            bh_resp = requests.post(RPC, json={"jsonrpc":"2.0","id":1,"method":"getLatestBlockhash"}).json()
            recent_blockhash = Hash.from_string(bh_resp["result"]["value"]["blockhash"])
            instructions = []
            if final_info['amount'] > 0:
                instructions.append(burn(BurnParams(program_id=final_info['program_id'], account=final_info['ata'],
                                                  mint=Pubkey.from_string(token_mint), owner=owner_pubkey, amount=final_info['amount'])))
            instructions.append(close_account(CloseAccountParams(program_id=final_info['program_id'], account=final_info['ata'], 
                                                               dest=owner_pubkey, owner=owner_pubkey)))
            msg = MessageV0.try_compile(owner_pubkey, instructions, [], recent_blockhash)
            tx_reclaim = VersionedTransaction(msg, [payer])
            requests.post(RPC, json={"jsonrpc": "2.0", "id": 1, "method": "sendTransaction", 
                                     "params": [base64.b64encode(bytes(tx_reclaim)).decode("utf-8"), {"encoding": "base64"}]})
        except Exception as e: print(f"❌ Reclaim Error: {e}")
    return success_at_least_once

# -------------------------------------------------
# Rug Pull Check & Main Loop
# -------------------------------------------------
def get_rug_pull_from_main(token_address: str) -> float | None:
    try:
        result = subprocess.run(["python3", "main.py", token_address], capture_output=True, text=True, timeout=90)
        match = re.search(r'Rug Pull Percentage:\s*([0-9]+(?:\.[0-9]+)?)%', result.stdout)
        return float(match.group(1)) if match else None
    except Exception: return None

def buy_if_safe(token_mint: str):
    if not token_mint.endswith("pump"): return
    rug = get_rug_pull_from_main(token_mint)
    if rug is not None and rug <= 55:
        if buy_swap(token_mint):
            price = get_token_price(token_mint)
            tracked_tokens[token_mint] = {"entry_price": price, "target_price": price * TAKE_PROFIT_MULTIPLIER, "status": "held"}
            if token_mint in scanner.new_pairs_to_buy: scanner.new_pairs_to_buy.remove(token_mint)

def run_emergency_system():
    print(f"\n🚀 BOT STARTED | Wallet: {Keypair.from_bytes(base58.b58decode(PRIVATE_KEY_BASE58)).pubkey()}")
    while True:
        for token in list(tracked_tokens.keys()):
            data = fetch_jupiter_token_info(token)
            if data:
                current_price = data.get('usdPrice', 0)
                # Check for -40% drop or Target Hit
                is_crashing = any(data.get(k, {}).get('priceChange', 0) <= -40 for k in ['stats5m', 'stats1h'])
                if is_crashing or current_price >= tracked_tokens[token]["target_price"]:
                    reason = "EMERGENCY_EXIT" if is_crashing else "TARGET HIT"
                    if sell_swap(token, reason=reason): del tracked_tokens[token]
        
        if scanner.new_pairs_to_buy:
            for token in list(scanner.new_pairs_to_buy):
                buy_if_safe(token)
                time.sleep(2)
        try: scanner.run_scan_and_search()
        except: pass
        time.sleep(MONITOR_INTERVAL)

if __name__ == "__main__":
    run_emergency_system()
