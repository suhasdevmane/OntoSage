"""Encrypted archive format shared by backup_encrypted.py and restore_encrypted.py.

Layout (integers big-endian)::

    header : MAGIC(7) | VERSION(1) | SALT(16) | NONCE_PREFIX(8)     = 32 bytes
    frames : repeated  FLAG(1) | LEN(4) | CIPHERTEXT(LEN)
             FLAG = 1 marks the final frame and nothing else may follow it.
             CIPHERTEXT = AES-256-GCM(chunk), nonce = NONCE_PREFIX | counter(4),
             AAD = header | FLAG, so editing the header or a flag fails the tag too.
    plaintext = one gzip-compressed tar stream (see backup_encrypted.py).

The key is scrypt(passphrase, SALT). The format is chunked so a multi-gigabyte dump is
never held in memory, and the FLAG byte makes truncation detectable: a stream that ends
without a final frame is rejected, not silently accepted as a shorter archive.
"""

import os
import struct
from typing import BinaryIO

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAGIC = b"OSBKENC"
VERSION = 1
SALT_LEN = 16
NONCE_PREFIX_LEN = 8
HEADER_LEN = len(MAGIC) + 1 + SALT_LEN + NONCE_PREFIX_LEN
CHUNK_SIZE = 1024 * 1024
TAG_LEN = 16
SCRYPT_N = 2**15
SCRYPT_R = 8
SCRYPT_P = 1
_FRAME_HDR = struct.Struct(">BI")


class ArchiveFormatError(Exception):
    """The file is not an OntoSage archive, is an unsupported version, or is truncated."""


class ArchiveAuthError(Exception):
    """AES-GCM authentication failed: the passphrase is wrong or the archive was altered."""


def derive_key(passphrase: str, salt: bytes) -> bytes:
    """Derive the 256-bit AES key from the passphrase and the archive's salt."""
    if not passphrase:
        raise ValueError("passphrase must not be empty")
    kdf = Scrypt(salt=salt, length=32, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P)
    return kdf.derive(passphrase.encode("utf-8"))


def _read_exact(fileobj: BinaryIO, n: int) -> bytes:
    """Read exactly n bytes or raise ArchiveFormatError on early end of file."""
    out = bytearray()
    while len(out) < n:
        piece = fileobj.read(n - len(out))
        if not piece:
            raise ArchiveFormatError("archive is truncated")
        out += piece
    return bytes(out)


class EncryptedWriter:
    """Write-only stream: call write() with plaintext, then close() to emit the final frame."""

    def __init__(self, fileobj: BinaryIO, passphrase: str) -> None:
        self._f = fileobj
        salt = os.urandom(SALT_LEN)
        self._prefix = os.urandom(NONCE_PREFIX_LEN)
        self._header = MAGIC + bytes([VERSION]) + salt + self._prefix
        self._aead = AESGCM(derive_key(passphrase, salt))
        self._counter = 0
        self._buf = bytearray()
        self._closed = False
        self._f.write(self._header)

    def write(self, data: bytes) -> int:
        """Buffer plaintext, emitting a non-final frame for every full chunk."""
        if self._closed:
            raise ValueError("write to closed EncryptedWriter")
        self._buf += data
        while len(self._buf) > CHUNK_SIZE:
            chunk = bytes(self._buf[:CHUNK_SIZE])
            del self._buf[:CHUNK_SIZE]
            self._emit(chunk, final=False)
        return len(data)

    def flush(self) -> None:
        """Required by tarfile's stream mode; frames are only emitted on full chunks."""

    def close(self) -> None:
        """Emit the final frame (possibly empty). Does not close the underlying file."""
        if self._closed:
            return
        self._emit(bytes(self._buf), final=True)
        self._buf = bytearray()
        self._closed = True

    def _emit(self, chunk: bytes, final: bool) -> None:
        if self._counter >= 2**32:
            raise ArchiveFormatError("archive exceeds the format's frame limit")
        flag = 1 if final else 0
        nonce = self._prefix + struct.pack(">I", self._counter)
        self._counter += 1
        ciphertext = self._aead.encrypt(nonce, chunk, self._header + bytes([flag]))
        self._f.write(_FRAME_HDR.pack(flag, len(ciphertext)) + ciphertext)

    def __enter__(self) -> "EncryptedWriter":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is None:
            self.close()


class EncryptedReader:
    """Read-only stream of decrypted plaintext. Every frame is authenticated before use."""

    def __init__(self, fileobj: BinaryIO, passphrase: str) -> None:
        self._f = fileobj
        header = _read_exact(fileobj, HEADER_LEN)
        if header[: len(MAGIC)] != MAGIC:
            raise ArchiveFormatError("not an OntoSage encrypted archive (bad magic)")
        version = header[len(MAGIC)]
        if version != VERSION:
            raise ArchiveFormatError(f"unsupported archive version {version}")
        salt = header[len(MAGIC) + 1 : len(MAGIC) + 1 + SALT_LEN]
        self._header = header
        self._prefix = header[HEADER_LEN - NONCE_PREFIX_LEN :]
        self._aead = AESGCM(derive_key(passphrase, salt))
        self._counter = 0
        self._buf = b""
        self._pos = 0
        self._done = False

    def _next_frame(self) -> None:
        flag, length = _FRAME_HDR.unpack(_read_exact(self._f, _FRAME_HDR.size))
        if flag not in (0, 1) or length > CHUNK_SIZE + TAG_LEN:
            raise ArchiveFormatError("corrupt frame header")
        ciphertext = _read_exact(self._f, length)
        nonce = self._prefix + struct.pack(">I", self._counter)
        self._counter += 1
        try:
            plaintext = self._aead.decrypt(nonce, ciphertext, self._header + bytes([flag]))
        except InvalidTag as exc:
            raise ArchiveAuthError(
                "authentication failed: wrong passphrase, or the archive was modified"
            ) from exc
        self._buf = plaintext
        self._pos = 0
        if flag == 1:
            self._done = True
            if self._f.read(1):
                raise ArchiveFormatError("data found after the final frame")

    def read(self, size: int = -1) -> bytes:
        """Return up to size plaintext bytes (all remaining when size < 0)."""
        out = []
        remaining = None if size is None or size < 0 else size
        while remaining is None or remaining > 0:
            avail = len(self._buf) - self._pos
            if avail == 0:
                if self._done:
                    break
                self._next_frame()
                continue
            take = avail if remaining is None else min(avail, remaining)
            out.append(self._buf[self._pos : self._pos + take])
            self._pos += take
            if remaining is not None:
                remaining -= take
        return b"".join(out)

    def readable(self) -> bool:
        return True

    def drain(self) -> None:
        """Read to the end so every frame, and the final-frame marker, is authenticated."""
        while self.read(CHUNK_SIZE):
            pass
