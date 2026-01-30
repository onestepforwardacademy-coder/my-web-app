import sys
import json
import base58
import base64
import requests
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction

# Jupiter API endpoints (Synchronized with swap.py)
JUP_QUOTE_API = "https://lite-api.jup.ag/swap/v1/quote"
JUP_SWAP_API = "https://lite-api.jup.ag/swap/v1/swap"
RPC = "https://api.mainnet-beta.solana.com"
HEADERS = {"User-Agent": "Mozilla/5.0"}
SOL_MINT = "So11111111111111111111111111111111111111112"

def sniper_buy():
    # Expects args: [script_name, private_key_b58, token_mint_address, amount_sol]
    if len(sys.argv) < 4:
        print("[-] Error: Missing arguments")
        return

    priv_key_str = sys.argv[1]
    token_address = sys.argv[2]
    amount_sol = float(sys.argv[3])

    try:
        # Decode the provided private key
        try:
            # Solana private keys are 64 bytes (secret key)
            # Sometimes people provide the 32-byte seed
            # base58 decode the string
            import base58
            from solders.keypair import Keypair
            
            raw_key = base58.b58decode(priv_key_str)
            
            if len(raw_key) == 32:
                keypair = Keypair.from_seed(raw_key)
            elif len(raw_key) == 64:
                keypair = Keypair.from_bytes(raw_key)
            else:
                # If length is weird, it might be a JSON array string
                import json
                try:
                    parsed = json.loads(priv_key_str)
                    if isinstance(parsed, list):
                        key_bytes = bytes(parsed)
                        if len(key_bytes) == 64:
                            keypair = Keypair.from_bytes(key_bytes)
                        elif len(key_bytes) == 32:
                            keypair = Keypair.from_seed(key_bytes)
                        else:
                            print(f"[-] Invalid byte array length: {len(key_bytes)}")
                            return
                    else:
                        print(f"[-] Invalid key length: {len(raw_key)} bytes.")
                        return
                except:
                    print(f"[-] Invalid key length: {len(raw_key)} bytes.")
                    return
        except Exception as ke:
             print(f"[-] Key Error: {ke}")
             return

        public_key = str(keypair.pubkey())
        print(f"[*] Wallet Address: {public_key}")
        
        amount_lamports = int(float(amount_sol) * 1_000_000_000)
        
        # 1. Get quote
        # Clean up the token address - remove any invisible characters or pump suffix if needed
        token_address_clean = token_address.strip()
        
        quote_url = (
            f"{JUP_QUOTE_API}"
            f"?inputMint={SOL_MINT}"
            f"&outputMint={token_address_clean}"
            f"&amount={amount_lamports}"
            f"&slippageBps=500"
        )
        
        resp = requests.get(quote_url, timeout=10)
        quote = resp.json()
        if "error" in quote:
            print(f"[-] Quote failed: {quote.get('error')}")
            return
        
        # 2. Get swap transaction
        swap_payload = {
            "quoteResponse": quote,
            "userPublicKey": public_key,
            "wrapAndUnwrapSol": True,
            "computeUnitPriceMicroLamports": 500000,
            "dynamicComputeUnitLimit": True
        }
        
        swap_resp_raw = requests.post(
            JUP_SWAP_API,
            json=swap_payload,
            timeout=20
        )
        
        if swap_resp_raw.status_code != 200:
            print(f"[-] Swap API error ({swap_resp_raw.status_code}): {swap_resp_raw.text}")
            return
            
        swap_res = swap_resp_raw.json()
        
        if "swapTransaction" not in swap_res:
            print(f"[-] No swap transaction returned. Response: {json.dumps(swap_res)}")
            return
        
        # 3. Sign and send
        tx_bytes = base64.b64decode(swap_res["swapTransaction"])
        tx = VersionedTransaction.from_bytes(tx_bytes)
        
        # Log basic info to debug
        print(f"[*] Transaction message hash: {tx.message.hash()}")
        
        # Correct signing for VersionedTransaction
        # The swapTransaction from Jupiter already contains the message.
        # We need to sign the message within the transaction.
        signed_tx = VersionedTransaction(tx.message, [keypair])
        signed_bytes = bytes(signed_tx)
        signed_bs58 = base58.b58encode(signed_bytes).decode()
        
        # Verify if signature is valid locally before sending
        # Note: solders verify() checks all signatures
        # try:
        #     signed_tx.verify()
        #     print("[+] Local signature verification passed")
        # except Exception as ve:
        #     print(f"[-] Local signature verification failed: {ve}")
        
        send_res = requests.post(
            RPC,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "sendTransaction",
                "params": [signed_bs58, {"preflightCommitment": "confirmed", "encoding": "base58"}]
            },
            timeout=20
        ).json()
        
        if "result" in send_res:
            print(f"[+] BUY SUCCESS | Signature: {send_res['result']}")
        else:
            error_msg = send_res.get("error", {}).get("message", "Unknown error")
            print(f"[-] Send failed: {error_msg}")
            if "data" in send_res.get("error", {}):
                print(f"[*] Error details: {send_res['error']['data']}")
            
    except Exception as e:
        print(f"[-] Buy Failed: {str(e)}")

if __name__ == "__main__":
    sniper_buy()
