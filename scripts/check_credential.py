"""Pull and decrypt a credential row to confirm an upsert worked.

Decryption happens locally with your own CRYPTO_KEY; nothing is sent anywhere.
Requires SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, and CRYPTO_KEY in your .env.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from credential_store import get_credential


def main():
    broker = input("Broker (e.g. kgi): ").strip()
    user_id = input("Account label (e.g. friend1): ").strip()

    creds = get_credential(user_id=user_id, broker=broker)
    if creds is None:
        print(f"No row found for user_id={user_id!r}, broker={broker!r}")
        return

    print(f"Found credentials for user_id={user_id!r}, broker={broker!r}:")
    for key, value in creds.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
