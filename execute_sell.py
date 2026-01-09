import sys
import os
import time
import base58
import base64
import requests
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction
from solders.pubkey import Pubkey
from solders.message import MessageV0
from solders.hash import Hash
from spl.token.instructions import close_account, CloseAccountParams, burn, BurnParams

# Configuration
RPC_URL = os.getenv("RPC_URL", "https://api.mainnet-beta.solana.com")
JUP_QUOTE_API = "https://lite-api.jup.ag/swap/v1/quote"
JUP_SWAP_API = "https://lite-api.jup.ag/swap/v1/swap"

def get_payer(secret):
    """Directly converts base58 private key to Keypair."""
    return Keypair.from_bytes(base58.b58decode(secret.strip()))

def get_token_account_details(owner: str, mint: str):
    payload = {
        "jsonrpc": "2.0", "id": 1, "method": "getTokenAccountsByOwner",
        "params": [owner, {"mint": mint}, {"encoding": "jsonParsed"}]
    }
    try:
        res = requests.post(RPC_URL, json=payload).json()
        accounts = res.get("result", {}).get("value", [])
        if not accounts: return None
        acc = accounts[0]
        return {
            "ata": Pubkey.from_string(acc["pubkey"]),
            "program_id": Pubkey.from_string(acc["account"]["owner"]),
            "amount": int(acc["account"]["data"]["parsed"]["info"]["tokenAmount"]["amount"]),
            "ui_amount": acc["account"]["data"]["parsed"]["info"]["tokenAmount"]["uiAmount"]
        }
    except: return None

def run_panic_logic(private_key, token_mint):
    """Executes the Two-Pass sell and rent reclaim logic."""
    payer = get_payer(private_key)
    owner_pubkey = payer.pubkey()

    print(f"\n🚨 PANIC LOGIC INITIATED | Mint: {token_mint}")
    print(f"Wallet: {owner_pubkey}\n" + "-"*60)

    # --- AUTOMATIC TWO-PASS LOOP (Matches bot.py) ---
    for attempt in range(1, 3):
        print(f"\n🔄 [RUN {attempt}/2] Processing exit...")

        # 1. Fetch current status
        details = get_token_account_details(str(owner_pubkey), token_mint)

        if not details:
            if attempt == 2:
                print(f"✅ Reclaim verified. Account successfully closed.")
            else:
                print(f"❌ No account found for {token_mint}")
            break

        # 2. SELL VIA JUPITER (25% Slippage for panic mode)
        if details['amount'] > 0:
            print(f"💰 Balance: {details['ui_amount']}. Selling with 25% slippage...")
            quote_url = f"{JUP_QUOTE_API}?inputMint={token_mint}&outputMint=So11111111111111111111111111111111111111112&amount={details['amount']}&slippageBps=2500"
            try:
                quote = requests.get(quote_url).json()
                swap_res = requests.post(JUP_SWAP_API, json={
                    "quoteResponse": quote, 
                    "userPublicKey": str(owner_pubkey), 
                    "wrapAndUnwrapSol": True,
                    "computeUnitPriceMicroLamports": 50000
                }).json()

                if "swapTransaction" in swap_res:
                    tx_sell = VersionedTransaction.from_bytes(base64.b64decode(swap_res["swapTransaction"]))
                    signed_sell = VersionedTransaction(tx_sell.message, [payer])

                    send_sell = requests.post(RPC_URL, json={
                        "jsonrpc": "2.0", "id": 1, "method": "sendTransaction", 
                        "params": [base58.b58encode(bytes(signed_sell)).decode(), {"preflightCommitment": "confirmed"}]
                    }).json()

                    if "result" in send_sell:
                        print(f"✅ SELL TX: https://solscan.io/tx/{send_sell['result']}")

                    print("⏳ Waiting 8s for network confirmation...")
                    time.sleep(8) 
            except Exception as e: 
                print(f"❌ Sell Error: {e}")

        # 3. BURN DUST & RECLAIM RENT (One Transaction)
        print(f"🧹 Reclaiming Rent...")
        final_info = get_token_account_details(str(owner_pubkey), token_mint)
        if not final_info: continue

        try:
            bh_resp = requests.post(RPC_URL, json={"jsonrpc":"2.0","id":1,"method":"getLatestBlockhash"}).json()
            recent_blockhash = Hash.from_string(bh_resp["result"]["value"]["blockhash"])
            instructions = []

            # Dust handling: Burn remaining units to avoid 0x11 error
            if final_info['amount'] > 0:
                print(f"🔥 Burning {final_info['amount']} units of dust...")
                instructions.append(burn(BurnParams(
                    program_id=final_info['program_id'], account=final_info['ata'],
                    mint=Pubkey.from_string(token_mint), owner=owner_pubkey, amount=final_info['amount']
                )))

            # Add the Close Account instruction
            instructions.append(close_account(CloseAccountParams(
                program_id=final_info['program_id'], account=final_info['ata'], dest=owner_pubkey, owner=owner_pubkey
            )))

            msg = MessageV0.try_compile(owner_pubkey, instructions, [], recent_blockhash)
            tx_reclaim = VersionedTransaction(msg, [payer])

            reclaim_payload = {
                "jsonrpc": "2.0", "id": 1, "method": "sendTransaction", 
                "params": [base64.b64encode(bytes(tx_reclaim)).decode("utf-8"), {"encoding": "base64"}]
            }
            send_reclaim = requests.post(RPC_URL, json=reclaim_payload).json()

            if "result" in send_reclaim:
                print(f"💎 SUCCESS: Rent reclaimed! TX: https://solscan.io/tx/{send_reclaim['result']}")
            else:
                print(f"⚠️ Reclaim incomplete: {send_reclaim.get('error')}")

            time.sleep(2) # Brief cooldown between passes
        except Exception as e: 
            print(f"❌ Final Stage Error: {e}")

if __name__ == "__main__":
    # STRICT BOT MODE: Requires 2 arguments: PrivateKey and MintAddress
    if len(sys.argv) < 3:
        print("❌ Usage: python3 execute_sell.py <PRIVATE_KEY> <TOKEN_MINT>")
        sys.exit(1)

    # Arguments passed from bot.py
    arg_private_key = sys.argv[1]
    arg_token_mint = sys.argv[2]

    run_panic_logic(arg_private_key, arg_token_mint) 