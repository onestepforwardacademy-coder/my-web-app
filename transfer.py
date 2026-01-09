import sys
import base58
import base64
from solana.rpc.api import Client
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from nacl.signing import SigningKey

# ---------------- ARGUMENTS ----------------
if len(sys.argv) != 4:
    print("Usage: python3 transfer.py <secretBase58> <toAddress> <amountSOL>")
    sys.exit(1)

secret_base58 = sys.argv[1]
to_address = sys.argv[2]
amount_sol = float(sys.argv[3])

# ---------------- CLIENT ----------------
RPC_URL = "https://api.mainnet-beta.solana.com"
client = Client(RPC_URL)

# ---------------- LOAD WALLET ----------------
secret_key = base58.b58decode(secret_base58)
wallet = Keypair.from_bytes(secret_key)

# ---------------- BLOCKHASH ----------------
latest = client.get_latest_blockhash()
recent_blockhash = latest.value.blockhash

# ---------------- LAMPORTS ----------------
LAMPORTS_PER_SOL = 1_000_000_000
lamports = int(amount_sol * LAMPORTS_PER_SOL)

from_pubkey = wallet.pubkey()
to_pubkey = Pubkey.from_string(to_address)
system_program = Pubkey.from_string("11111111111111111111111111111111")

# ---------------- ACCOUNT METADATA ----------------
account_keys = [
    (from_pubkey, True, True),
    (to_pubkey, False, True),
    (system_program, False, False)
]

# ---------------- HELPERS ----------------
def pubkey_bytes(pk: Pubkey) -> bytes:
    return bytes(pk)

def encode_shortvec(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n == 0:
            out.append(b)
            break
        out.append(0x80 | b)
    return bytes(out)

# ---------------- HEADER ----------------
num_required_signatures = sum(1 for (_, signer, _) in account_keys if signer)
num_readonly_signed = sum(1 for (_, signer, writable) in account_keys if signer and not writable)
num_readonly_unsigned = sum(1 for (_, signer, writable) in account_keys if not signer and not writable)

header = bytes([
    num_required_signatures,
    num_readonly_signed,
    num_readonly_unsigned
])

# ---------------- INSTRUCTION ----------------
ix_accounts = [0, 1]
data = (2).to_bytes(4, "little") + lamports.to_bytes(8, "little")
program_index = 2

ix_serialized = (
    program_index.to_bytes(1, "little") +
    encode_shortvec(len(ix_accounts)) +
    bytes(ix_accounts) +
    encode_shortvec(len(data)) +
    data
)

# ---------------- BUILD MESSAGE ----------------
version_prefix = bytes([0x80])
account_pubkeys = [pk for (pk, _, _) in account_keys]

message_body = (
    header +
    encode_shortvec(len(account_pubkeys)) +
    b"".join(pubkey_bytes(k) for k in account_pubkeys) +
    bytes(recent_blockhash) +
    encode_shortvec(1) +
    ix_serialized +
    encode_shortvec(0)
)

message_bytes = version_prefix + message_body

# ---------------- SIGN ----------------
signer = SigningKey(secret_key[:32])
signed = signer.sign(message_bytes)
signature = signed.signature

# ---------------- FINAL TX ----------------
tx_wire = encode_shortvec(1) + signature + message_bytes

# ---------------- SEND ----------------
try:
    resp = client.send_raw_transaction(tx_wire)
    sig = resp.value
    print(sig)  # <-- Only the tx signature, used by bot
except Exception as e:
    print(f"ERROR: {e}")
