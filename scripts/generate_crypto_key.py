"""Generate a new CRYPTO_KEY. Run once, share the output over a secure channel
(not chat, not git), and both sides put it in their local .env as CRYPTO_KEY.
"""
from cryptography.fernet import Fernet

if __name__ == "__main__":
    print(Fernet.generate_key().decode())
