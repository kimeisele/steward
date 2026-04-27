from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

logger = logging.getLogger("STEWARD.FEDERATION_CRYPTO")


def derive_node_id(public_key_hex: str, length: int = 16) -> str:
    digest = hashlib.sha256(str(public_key_hex).encode()).hexdigest()
    return f"ag_{digest[:length]}"


def _load_from_hex_or_json(text: str) -> tuple[str, str, str] | None:
    """Try parsing `text` as JSON-blob or raw 32-byte hex. Returns
    (priv_hex, pub_hex, node_id) or None on failure."""
    text = (text or "").strip()
    if not text:
        return None
    # JSON blob
    try:
        blob = json.loads(text)
        if isinstance(blob, dict):
            priv = str(blob.get("private_key", "")).strip()
            pub = str(blob.get("public_key", "")).strip()
            if priv and pub:
                node_id = str(blob.get("node_id") or "").strip() or derive_node_id(pub)
                return priv, pub, node_id
    except (json.JSONDecodeError, ValueError):
        pass
    # Raw hex (32 bytes)
    try:
        raw = bytes.fromhex(text)
        if len(raw) == 32:
            sk = Ed25519PrivateKey.from_private_bytes(raw)
            pub = sk.public_key().public_bytes(
                serialization.Encoding.Raw, serialization.PublicFormat.Raw,
            ).hex()
            return raw.hex(), pub, derive_node_id(pub)
    except (ValueError, TypeError):
        pass
    return None


class NodeKeyStore:
    """Persistent Ed25519 key holder.

    Resolution order (highest priority first):
      1. NODE_PRIVATE_KEY environment variable (raw 32-byte hex OR JSON blob)
      2. The file at `path` (legacy fallback)
      3. Generate fresh ephemeral keypair (last resort, logs WARNING)

    The env-first policy means a node's identity is governed by the
    GitHub-Actions secret (Genesis-Hook target), and rotating the secret
    rotates the identity — without leaving a stale key on disk that
    could be re-leaked by a misconfigured workflow.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self.private_key = ""
        self.public_key = ""
        self.node_id = ""

    def ensure_keys(self) -> None:
        # 1. Env wins
        env_text = os.environ.get("NODE_PRIVATE_KEY", "")
        loaded = _load_from_hex_or_json(env_text) if env_text else None
        if loaded:
            self.private_key, self.public_key, self.node_id = loaded
            logger.info(
                "nodekeystore: loaded identity from NODE_PRIVATE_KEY env (node_id=%s)",
                self.node_id,
            )
            return
        # 2. File fallback
        if self._path.exists():
            self._load()
            if self.private_key and self.public_key:
                logger.info(
                    "nodekeystore: loaded from file %s (env unset) — node_id=%s",
                    self._path, self.node_id,
                )
                return
        # 3. Last resort
        logger.warning(
            "nodekeystore: env unset and %s missing/invalid — generating ephemeral keypair",
            self._path,
        )
        self._generate()

    def _load(self) -> None:
        try:
            text = self._path.read_text()
        except OSError:
            return
        loaded = _load_from_hex_or_json(text)
        if loaded:
            self.private_key, self.public_key, self.node_id = loaded

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
        self.node_id = derive_node_id(self.public_key)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(
                {"private_key": self.private_key, "public_key": self.public_key, "node_id": self.node_id},
                indent=2,
            )
        )


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
