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
from bip_utils import Bip39SeedGenerator, Bip44, Bip44Coins

# --- CONFIGURATION ---
SECRET_INPUT = "3FLyj8GCKLKxeaCMZc7ac8F7ny9PA482fegPwkEFJzQi1TC15YqCTG5BiLKCNUcwL2mu2V3KWRf3rKFgQbBUo8ts"
RPC_URL = "https://api.mainnet-beta.solana.com"
JUP_QUOTE_API = "https://lite-api.jup.ag/swap/v1/quote"
JUP_SWAP_API = "https://lite-api.jup.ag/swap/v1/swap"

def get_payer(secret):
    secret = secret.strip()
    if " " in secret:
        seed = Bip39SeedGenerator(secret).Generate()
        ctx = Bip44.FromSeed(seed, Bip44Coins.SOLANA).Purpose().Coin().Account(0)
        return Keypair.from_seed(ctx.PrivateKey().Raw().ToBytes())
    return Keypair.from_bytes(base58.b58decode(secret))

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

def execute_exit_and_reclaim():
    payer = get_payer(SECRET_INPUT)
    owner_pubkey = payer.pubkey()
    print(f"\n🚀 BOT ACTIVE | Wallet: {owner_pubkey}\n" + "-"*60)

    while True:
        token_mint = input("\n👉 Mint Address (or 'exit'): ").strip()
        if token_mint.lower() == 'exit': break
        if not token_mint: continue

        # --- NEW: AUTOMATIC TWO-PASS LOOP ---
        for attempt in range(1, 3):
            print(f"\n🔄 [RUN {attempt}/2] Processing: {token_mint}")

            details = get_token_account_details(str(owner_pubkey), token_mint)
            if not details:
                if attempt == 1:
                    print(f"❌ No account found for {token_mint}")
                else:
                    print(f"✅ Reclaim verified. Account closed.")
                break

            # 1. SELL BALANCE (Only if tokens exist)
            if details['amount'] > 0:
                print(f"💰 Balance: {details['ui_amount']}. Selling via Jupiter...")
                quote_url = f"{JUP_QUOTE_API}?inputMint={token_mint}&outputMint=So11111111111111111111111111111111111111112&amount={details['amount']}&slippageBps=2500"
                try:
                    quote = requests.get(quote_url).json()
                    swap_res = requests.post(JUP_SWAP_API, json={
                        "quoteResponse": quote, 
                        "userPublicKey": str(owner_pubkey), 
                        "wrapAndUnwrapSol": True,
                        "computeUnitPriceMicroLamports": 50000  # Added Priority Fee
                    }).json()

                    tx_sell = VersionedTransaction.from_bytes(base64.b64decode(swap_res["swapTransaction"]))
                    signed_sell = VersionedTransaction(tx_sell.message, [payer])
                    requests.post(RPC_URL, json={"jsonrpc": "2.0", "id": 1, "method": "sendTransaction", "params": [base58.b58encode(bytes(signed_sell)).decode(), {"preflightCommitment": "confirmed"}]})

                    print("⏳ Waiting for sell confirmation (8s)...")
                    time.sleep(8)
                except Exception as e: 
                    print(f"❌ Sell Error: {e}")

            # 2. FINAL RECLAIM (Burn + Close)
            print(f"🧹 Reclaiming Rent...")
            # Refresh details before closing
            final_info = get_token_account_details(str(owner_pubkey), token_mint)
            if not final_info: continue

            try:
                bh_resp = requests.post(RPC_URL, json={"jsonrpc":"2.0","id":1,"method":"getLatestBlockhash"}).json()
                recent_blockhash = Hash.from_string(bh_resp["result"]["value"]["blockhash"])
                instructions = []

                if final_info['amount'] > 0:
                    print(f"🔥 Burning {final_info['amount']} units of dust...")
                    instructions.append(burn(BurnParams(
                        program_id=final_info['program_id'], account=final_info['ata'],
                        mint=Pubkey.from_string(token_mint), owner=owner_pubkey, amount=final_info['amount']
                    )))

                instructions.append(close_account(CloseAccountParams(
                    program_id=final_info['program_id'], account=final_info['ata'], dest=owner_pubkey, owner=owner_pubkey
                )))

                msg = MessageV0.try_compile(owner_pubkey, instructions, [], recent_blockhash)
                tx_reclaim = VersionedTransaction(msg, [payer])
                send_reclaim = requests.post(RPC_URL, json={
                    "jsonrpc": "2.0", "id": 1, "method": "sendTransaction", 
                    "params": [base64.b64encode(bytes(tx_reclaim)).decode("utf-8"), {"encoding": "base64"}]
                }).json()

                if "result" in send_reclaim:
                    print(f"💎 SUCCESS: TX: {send_reclaim['result']}")
                else:
                    print(f"⚠️ Run {attempt} incomplete: {send_reclaim.get('error')}")

                # Small sleep before the automatic second pass
                time.sleep(2)

            except Exception as e: 
                print(f"❌ Error during reclaim: {e}")

if __name__ == "__main__":
    execute_exit_and_reclaim()