import os
from datetime import datetime, timezone
from dotenv import load_dotenv
import requests

import credential_crypto as crypto

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_ROLE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

TABLE = "credentials"

_HEADERS = {
    "apikey": SUPABASE_SERVICE_ROLE_KEY,
    "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
    "Content-Type": "application/json",
}

_DEFAULT_TIER = {
    "kgi": (None, None),
}


def upsert_credential(user_id, broker, fields, symbols_per_connection=None, connections=None):
    """Encrypt `fields` and write the user's row for `broker`."""
    default_symbols, default_connections = _DEFAULT_TIER.get(broker, (None, None))
    if symbols_per_connection is None:
        symbols_per_connection = default_symbols
    if connections is None:
        connections = default_connections

    row = {
        "user_id": user_id,
        "broker": broker,
        "encrypted_fields": crypto.encrypt(fields),
        "symbols_per_connection": symbols_per_connection,
        "connections": connections,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    resp = requests.post(
        f"{SUPABASE_URL}/rest/v1/{TABLE}",
        headers={**_HEADERS, "Prefer": "resolution=merge-duplicates"},
        params={"on_conflict": "user_id,broker"},
        json=row,
        timeout=10,
    )
    resp.raise_for_status()


def get_credential(user_id, broker):
    """Decrypted credential fields plus the capacity tier columns, or None."""
    resp = requests.get(
        f"{SUPABASE_URL}/rest/v1/{TABLE}",
        headers=_HEADERS,
        params={
            "user_id": f"eq.{user_id}",
            "broker": f"eq.{broker}",
            "select": "*",
            "limit": 1,
        },
        timeout=10,
    )
    resp.raise_for_status()
    rows = resp.json()
    if not rows:
        return None
    row = rows[0]
    return {
        **crypto.decrypt(row["encrypted_fields"]),
        "symbols_per_connection": row.get("symbols_per_connection"),
        "connections": row.get("connections"),
    }
