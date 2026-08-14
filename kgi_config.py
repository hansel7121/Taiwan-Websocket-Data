import os
from dotenv import load_dotenv

from credential_store import get_credential

load_dotenv()

KGI_ACCOUNT_LABEL = os.environ["KGI_ACCOUNT_LABEL"]

_creds = get_credential(user_id=KGI_ACCOUNT_LABEL, broker="kgi")
if _creds is None:
    raise RuntimeError(
        f"No credentials found for user_id={KGI_ACCOUNT_LABEL!r}, broker='kgi' — "
        f"ask your friend to run scripts/upsert_credential.py"
    )

TOKEN = _creds["token"]
SID = _creds["sid"]
USER_ID = _creds["user_id"]
PASSWORD = _creds["password"]
BROKER_ID = _creds["broker_id"]
ACCOUNT = _creds["account"]
