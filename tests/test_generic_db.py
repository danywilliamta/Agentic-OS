"""Unit tests for agent_harness.tools.generic_db — uses a real temp SQLite DB
rather than mocking SQLAlchemy, since round-tripping real SQL is cheap and
catches query-building bugs that mocks would hide."""

from sqlalchemy import create_engine, text

from agent_harness.tools.generic_db import generic_db_query, generic_db_write


def make_db(tmp_path):
    db_path = tmp_path / "test.db"
    connection_string = f"sqlite:///{db_path}"
    engine = create_engine(connection_string)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, age INTEGER)"))
        conn.execute(text("INSERT INTO users (name, age) VALUES ('Alice', 30)"))
    engine.dispose()
    return connection_string


class TestGenericDbQuery:
    def test_select_returns_rows_as_dicts(self, tmp_path):
        connection_string = make_db(tmp_path)

        result = generic_db_query(connection_string, "SELECT * FROM users")

        assert result["success"] is True
        assert result["row_count"] == 1
        assert result["data"] == [{"id": 1, "name": "Alice", "age": 30}]

    def test_non_select_query_returns_affected_rows(self, tmp_path):
        connection_string = make_db(tmp_path)

        result = generic_db_query(
            connection_string,
            "UPDATE users SET age = :age WHERE name = :name",
            params={"age": 31, "name": "Alice"},
            query_type="update",
        )

        assert result == {"success": True, "affected_rows": 1, "error": None}

    def test_invalid_sql_is_caught_and_reported(self, tmp_path):
        connection_string = make_db(tmp_path)

        result = generic_db_query(connection_string, "NOT VALID SQL")

        assert result["success"] is False
        assert result["data"] is None
        assert result["error"]


class TestGenericDbWrite:
    def test_insert_returns_new_row_id(self, tmp_path):
        connection_string = make_db(tmp_path)

        result = generic_db_write(connection_string, "users", {"name": "Bob", "age": 25}, operation="insert")

        assert result["success"] is True
        assert result["operation"] == "insert"
        assert result["id"] == 2

        readback = generic_db_query(connection_string, "SELECT name, age FROM users WHERE id = 2")
        assert readback["data"] == [{"name": "Bob", "age": 25}]

    def test_update_without_id_is_rejected(self, tmp_path):
        connection_string = make_db(tmp_path)

        result = generic_db_write(connection_string, "users", {"name": "NoId"}, operation="update")

        assert result == {"success": False, "error": "ID required for update operation"}

    def test_update_with_id_modifies_row(self, tmp_path):
        connection_string = make_db(tmp_path)

        result = generic_db_write(connection_string, "users", {"id": 1, "age": 99}, operation="update")

        assert result == {"success": True, "operation": "update", "affected_rows": 1, "error": None}
        readback = generic_db_query(connection_string, "SELECT age FROM users WHERE id = 1")
        assert readback["data"] == [{"age": 99}]

    def test_write_to_nonexistent_table_is_caught(self, tmp_path):
        connection_string = make_db(tmp_path)

        result = generic_db_write(connection_string, "no_such_table", {"name": "x"}, operation="insert")

        assert result["success"] is False
        assert result["error"]
