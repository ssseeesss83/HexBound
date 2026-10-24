"""A01/A02/A30: real SQLite/WAL backup, corruption and forward-version gates."""
import json
from copy import deepcopy
from pathlib import Path
import sqlite3
from zipfile import ZipFile

import pytest

from backend import compendium
from backend.maintenance import backup_database, restore_backup, SCHEMA_VERSION
from backend.store import Store


def without_scope_metadata(state):
    state = deepcopy(state)
    state.pop("text_scope", None)
    state.pop("action_revision", None)
    for event in state["events"]:
        event.pop("_audience", None)
        event.pop("_channel", None)
    return state


def test_legacy_migration_and_backup_preserve_room_and_receipts(tmp_path):
    fixture = json.loads((Path(__file__).parent / "fixtures/legacy_room_v06.json").read_text(encoding="utf-8"))
    path = tmp_path / "legacy.sqlite3"
    initial = Store(str(path))
    with initial.connect() as db:
        db.execute("INSERT INTO rooms VALUES(?,?,?,?)", (fixture["id"], fixture["invite_code"], fixture["version"], json.dumps(fixture)))
        db.execute("INSERT INTO commands VALUES(?,?,?,?)", (fixture["id"], "p0", "settled-command", '{"replayed":true}'))
        db.execute("PRAGMA user_version=0")
    migrated = Store(str(path))
    assert without_scope_metadata(migrated.get(fixture["id"])) == fixture
    backups = list((tmp_path / "backups").glob("*.zip"))
    assert len(backups) == 1
    restore_backup(backups[0], tmp_path / "restored")
    restored = Store(str(tmp_path / "restored/database.sqlite3"))
    assert without_scope_metadata(restored.get(fixture["id"])) == fixture
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


@pytest.mark.parametrize("unsupported", [-1, SCHEMA_VERSION + 1])
def test_future_schema_refused_before_writes(tmp_path, unsupported):
    path = tmp_path / "future.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute(f"PRAGMA user_version={unsupported}")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="newer server"):
        Store(str(path))
    assert path.read_bytes() == before


def test_missing_source_cannot_create_incomplete_backup(tmp_path):
    database = tmp_path / "db.sqlite3"
    Store(str(database))
    archive = tmp_path / "must-not-exist.zip"
    with pytest.raises(ValueError, match="source content"):
        backup_database(database, archive, data_root=tmp_path / "missing")
    assert not archive.exists()


def test_actual_pre_account_table_gets_column_without_changing_state(tmp_path):
    path = tmp_path / "pre-account.sqlite3"
    fixture = json.loads((Path(__file__).parent / "fixtures/legacy_room_v06.json").read_text(encoding="utf-8"))
    db = sqlite3.connect(path)
    try:
        db.executescript("""
            CREATE TABLE rooms (id TEXT PRIMARY KEY, invite_code TEXT NOT NULL UNIQUE, version INTEGER NOT NULL, state TEXT NOT NULL);
            CREATE TABLE members (id TEXT PRIMARY KEY, room_id TEXT NOT NULL REFERENCES rooms(id), token_hash TEXT NOT NULL UNIQUE);
            CREATE TABLE commands (room_id TEXT, member_id TEXT, command_id TEXT, response TEXT, PRIMARY KEY(room_id,member_id,command_id));
        """)
        db.execute("INSERT INTO rooms VALUES(?,?,?,?)", (fixture["id"], fixture["invite_code"], fixture["version"], json.dumps(fixture)))
        db.execute("INSERT INTO members VALUES('p0',?,'synthetic-token-hash')", (fixture["id"],))
        db.execute("INSERT INTO commands VALUES(?,'p0','old-command','{\"replayed\":true}')", (fixture["id"],))
        db.commit()
        assert "user_id" not in {row[1] for row in db.execute("PRAGMA table_info(members)")}
    finally:
        db.close()
    store = Store(str(path))
    assert without_scope_metadata(store.get(fixture["id"])) == fixture
    assert store.prior_command(fixture["id"], "p0", "old-command") == {"replayed": True}
    with store.connect() as db:
        assert "user_id" in {row["name"] for row in db.execute("PRAGMA table_info(members)")}
        assert db.execute("SELECT token_hash FROM members WHERE id='p0'").fetchone()[0] == "synthetic-token-hash"
    assert len(list((tmp_path / "backups").glob("*.zip"))) == 1


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
