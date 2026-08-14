"""Interactive CLI to encrypt and upload one broker's credentials to Supabase.

Run this locally, answer the prompts, and your credentials are encrypted with
CRYPTO_KEY before ever leaving your machine. Requires SUPABASE_URL,
SUPABASE_SERVICE_ROLE_KEY, and CRYPTO_KEY set in your local .env.
"""
import getpass
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from credential_store import upsert_credential

KGI_FIELDS = ["user_id", "password", "token", "sid", "broker_id", "account"]


def main():
    broker = input("Broker (e.g. kgi): ").strip()
    user_id = input("Your label for this account (e.g. friend1): ").strip()

    fields = {}
    field_names = KGI_FIELDS if broker == "kgi" else None
    if field_names is None:
        print("Enter field names one at a time, blank line to finish.")
        while True:
            name = input("Field name (blank to stop): ").strip()
            if not name:
                break
            fields[name] = getpass.getpass(f"Value for {name}: ")
    else:
        for name in field_names:
            fields[name] = getpass.getpass(f"{name}: ")

    upsert_credential(user_id=user_id, broker=broker, fields=fields)
    print(f"Uploaded encrypted credentials for user_id={user_id!r}, broker={broker!r}")


if __name__ == "__main__":
    main()
