"""Generate a VAPID key pair for web push. Put the output in .env (or your host's env vars)."""
from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid01
from py_vapid.utils import b64urlencode

v = Vapid01()
v.generate_keys()
priv = b64urlencode(v.private_key.private_numbers().private_value.to_bytes(32, "big"))
pub = b64urlencode(v.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint))
print(f"VAPID_PUBLIC_KEY={pub}\nVAPID_PRIVATE_KEY={priv}")
