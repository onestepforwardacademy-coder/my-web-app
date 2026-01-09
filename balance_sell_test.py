import os
import sys
import json
import base58
import base64
import requests
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction

# -------------------------------------------------
# CONFIGURATION
# -------------------------------------------------
# Arg 1: Private Key from index.js | Arg 2: Token Mint from user selection
PRIVATE_KEY_BASE58 = sys.argv[1] if len(sys.argv) > 1 else os.environ.get('PRIVATE_KEY')
# If no 2nd arg is passed, it defaults to your OLAF test token
TARGET_TOKEN_MINT = sys.argv[2] if len(sys.argv) > 2 else "7biCCUthUHDn48jTpYKFExvpJzxTcWoXjwVDBCyZpump"

RPC = os.getenv("RPC_URL", "https://api.mainnet-beta.solana.com")

def get_actual_token_balance(public_key_str, token_mint):
    """Fetches the exact number of tokens held in the wallet via RPC."""
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
            return 0
        return int(accounts[0]["account"]["data"]["parsed"]["info"]["tokenAmount"]["amount"])
    except Exception as e:
        print(f"❌ Error fetching balance: {e}")
        return 0

def sell_all_test(token_mint: str) -> bool:
    if not PRIVATE_KEY_BASE58:
        print("❌ ERROR: No Private Key provided by the bot.")
        return False

    # Decode the keypair provided by index.js
    keypair = Keypair.from_bytes(base58.b58decode(PRIVATE_KEY_BASE58))
    public_key = str(keypair.pubkey())

    # 1. FETCH ACTUAL BALANCE
    print(f"🔍 Checking balance for: {token_mint}")
    amount_to_sell = get_actual_token_balance(public_key, token_mint)

    if amount_to_sell == 0:
        print("❌ Actual balance is 0. Nothing to sell.")
        return False

    # 2. GET JUPITER QUOTE
    # Increased slippage to 1000 (10%) for Pump.fun stability
    quote_url = (
        "https://lite-api.jup.ag/swap/v1/quote"
        f"?inputMint={token_mint}"
        f"&outputMint=So11111111111111111111111111111111111111112"
        f"&amount={amount_to_sell}"
        f"&slippageBps=1000" 
    )

    try:
        quote = requests.get(quote_url, timeout=10).json()
        if "error" in quote:
            print(f"❌ Jupiter quote failed: {quote['error']}")
            return False

        est_sol = int(quote['outAmount']) / 1_000_000_000
        print(f"📡 QUOTE: Selling balance for approx {est_sol:.6f} SOL")

    except Exception as e:
        print(f"❌ Connection error: {e}")
        return False

    # 3. CREATE SWAP TRANSACTION
    swap_tx_res = requests.post(
        "https://lite-api.jup.ag/swap/v1/swap",
        json={
            "quoteResponse": quote,
            "userPublicKey": public_key,
            "wrapAndUnwrapSol": True,
            "prioritizationFeeLamports": 100000 # Adds a small priority fee to ensure it lands
        },
        timeout=20
    ).json()

    if "swapTransaction" not in swap_tx_res:
        print("❌ Swap TX generation failed")
        return False

    # 4. SIGN AND SEND
    try:
        tx = VersionedTransaction.from_bytes(
            base64.b64decode(swap_tx_res["swapTransaction"])
        )
        signed = VersionedTransaction(tx.message, [keypair])
        signed_bs58 = base58.b58encode(bytes(signed)).decode()

        print("🚀 Broadcasting Sell Transaction...")
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
            print(f"✅ SELL SUCCESS")
            print(f"🔗 TX: https://explorer.solana.com/tx/{send['result']}")
            return True

        print(f"❌ SELL FAILED: {send.get('error')}")
        return False
    except Exception as e:
        print(f"❌ Error during signing/sending: {e}")
        return False

# -------------------------------------------------
# EXECUTION
# -------------------------------------------------
if __name__ == "__main__":
    sell_all_test(TARGET_TOKEN_MINT)