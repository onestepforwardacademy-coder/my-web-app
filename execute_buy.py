import sys
import base58
import requests
from solana.rpc.api import Client
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction

def sniper_buy():
    # Expects args: [script_name, private_key_b58, token_mint_address, amount_sol]
    if len(sys.argv) < 4:
        print("[-] Error: Missing arguments")
        return

    priv_key_str = sys.argv[1]
    token_address = sys.argv[2]
    amount_sol = float(sys.argv[3])

    # 1. Setup Connection (Use a fast RPC if possible)
    RPC_URL = "https://api.mainnet-beta.solana.com"
    client = Client(RPC_URL)

    try:
        # 2. Setup Wallet from Private Key
        payer = Keypair.from_bytes(base58.b58decode(priv_key_str))
        mint = Pubkey.from_string(token_address)
        print(f"[*] Executing buy for: {payer.pubkey()} | Token: {token_address}")

        # 3. Fetch Transaction from PumpPortal (Reliable & Fast)
        response = requests.post(
            "https://pumpportal.fun/api/trade-local",
            json={
                "publicKey": str(payer.pubkey()),
                "action": "buy",
                "mint": str(mint),
                "denominatedInSol": "true",
                "amount": amount_sol,
                "slippage": 10,  # 10% Slippage
                "priorityFee": 0.0001,
                "pool": "pump"
            }
        )

        if response.status_code == 200:
            # 4. Sign and Broadcast
            tx_bytes = response.content
            tx = VersionedTransaction.from_bytes(tx_bytes)

            # Sign with user's specific key
            signature = client.send_raw_transaction(bytes(tx.sign([payer])))
            print(f"[+] BUY SUCCESS | Signature: {signature.value}")
        else:
            print(f"[-] API Error: {response.text}")

    except Exception as e:
        print(f"[-] Buy Failed: {str(e)}")

if __name__ == "__main__":
    sniper_buy()