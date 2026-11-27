"""Generate a VAPID key pair for Web Push (07 L2) and write it to api/.env.local (gitignored).

    uv run python -m scripts.gen_vapid            # appends VAPID_* to api/.env.local
    uv run python -m scripts.gen_vapid --print-public

Nothing secret is printed: the private key goes only into the file. Copy it into Vercel from there.
"""

import base64
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

ENV = Path(__file__).resolve().parents[1] / ".env.local"


def b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def main() -> None:
    existing = ENV.read_text(encoding="utf-8") if ENV.exists() else ""
    if "VAPID_PRIVATE_KEY=" in existing:
        sys.exit(f"{ENV} already has a VAPID key; remove it first to make a new pair")
    key = ec.generate_private_key(ec.SECP256R1())
    private = b64(key.private_numbers().private_value.to_bytes(32, "big"))
    public = b64(
        key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
    )
    sep = "" if not existing or existing.endswith("\n") else "\n"
    ENV.write_text(
        f"{existing}{sep}VAPID_PUBLIC_KEY={public}\nVAPID_PRIVATE_KEY={private}\n", encoding="utf-8"
    )
    print(f"wrote VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY to {ENV}")
    if "--print-public" in sys.argv:
        print(f"VAPID_PUBLIC_KEY={public}")


if __name__ == "__main__":
    main()
