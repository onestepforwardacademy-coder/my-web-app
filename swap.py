#!/usr/bin/env python3
"""
Standalone swap module for manual token swaps.
Usage: python3 swap.py <BASE58_PRIVATE_KEY> <TOKEN_MINT> <AMOUNT_SOL>
Returns: JSON with tx signature, amount, and status
"""

import sys
import json
import base58
import base64
import requests
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction

# Jupiter API endpoints
JUP_QUOTE_API = "https://lite-api.jup.ag/swap/v1/quote"
JUP_SWAP_API = "https://lite-api.jup.ag/swap/v1/swap"
RPC = "https://api.mainnet-beta.solana.com"
HEADERS = {"User-Agent": "Mozilla/5.0"}
SOL_MINT = "So11111111111111111111111111111111111111112"

def get_token_info(token_mint):
    """Fetch token info from Dexscreener"""
    try:
        url = f"https://api.dexscreener.com/token-pairs/v1/solana/{token_mint}"
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200 or not resp.json():
            return None
        pair = resp.json()[0]
        base = pair.get("baseToken", {})
        return {
            "name": base.get("name", "Unknown"),
            "symbol": base.get("symbol", "???"),
            "price_usd": pair.get("priceUsd", "0"),
            "price_sol": pair.get("priceNative", "0"),
            "liquidity": pair.get("liquidity", {}).get("usd", 0),
            "mcap": pair.get("marketCap", 0),
            "volume_24h": pair.get("volume", {}).get("h24", 0),
            "change_24h": pair.get("priceChange", {}).get("h24", 0)
        }
    except Exception as e:
        return None

def swap_sol_to_token(private_key_b58, token_mint, amount_sol):
    """Execute SOL -> Token swap via Jupiter"""
    result = {
        "success": False,
        "tx_signature": None,
        "amount_sol": amount_sol,
        "token_mint": token_mint,
        "error": None
    }
    
    try:
        keypair = Keypair.from_bytes(base58.b58decode(private_key_b58))
        public_key = str(keypair.pubkey())
        
        amount_lamports = int(float(amount_sol) * 1_000_000_000)
        
        # Get quote
        quote_url = (
            f"{JUP_QUOTE_API}"
            f"?inputMint={SOL_MINT}"
            f"&outputMint={token_mint}"
            f"&amount={amount_lamports}"
            f"&slippageBps=500"
        )
        
        quote = requests.get(quote_url, timeout=10).json()
        if "error" in quote:
            result["error"] = f"Quote failed: {quote.get('error')}"
            return result
        
        # Get expected output
        out_amount = int(quote.get("outAmount", 0))
        result["tokens_received"] = out_amount
        
        # Get swap transaction
        swap_res = requests.post(
            JUP_SWAP_API,
            json={
                "quoteResponse": quote,
                "userPublicKey": public_key,
                "wrapAndUnwrapSol": True,
                "computeUnitPriceMicroLamports": 50000
            },
            timeout=20
        ).json()
        
        if "swapTransaction" not in swap_res:
            result["error"] = "No swap transaction returned"
            return result
        
        # Sign and send
        tx = VersionedTransaction.from_bytes(base64.b64decode(swap_res["swapTransaction"]))
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
            result["success"] = True
            result["tx_signature"] = send["result"]
        else:
            result["error"] = send.get("error", {}).get("message", "Unknown error")
            
    except Exception as e:
        result["error"] = str(e)
    
    return result

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(json.dumps({"error": "Usage: swap.py <PK> <TOKEN> <AMOUNT> or swap.py info <TOKEN>"}))
        sys.exit(1)
    
    # Handle info command first
    if sys.argv[1] == "info":
        token = sys.argv[2]
        info = get_token_info(token)
        if info:
            print(json.dumps(info))
        else:
            print(json.dumps({"error": "Token not found"}))
        sys.exit(0)
    
    # Normal swap requires 4 args
    if len(sys.argv) < 4:
        print(json.dumps({"error": "Usage: swap.py <PK> <TOKEN> <AMOUNT>"}))
        sys.exit(1)
    
    pk = sys.argv[1]
    token = sys.argv[2]
    amount = sys.argv[3]
    
    result = swap_sol_to_token(pk, token, amount)
    print(json.dumps(result))
