import hashlib
import base64

hashed_pass64 = "AI+8vL8h2PO9GNc4BXWoe9eaL3jw5LIL2Y3+1+f5rQfB4XjOlNoZ0bSxtNAGkcM5kQ=="

clear_pass = "profesional"

salt = base64.b64decode(hashed_pass64)[1:17]

def password_hash(clear_pass, salt):
    dst = salt + clear_pass
    return base64.b64encode(hashlib.sha1(dst).digest())
