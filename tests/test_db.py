from photomanager.db import connect


def test_schema_creates_expected_tables(tmp_path):
    conn = connect(tmp_path / "test.sqlite3")
    tables = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    assert {"volumes", "places", "people", "events", "files", "faces"} <= tables
    conn.close()


def test_schema_is_idempotent(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    connect(db_path).close()
    connect(db_path).close()
