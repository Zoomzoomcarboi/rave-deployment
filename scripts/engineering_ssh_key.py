#!/usr/bin/env python3
"""Validate one externally supplied OpenSSH ED25519 engineering public key."""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

KEY_TYPE = b"ssh-ed25519"
MAX_INPUT_BYTES = 1024
MAX_COMMENT_LENGTH = 128


class PublicKeyError(ValueError):
    pass


@dataclass(frozen=True)
class EngineeringPublicKey:
    normalized: str
    fingerprint: str


def parse_public_key(content: str) -> EngineeringPublicKey:
    if len(content.encode("utf-8")) > MAX_INPUT_BYTES:
        raise PublicKeyError("engineering public key input is too large")
    lines = content.splitlines()
    if len(lines) != 1:
        raise PublicKeyError("engineering public key input must contain exactly one line")
    fields = lines[0].strip().split(maxsplit=2)
    if len(fields) not in {2, 3} or fields[0] != KEY_TYPE.decode():
        raise PublicKeyError("engineering public key must be OpenSSH ssh-ed25519")
    try:
        blob = base64.b64decode(fields[1], validate=True)
    except (ValueError, binascii.Error) as error:
        raise PublicKeyError("engineering public key base64 is invalid") from error
    key_type, offset = _read_field(blob, 0)
    key_material, offset = _read_field(blob, offset)
    if key_type != KEY_TYPE or len(key_material) != 32 or offset != len(blob):
        raise PublicKeyError("engineering public key payload is not ED25519")
    comment = fields[2] if len(fields) == 3 else ""
    if len(comment) > MAX_COMMENT_LENGTH or any(
        ord(character) < 0x20 or ord(character) == 0x7F for character in comment
    ):
        raise PublicKeyError("engineering public key comment is invalid")
    normalized = f"ssh-ed25519 {base64.b64encode(blob).decode()}"
    if comment:
        normalized = f"{normalized} {comment}"
    digest = base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip("=")
    return EngineeringPublicKey(normalized=normalized, fingerprint=f"SHA256:{digest}")


def _read_field(blob: bytes, offset: int) -> tuple[bytes, int]:
    if offset + 4 > len(blob):
        raise PublicKeyError("engineering public key payload is truncated")
    length = struct.unpack(">I", blob[offset : offset + 4])[0]
    start = offset + 4
    end = start + length
    if end > len(blob):
        raise PublicKeyError("engineering public key payload is truncated")
    return blob[start:end], end


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", type=Path)
    source.add_argument("--stdin", action="store_true")
    parser.add_argument("--fingerprint", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        content = sys.stdin.read(MAX_INPUT_BYTES + 1) if args.stdin else args.input.read_text()
        key = parse_public_key(content)
    except (OSError, UnicodeError, PublicKeyError) as error:
        print(f"invalid engineering public key: {error}", file=sys.stderr)
        return 2
    print(key.fingerprint if args.fingerprint else key.normalized)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
