"""Offline, verified snapshots for forward-only database migrations.

SQLite's backup API includes committed WAL pages. Run restore while the server
is stopped and point the application at the NEW database; never overwrite a
live database or its WAL files.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
from zipfile import ZipFile, ZIP_DEFLATED

# Version 10 also protects the persisted author-content format: v2 graph drafts
# must not be opened by older binaries that only understand v1 scenario JSON.
# Version 11 protects persisted capability plans and their typed decisions.
# Version 12 protects global challenge attempts from older reroll semantics.
# Version 14 protects scene-local transition waits and durable request receipts.
# Version 15 protects durable generation jobs and revocable worker leases.
# Version 16 protects validated narrative approvals and atomic graph receipts.
SCHEMA_VERSION = 16
BACKUP_FORMAT = "hexbound-backup-v1"
DATA_ROOT = Path(__file__).parent / "data"


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def database_version(path):
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)) as db:
        return db.execute("PRAGMA user_version").fetchone()[0]


def check_database_version(db):
    version = db.execute("PRAGMA user_version").fetchone()[0]
    if version < 0 or version > SCHEMA_VERSION:
        raise ValueError(f"Database schema {version} requires a newer server (supports {SCHEMA_VERSION})")
    return version


def backup_database(database, destination, data_root=DATA_ROOT):
    """Create one new archive containing a consistent DB and complete content.

    Destination creation is exclusive: existing backups cannot be overwritten.
    The manifest is a corruption detector, not a signature from a trusted party.
    """
    source, target = Path(database).resolve(), Path(destination).resolve()
    if not source.is_file():
        raise ValueError("Source database does not exist")
    if target.exists():
        raise FileExistsError(target)
    data_root = Path(data_root).resolve()
    source_manifest = data_root / "source-manifest.json"
    if not data_root.is_dir() or not source_manifest.is_file():
        raise ValueError("Complete source content and manifest are required for backup")
    sources = json.loads(source_manifest.read_text(encoding="utf-8"))
    required = [row["file"] for row in sources["files"]] + ["5e-database-LICENSE.md"]
    for name in required:
        content_path = (data_root / name).resolve()
        if not content_path.is_relative_to(data_root) or not content_path.is_file():
            raise ValueError(f"Missing required source content: {name}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="hexbound-backup-") as temporary:
        snapshot = Path(temporary) / "database.sqlite3"
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as src:
            with closing(sqlite3.connect(snapshot)) as dst:
                src.backup(dst)
                if dst.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("Database integrity check failed")
        files = {"database.sqlite3": snapshot.read_bytes()}
        for path in sorted(data_root.rglob("*")):
            if path.is_file():
                if path.is_symlink() or not path.resolve().is_relative_to(data_root):
                    raise ValueError("Source content contains an external reference")
                files["content/" + path.relative_to(data_root).as_posix()] = path.read_bytes()
        manifest = {"format": BACKUP_FORMAT, "schema_version": database_version(snapshot),
                    "files": {name: {"sha256": _digest(raw), "bytes": len(raw)} for name, raw in files.items()}}
        # Build the archive before exclusively publishing it at its final name.
        archive = Path(temporary) / "backup.zip"
        with ZipFile(archive, "w", ZIP_DEFLATED) as output:
            for name, raw in files.items():
                output.writestr(name, raw)
            output.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        owned = False
        try:
            with target.open("xb") as output:
                owned = True
                output.write(archive.read_bytes())
        except BaseException:
            if owned and target.exists():
                target.unlink()
            raise
    return manifest


def inspect_backup(archive):
    with ZipFile(archive) as backup:
        names = backup.namelist()
        if len(names) != len(set(names)):
            raise ValueError("Duplicate archive members")
        manifest = json.loads(backup.read("manifest.json"))
        if manifest.get("format") != BACKUP_FORMAT or "database.sqlite3" not in manifest.get("files", {}):
            raise ValueError("Unknown or incomplete backup format")
        if set(names) != set(manifest["files"]) | {"manifest.json"}:
            raise ValueError("Unexpected archive members")
        for name, expected in manifest["files"].items():
            parts = name.split("/")
            if name != "database.sqlite3" and (parts[0] != "content" or ".." in parts or "" in parts or "\\" in name or ":" in name):
                raise ValueError("Unsafe archive path")
            raw = backup.read(name)
            if len(raw) != expected["bytes"] or _digest(raw) != expected["sha256"]:
                raise ValueError(f"Backup checksum mismatch: {name}")
    return manifest


def restore_backup(archive, destination):
    """Restore to a NEW directory with database and the matching content bytes."""
    manifest = inspect_backup(archive)
    target = Path(destination).resolve()
    # Restore complete contents in a staging sibling, then publish by rename.
    if target.exists():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".hexbound-restore-", dir=target.parent) as temporary:
        stage = Path(temporary) / "restored"
        stage.mkdir()
        with ZipFile(archive) as backup:
            for name in manifest["files"]:
                path = stage / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(backup.read(name))
        with closing(sqlite3.connect(stage / "database.sqlite3")) as db:
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Restored database integrity check failed")
            if db.execute("PRAGMA user_version").fetchone()[0] != manifest["schema_version"]:
                raise ValueError("Backup schema marker mismatch")
        stage.rename(target)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    backup = sub.add_parser("backup")
    backup.add_argument("--database", required=True)
    backup.add_argument("--destination", required=True)
    restore = sub.add_parser("restore")
    restore.add_argument("--archive", required=True)
    restore.add_argument("--destination", required=True)
    args = parser.parse_args()
    if args.command == "backup":
        result = backup_database(args.database, args.destination)
    else:
        result = restore_backup(args.archive, args.destination)
    print(json.dumps({"format": result["format"], "schema_version": result["schema_version"],
                      "files_verified": len(result["files"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
