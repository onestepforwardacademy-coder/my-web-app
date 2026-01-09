import os
import sys
import requests
import base64
import base58
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.hash import Hash
from solders.message import MessageV0
from solders.transaction import VersionedTransaction
from spl.token.instructions import close_account, CloseAccountParams
from bip_utils import Bip39SeedGenerator, Bip44, Bip44Coins, Bip44Changes

# --- CONFIG ---
# Usage: python3 test_solana.py <KEY_OR_MNEMONIC> <TOKEN_MINT>
RPC_URL = os.getenv("RPC_URL", "https://api.mainnet-beta.solana.com")

def load_wallet(input_str: str) -> Keypair:
    """Detects if input is a private key or a 12/24 word mnemonic."""
    words = input_str.strip().split()

    # Check if it's a mnemonic (12, 15, 18, 21, or 24 words)
    if len(words) in [12, 15, 18, 21, 24]:
        print("🔐 Mnemonic detected. Deriving key...")
        seed_bytes = Bip39SeedGenerator(input_str).Generate()
        bip44_mst_ctx = Bip44.FromSeed(seed_bytes, Bip44Coins.SOLANA)
        # Standard Solana path: m/44'/501'/0'/0'
        bip44_acc_ctx = bip44_mst_ctx.Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0)
        return Keypair.from_bytes(bip44_acc_ctx.PrivateKey().Raw().ToBytes() + bip44_acc_ctx.PublicKey().Raw().ToBytes())

    # Otherwise, assume it's a Base58 Private Key (from index.js or bot.py)
    try:
        return Keypair.from_bytes(base58.b58decode(input_str))
    except Exception:
        print("❌ Error: Input is neither a valid mnemonic nor a Base58 private key.")
        sys.exit(1)

def prove_and_close(wallet_input, token_mint):
    payer = load_wallet(wallet_input)
    owner_pubkey = payer.pubkey()
    print(f"🚀 Active Wallet: {owner_pubkey}")
    print(f"🎯 Target Token: {token_mint}")
    print("-" * 50)

    # 1. Fetch account and its owner
    payload = {
        "jsonrpc": "2.0", "id": 1, "method": "getTokenAccountsByOwner",
        "params": [str(owner_pubkey), {"mint": token_mint}, {"encoding": "jsonParsed"}]
    }

    res = requests.post(RPC_URL, json=payload).json()
    accounts = res.get("result", {}).get("value", [])

    if not accounts:
        print("❌ No open account found to close. (Already closed or never opened)")
        return

    acc = accounts[0]
    ata_to_close = Pubkey.from_string(acc["pubkey"])
    actual_program_id = Pubkey.from_string(acc["account"]["owner"])
    balance = acc["account"]["data"]["parsed"]["info"]["tokenAmount"]["uiAmount"]

    program_name = "Token-2022" if "Tokenz" in str(actual_program_id) else "Legacy"
    print(f"✅ Found {program_name} Account: {ata_to_close}")
    print(f"💰 Balance: {balance} tokens")

    if balance > 0:
        print(f"❌ CANNOT CLOSE: Balance is {balance}. Please sell or burn tokens first.")
        return

    # 2. Prepare Closure
    print(f"🛠️  Reclaiming rent...")

    ix = close_account(CloseAccountParams(
        program_id=actual_program_id, 
        account=ata_to_close,
        dest=owner_pubkey,
        owner=owner_pubkey
    ))

    # Fetch blockhash
    bh_resp = requests.post(RPC_URL, json={"jsonrpc":"2.0","id":1,"method":"getLatestBlockhash"}).json()
    recent_blockhash = Hash.from_string(bh_resp["result"]["value"]["blockhash"])

    # 3. Compile, Sign, and Send
    message = MessageV0.try_compile(payer=owner_pubkey, instructions=[ix], 
                                   address_lookup_table_accounts=[], recent_blockhash=recent_blockhash)
    tx = VersionedTransaction(message, [payer])
    encoded_tx = base64.b64encode(bytes(tx)).decode("utf-8")

    send_res = requests.post(RPC_URL, json={
        "jsonrpc": "2.0", "id": 1, "method": "sendTransaction",
        "params": [encoded_tx, {"encoding": "base64"}]
    }).json()

    if "result" in send_res:
        print(f"💰 SUCCESS! Rent reclaimed. Signature: {send_res['result']}")
    else:
        print(f"❌ Transaction Failed: {send_res.get('error')}")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("❌ Usage: python3 test_solana.py <KEY_OR_MNEMONIC> <TOKEN_MINT>")
        sys.exit(1)

    user_key = sys.argv[1]
    mint_addr = sys.argv[2]
    prove_and_close(user_key, mint_addr)