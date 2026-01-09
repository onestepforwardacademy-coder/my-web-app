import time
from solana.rpc.api import Client
from solana.rpc.types import TokenAccountOpts
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction
from solders.message import MessageV0
from spl.token.instructions import burn, BurnParams, close_account, CloseAccountParams
from spl.token.constants import TOKEN_PROGRAM_ID
from bip_utils import Bip39SeedGenerator, Bip32Slip10Ed25519

# --- CONFIGURATION ---
MNEMONIC = "chase trap inspire salmon dash spread primary news bitter lab occur husband"
RPC_URL = "https://api.mainnet-beta.solana.com"
TOKEN_2022_PROGRAM_ID = Pubkey.from_string("TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb")

# 1. Derive Keypair (Trust Wallet Path)
seed_bytes = Bip39SeedGenerator(MNEMONIC).Generate()
bip32_mst = Bip32Slip10Ed25519.FromSeed(seed_bytes)
derived_key = bip32_mst.DerivePath("m/44'/501'/0'")
payer = Keypair.from_seed(derived_key.PrivateKey().Raw().ToBytes())

client = Client(RPC_URL)

def run_mass_reclaim():
    print(f"🔑 Wallet: {payer.pubkey()}")
    total_reclaimed = 0

    programs = [
        ("Standard SPL", TOKEN_PROGRAM_ID),
        ("Token-2022", TOKEN_2022_PROGRAM_ID)
    ]

    for label, prog_id in programs:
        print(f"\n🔎 Scanning for {label} accounts...")
        opts = TokenAccountOpts(program_id=prog_id)
        response = client.get_token_accounts_by_owner_json_parsed(payer.pubkey(), opts=opts)

        if not response.value:
            print(f"✅ No {label} accounts found.")
            continue

        accounts = response.value
        print(f"💰 Found {len(accounts)} {label} accounts.")

        for acc in accounts:
            ata_pubkey = acc.pubkey
            parsed_info = acc.account.data.parsed['info']
            mint_str = parsed_info['mint']
            raw_balance = int(parsed_info['tokenAmount']['amount'])

            # Skip Wrapped SOL
            if mint_str == "So11111111111111111111111111111111111111112":
                continue

            instructions = []

            if raw_balance > 0:
                print(f"🔥 Burning {raw_balance} dust of {mint_str[:8]}...")
                instructions.append(burn(BurnParams(
                    program_id=prog_id,
                    account=ata_pubkey,
                    mint=Pubkey.from_string(mint_str),
                    owner=payer.pubkey(),
                    amount=raw_balance
                )))

            instructions.append(close_account(CloseAccountParams(
                program_id=prog_id,
                account=ata_pubkey,
                dest=payer.pubkey(),
                owner=payer.pubkey()
            )))

            try:
                recent_blockhash = client.get_latest_blockhash().value.blockhash
                msg = MessageV0.try_compile(payer.pubkey(), instructions, [], recent_blockhash)
                tx = VersionedTransaction(msg, [payer])

                res = client.send_transaction(tx)
                # FIXED: Convert signature to string before printing
                print(f"✅ Reclaimed Rent for: {mint_str[:8]}... | Sig: {str(res.value)[:12]}...")

                total_reclaimed += 0.002039 # Average rent for a token ATA
                time.sleep(1) 
            except Exception as e:
                print(f"❌ Failed {mint_str[:8]}: {e}")

    print(f"\n🎉 Mass Reclaim Complete!")
    print(f"💵 Total SOL Recovered: ~{total_reclaimed:.4f} SOL")

if __name__ == "__main__":
    run_mass_reclaim()