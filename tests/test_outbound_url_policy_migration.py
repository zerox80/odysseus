"""The outbound-URL-policy migration must only fail-close API Chat sessions.

An earlier revision added the column with DEFAULT 'legacy-api-unknown', which
stamped every pre-existing session — so after the upgrade, API-token resume
(routes/webhook_routes.py) refused normal sessions too, not just the old
``API Chat`` rows whose endpoint provenance is genuinely unknown.
"""

import sqlite3

import core.database as cdb


def _policies(db_path):
    conn = sqlite3.connect(db_path)
    try:
        return dict(conn.execute("SELECT id, outbound_url_policy FROM sessions"))
    finally:
        conn.close()


def test_migration_marks_only_api_chat_sessions_legacy(tmp_path, monkeypatch):
    db_path = tmp_path / "app.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, name TEXT NOT NULL)")
    conn.executemany(
        "INSERT INTO sessions (id, name) VALUES (?, ?)",
        [
            ("normal", "My research chat"),
            ("api", "API Chat"),
            ("renamed", "API Chat 2"),
        ],
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(cdb, "DATABASE_URL", f"sqlite:///{db_path}")
    cdb._migrate_add_outbound_url_policy()

    policies = _policies(db_path)
    assert policies["normal"] == "configured"
    assert policies["api"] == "legacy-api-unknown"
    # Only the exact legacy auto-created name is fail-closed.
    assert policies["renamed"] == "configured"


def test_migration_is_idempotent_and_preserves_existing_values(tmp_path, monkeypatch):
    db_path = tmp_path / "app.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, name TEXT NOT NULL)")
    conn.execute("INSERT INTO sessions (id, name) VALUES ('api', 'API Chat')")
    conn.commit()
    conn.close()

    monkeypatch.setattr(cdb, "DATABASE_URL", f"sqlite:///{db_path}")
    cdb._migrate_add_outbound_url_policy()

    # A row re-validated after the migration must keep its upgraded policy.
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE sessions SET outbound_url_policy = 'configured' WHERE id = 'api'")
    conn.commit()
    conn.close()

    cdb._migrate_add_outbound_url_policy()
    assert _policies(db_path)["api"] == "configured"
