#!/usr/bin/env python
"""Verify, and optionally restore, an archive written by backup_encrypted.py.

The archive is decrypted to a temporary directory. Verification happens in three layers:
  1. header: magic and version must match (a file that is not an archive fails here);
  2. AES-256-GCM: every frame must authenticate, including the final-frame marker, so a
     flipped byte, a wrong passphrase or a truncated archive all fail before any file is trusted;
  3. manifest.json: every member must be present with the listed size and sha256, and no
     member may be unlisted.

Nothing is copied into a destination until all three pass. The databases are NOT restored
into live services by this script: it places the verified files, and the database dumps
(db/*.dump, db/*.sql, graph/*.nq) are restored with pg_restore / mysql / the GraphDB import
tools by hand, deliberately, against a stopped service.

Usage::

    python scripts/restore_encrypted.py <archive.enc> --verify-only
    python scripts/restore_encrypted.py <archive.enc> --dest <empty-or-new-dir>

Exit codes: 0 verified · 1 unexpected · 2 wrong passphrase or tampered (GCM) ·
3 not an archive or truncated · 4 manifest mismatch · 5 destination not empty.
"""

import argparse
import hashlib
import json
import re
import shutil
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from _backup_format import ArchiveAuthError, ArchiveFormatError, EncryptedReader  # noqa: E402

FORMAT_NAME = "ontosage-encrypted-backup"
SUPPORTED_MANIFEST_VERSION = 1
_COPY_BLOCK = 1024 * 1024


class ManifestMismatch(Exception):
    """The decrypted members do not match manifest.json."""

    def __init__(self, problems: List[str]) -> None:
        super().__init__(f"{len(problems)} manifest problem(s)")
        self.problems = problems


def safe_member_path(name: str) -> PurePosixPath:
    """Reject absolute paths, traversal and Windows drive prefixes before writing anything."""
    if not name or "\\" in name or re.match(r"^[A-Za-z]:", name) or name.startswith("/"):
        raise ArchiveFormatError(f"unsafe member name: {name!r}")
    path = PurePosixPath(name)
    if ".." in path.parts or path.is_absolute():
        raise ArchiveFormatError(f"unsafe member name: {name!r}")
    return path


def extract_and_verify(archive: Path, passphrase: str, extract_dir: Path) -> dict:
    """Decrypt into extract_dir and verify against the manifest. Returns the manifest."""
    extracted: Dict[str, dict] = {}
    manifest_bytes: Optional[bytes] = None
    with open(archive, "rb") as fh:
        reader = EncryptedReader(fh, passphrase)
        try:
            with tarfile.open(fileobj=reader, mode="r|gz") as tar:
                for member in tar:
                    if member.isdir():
                        continue
                    if not member.isfile():
                        raise ArchiveFormatError(f"non-regular member refused: {member.name}")
                    if member.name == "manifest.json":
                        handle = tar.extractfile(member)
                        manifest_bytes = handle.read() if handle else b""
                        continue
                    rel = safe_member_path(member.name)
                    target = extract_dir.joinpath(*rel.parts)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    digest = hashlib.sha256()
                    size = 0
                    handle = tar.extractfile(member)
                    with open(target, "wb") as dst:
                        while handle is not None:
                            block = handle.read(_COPY_BLOCK)
                            if not block:
                                break
                            digest.update(block)
                            size += len(block)
                            dst.write(block)
                    extracted[member.name] = {"size": size, "sha256": digest.hexdigest()}
        except tarfile.ReadError as exc:
            raise ArchiveFormatError(f"archive is truncated or not a tar stream: {exc}") from exc
        # Authenticate the remainder: the tar end-of-archive marker can arrive before the
        # final GCM frame, and a truncated tail must still fail.
        reader.drain()

    if manifest_bytes is None:
        raise ArchiveFormatError("archive has no manifest.json")
    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ArchiveFormatError("manifest.json is not valid JSON") from exc
    if manifest.get("format") != FORMAT_NAME:
        raise ArchiveFormatError("manifest format name does not match")
    if manifest.get("format_version") != SUPPORTED_MANIFEST_VERSION:
        raise ArchiveFormatError(f"unsupported manifest version {manifest.get('format_version')}")

    problems: List[str] = []
    listed = set()
    for entry in manifest.get("members", []):
        name = entry.get("name", "")
        listed.add(name)
        got = extracted.get(name)
        if got is None:
            problems.append(f"missing member: {name}")
        elif got["size"] != entry.get("size"):
            problems.append(f"size mismatch: {name} ({got['size']} != {entry.get('size')})")
        elif got["sha256"] != entry.get("sha256"):
            problems.append(f"sha256 mismatch: {name}")
    for name in extracted:
        if name not in listed:
            problems.append(f"unlisted member: {name}")
    if problems:
        raise ManifestMismatch(problems)
    return manifest


def _fmt_bytes(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Verify or restore an OntoSage backup archive.")
    parser.add_argument("archive", type=Path)
    parser.add_argument("--verify-only", action="store_true", help="verify and discard")
    parser.add_argument("--dest", type=Path, help="directory to place verified files in")
    args = parser.parse_args(argv)
    if not args.verify_only and args.dest is None:
        parser.error("give --dest <dir> to restore, or --verify-only")
    if not args.archive.is_file():
        print(f"error: no such archive: {args.archive}", file=sys.stderr)
        return 1

    from _backup_secret import PassphraseError, get_passphrase

    try:
        passphrase = get_passphrase(creating=False)
    except PassphraseError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.dest is not None and args.dest.exists() and any(args.dest.iterdir()):
        print(f"error: destination is not empty: {args.dest}", file=sys.stderr)
        return 5

    work = Path(tempfile.mkdtemp(prefix="ontosage-restore-"))
    try:
        manifest = extract_and_verify(args.archive, passphrase, work)
    except ArchiveAuthError as exc:
        shutil.rmtree(work, ignore_errors=True)
        print(f"FAILED: {exc}", file=sys.stderr)
        return 2
    except ArchiveFormatError as exc:
        shutil.rmtree(work, ignore_errors=True)
        print(f"FAILED: {exc}", file=sys.stderr)
        return 3
    except ManifestMismatch as exc:
        shutil.rmtree(work, ignore_errors=True)
        print("FAILED: manifest verification:", file=sys.stderr)
        for line in exc.problems:
            print(f"  - {line}", file=sys.stderr)
        return 4
    except Exception as exc:
        shutil.rmtree(work, ignore_errors=True)
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    members = manifest.get("members", [])
    total = sum(m.get("size", 0) for m in members)
    print(
        f"VERIFIED: {len(members)} member(s), {_fmt_bytes(total)}, building "
        f"{manifest.get('building_id')}, created {manifest.get('created_utc')}."
    )
    for skip in manifest.get("skipped", []):
        print(f"  NOTE: the backup did not include {skip.get('source')}: {skip.get('reason')}")

    try:
        if args.verify_only:
            return 0
        shutil.copytree(work, args.dest, dirs_exist_ok=True)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print(f"Restored verified files to {args.dest}. Restore databases by hand (see docstring).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
