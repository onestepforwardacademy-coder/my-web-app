from solana.rpc.api import Client
from solders.keypair import Keypair
from bip_utils import Bip39SeedGenerator, Bip32Slip10Ed25519
import nacl.signing

# -----------------------------------
# TRUST WALLET GENERATED MNEMONIC
# ⚠️ DEMO ONLY — DO NOT USE REAL FUNDS
# -----------------------------------
MNEMONIC_WORDS = (
    "finish member teach dinosaur sting civil "
    "cactus boil doctor fever another approve"
)

# Generate BIP39 seed
seed = Bip39SeedGenerator(MNEMONIC_WORDS).Generate()

# Trust Wallet Solana derivation path
path = "m/44'/501'/0'"

# Derive key using SLIP-0010 Ed25519
bip32_ctx = Bip32Slip10Ed25519.FromSeed(seed)
derived = bip32_ctx.DerivePath(path)

# 32-byte private key
private_key_32 = derived.PrivateKey().Raw().ToBytes()

# Derive public key
signing_key = nacl.signing.SigningKey(private_key_32)
public_key_32 = signing_key.verify_key.encode()

# Combine into Solana 64-byte secret key
secret_key_64 = private_key_32 + public_key_32

# Create Solana keypair
keypair = Keypair.from_bytes(secret_key_64)

# Public address
public_key = keypair.pubkey()
print("Public Address:", public_key)

# Connect to Solana Mainnet
client = Client("https://api.mainnet-beta.solana.com")

# Fetch SOL balance
balance_resp = client.get_balance(public_key)
sol_balance = balance_resp.value / 1_000_000_000

print("SOL Balance:", sol_balance)
