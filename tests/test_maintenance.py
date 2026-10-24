"""A01/A02/A30: real SQLite/WAL backup, corruption and forward-version gates."""
import json
from pathlib import Path
import sqlite3
from zipfile import ZipFile

import pytest

from backend import compendium
from backend.maintenance import backup_database, restore_backup, SCHEMA_VERSION
from backend.store import Store


def test_legacy_migration_and_backup_preserve_room_and_receipts(tmp_path):
    fixture = json.loads((Path(__file__).parent / "fixtures/legacy_room_v06.json").read_text(encoding="utf-8"))
    path = tmp_path / "legacy.sqlite3"
    initial = Store(str(path))
    with initial.connect() as db:
        db.execute("INSERT INTO rooms VALUES(?,?,?,?)", (fixture["id"], fixture["invite_code"], fixture["version"], json.dumps(fixture)))
        db.execute("INSERT INTO commands VALUES(?,?,?,?)", (fixture["id"], "p0", "settled-command", '{"replayed":true}'))
        db.execute("PRAGMA user_version=0")
    migrated = Store(str(path))
    assert migrated.get(fixture["id"]) == fixture
    backups = list((tmp_path / "backups").glob("*.zip"))
    assert len(backups) == 1
    restore_backup(backups[0], tmp_path / "restored")
    restored = Store(str(tmp_path / "restored/database.sqlite3"))
    assert restored.get(fixture["id"]) == fixture
    assert restored.prior_command(fixture["id"], "p0", "settled-command") == {"replayed": True}
    # Reopening a current schema does not migrate or make another backup.
    Store(str(path))
    assert len(list((tmp_path / "backups").glob("*.zip"))) == 1


def test_backup_includes_wal_and_content_and_restore_is_exclusive(tmp_path):
    path = tmp_path / "db.sqlite3"
    with sqlite3.connect(path) as live:
        live.execute("PRAGMA journal_mode=WAL")
        live.execute("CREATE TABLE payload (value TEXT)")
        live.execute("INSERT INTO payload VALUES ('committed in WAL')")
        live.commit()
        archive = tmp_path / "snapshot.zip"
        result = backup_database(path, archive)
        assert "content/source-manifest.json" in result["files"]
        with pytest.raises(FileExistsError):
            backup_database(path, archive)
    restore_backup(archive, tmp_path / "recovery")
    with sqlite3.connect(tmp_path / "recovery/database.sqlite3") as recovered:
        assert recovered.execute("SELECT value FROM payload").fetchone()[0] == "committed in WAL"
    with pytest.raises(FileExistsError):
        restore_backup(archive, tmp_path / "recovery")
    assert (tmp_path / "recovery/content/source-manifest.json").read_bytes() == (compendium.DATA_DIR / "source-manifest.json").read_bytes()


def test_corrupt_archive_never_publishes_restore(tmp_path):
    path = tmp_path / "db.sqlite3"
    Store(str(path))
    archive = tmp_path / "good.zip"
    backup_database(path, archive)
    broken = tmp_path / "broken.zip"
    with ZipFile(archive) as src, ZipFile(broken, "w") as dst:
        for name in src.namelist():
            dst.writestr(name, b"corrupt" if name == "database.sqlite3" else src.read(name))
    with pytest.raises(ValueError, match="checksum"):
        restore_backup(broken, tmp_path / "should-not-exist")
    assert not (tmp_path / "should-not-exist").exists()


def test_future_schema_refused_before_writes(tmp_path):
    path = tmp_path / "future.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute(f"PRAGMA user_version={SCHEMA_VERSION + 1}")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="newer server"):
        Store(str(path))
    assert path.read_bytes() == before


@pytest.mark.parametrize("change", ["byte", "missing", "count", "invalid", "license"])
def test_source_audit_detects_corruption(tmp_path, monkeypatch, change):
    import shutil
    shutil.copytree(compendium.DATA_DIR, tmp_path / "source")
    monkeypatch.setattr(compendium, "DATA_DIR", tmp_path / "source")
    row = compendium.SOURCE["files"][0]
    path = compendium.DATA_DIR / row["file"]
    if change == "byte":
        path.write_bytes(path.read_bytes() + b" ")
    elif change == "missing":
        path.unlink()
    elif change == "count":
        path.write_text("[]", encoding="utf-8")
    elif change == "invalid":
        path.write_bytes(b"not json")
    else:
        (compendium.DATA_DIR / "5e-database-LICENSE.md").unlink()
    assert compendium.verify_source_integrity()
