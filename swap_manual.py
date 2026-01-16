#!/usr/bin/env python3
import sys
import os
import base58
import base64
import requests
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction

if len(sys.argv) < 4:
    print("ERROR: Usage: python3 swap_manual.py <PRIVATE_KEY> <TOKEN_MINT> <AMOUNT_SOL>")
    sys.exit(1)

PRIVATE_KEY = sys.argv[1]
TOKEN_MINT = sys.argv[2]
AMOUNT_SOL = float(sys.argv[3])

RPC = os.getenv("RPC_URL", "https://api.mainnet-beta.solana.com")
JUP_QUOTE_API = "https://lite-api.jup.ag/swap/v1/quote"
JUP_SWAP_API = "https://lite-api.jup.ag/swap/v1/swap"

def buy_swap():
    print(f"🟢 BUYING {TOKEN_MINT}")
    print(f"Amount: {AMOUNT_SOL} SOL")
    
    keypair = Keypair.from_bytes(base58.b58decode(PRIVATE_KEY))
    public_key = str(keypair.pubkey())
    
    AMOUNT = int(AMOUNT_SOL * 1_000_000_000)
    
    quote_url = (
        f"{JUP_QUOTE_API}"
        f"?inputMint=So11111111111111111111111111111111111111112"
        f"&outputMint={TOKEN_MINT}"
        f"&amount={AMOUNT}"
        f"&slippageBps=500"
    )
    
    try:
        quote = requests.get(quote_url, timeout=10).json()
        if "error" in quote:
            print("❌ Jupiter quote failed: " + str(quote.get("error", "")))
            return False
        
        out_amount = int(quote.get("outAmount", 0))
        print(f"Expected tokens: {out_amount:,}")
        
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
            sig = send["result"]
            print(f"✅ SUCCESS!")
            print(f"Signature: {sig}")
            print(f"View: https://solscan.io/tx/{sig}")
            return True
        else:
            print("❌ Transaction failed: " + str(send.get("error", "")))
            
    except Exception as e:
        print(f"❌ ERROR: {e}")
    return False

if __name__ == "__main__":
    buy_swap()
