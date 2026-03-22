from __future__ import annotations

import base64
import json
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


class NodeKeyStore:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self.private_key = ""
        self.public_key = ""

    def ensure_keys(self) -> None:
        if self._path.exists():
            self._load()
            if self.private_key and self.public_key:
                return
        self._generate()

    def _load(self) -> None:
        try:
            payload = json.loads(self._path.read_text())
        except (json.JSONDecodeError, OSError):
            payload = {}
        self.private_key = str(payload.get("private_key", "")).strip()
        self.public_key = str(payload.get("public_key", "")).strip()

    def _generate(self) -> None:
        private_key = Ed25519PrivateKey.generate()
        public_key = private_key.public_key()
        private_bytes = private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        public_bytes = public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        self.private_key = private_bytes.hex()
        self.public_key = public_bytes.hex()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps({"private_key": self.private_key, "public_key": self.public_key}, indent=2))


def sign_payload_hash(private_key_hex: str, payload_hash: str) -> str:
    private_key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(private_key_hex))
    signature = private_key.sign(payload_hash.encode())
    return base64.b64encode(signature).decode()


def verify_payload_signature(public_key_hex: str, payload_hash: str, signature: str) -> bool:
    try:
        public_key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex))
        public_key.verify(base64.b64decode(signature.encode()), payload_hash.encode())
        return True
    except Exception:
        return False
