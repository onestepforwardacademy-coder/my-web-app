import sys
from solana.rpc.api import Client
from solders.keypair import Keypair
from bip_utils import Bip39SeedGenerator, Bip32Slip10Ed25519
import nacl.signing

def sync_wallet():
    # Receive mnemonic from index.js arguments
    if len(sys.argv) < 2:
        print("ERROR: No mnemonic provided")
        return

    # Join arguments in case the phrase is passed as multiple strings
    mnemonic_input = " ".join(sys.argv[1:])

    try:
        # 1. Generate BIP39 seed (The Trust Wallet way)
        seed = Bip39SeedGenerator(mnemonic_input).Generate()

        # 2. Derive key using SLIP-0010 Ed25519
        path = "m/44'/501'/0'"
        bip32_ctx = Bip32Slip10Ed25519.FromSeed(seed)
        derived = bip32_ctx.DerivePath(path)

        # 3. Handle Bytes
        private_key_32 = derived.PrivateKey().Raw().ToBytes()
        signing_key = nacl.signing.SigningKey(private_key_32)
        public_key_32 = signing_key.verify_key.encode()
        secret_key_64 = private_key_32 + public_key_32

        # 4. Create Keypair
        keypair = Keypair.from_bytes(secret_key_64)
        public_key = keypair.pubkey()

        # 5. Connect and Fetch
        client = Client("https://api.mainnet-beta.solana.com")
        balance_resp = client.get_balance(public_key)
        sol_balance = balance_resp.value / 1_000_000_000

        # OUTPUT FOR INDEX.JS TO READ
        print(f"ADDRESS:{public_key}")
        print(f"BALANCE:{sol_balance}")
        # Print the secret key so index.js can use it for trading
        import base58
        print(f"SECRET:{base58.b58encode(secret_key_64).decode()}")

    except Exception as e:
        print(f"ERROR:{str(e)}")

if __name__ == "__main__":
    sync_wallet()