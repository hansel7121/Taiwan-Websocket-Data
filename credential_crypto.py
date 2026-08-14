import os
import json
from dotenv import load_dotenv
from cryptography.fernet import Fernet

load_dotenv()

_fernet = Fernet(os.environ["CRYPTO_KEY"].encode())


def encrypt(fields: dict) -> str:
    return _fernet.encrypt(json.dumps(fields).encode()).decode()


def decrypt(blob: str) -> dict:
    return json.loads(_fernet.decrypt(blob.encode()).decode())
