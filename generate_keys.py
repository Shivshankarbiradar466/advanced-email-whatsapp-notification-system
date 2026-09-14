from security import generate_fernet_key
import secrets

print("Copy these two lines into .env:")
print("FERNET_KEY=" + generate_fernet_key())
print("FLASK_SECRET_KEY=" + secrets.token_hex(32))
