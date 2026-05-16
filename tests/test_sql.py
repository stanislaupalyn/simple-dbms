import os
import tempfile
import unittest

from simple_dbms.database import Database
from simple_dbms.schema import DataType
from simple_dbms.sql import (
    CountResult,
    CreateTableStmt,
    DeleteStmt,
    DropTableStmt,
    ExitStmt,
    HelpStmt,
    InsertStmt,
    ParseError,
    SelectResult,
    SelectStmt,
    ShowTablesStmt,
    StatusResult,
    Token,
    TokenType,
    UpdateStmt,
    execute,
    parse,
    tokenize,
)


class TokenizerTests(unittest.TestCase):
    def test_keywords_case_insensitive(self) -> None:
        for form in ("select", "SELECT", "Select"):
            toks = tokenize(form)
            self.assertEqual(toks[0].type, TokenType.KEYWORD)
            self.assertEqual(toks[0].text, "SELECT")

    def test_string_literal(self) -> None:
        toks = tokenize("'alice with spaces'")
        self.assertEqual(toks[0].type, TokenType.STRING_LIT)
        self.assertEqual(toks[0].text, "alice with spaces")

    def test_integer_and_negative_minus_is_separate_token(self) -> None:
        toks = tokenize("-42")
        self.assertEqual(toks[0].type, TokenType.MINUS)
        self.assertEqual(toks[1].type, TokenType.INT_LIT)
        self.assertEqual(toks[1].text, "42")

    def test_punctuation(self) -> None:
        toks = tokenize("(),;*=")
        kinds = [t.type for t in toks[:-1]]  # drop EOF
        self.assertEqual(
            kinds,
            [
                TokenType.LPAREN,
                TokenType.RPAREN,
                TokenType.COMMA,
                TokenType.SEMI,
                TokenType.STAR,
                TokenType.EQ,
            ],
        )

    def test_rejects_unknown_char(self) -> None:
        with self.assertRaises(ParseError):
            tokenize("SELECT @ FROM t")

    def test_unterminated_string_raises(self) -> None:
        with self.assertRaises(ParseError):
            tokenize("'no end")


class ParserTests(unittest.TestCase):
    def test_create_table(self) -> None:
        stmt = parse("CREATE TABLE users (id INT, name TEXT, active BOOL)")
        self.assertIsInstance(stmt, CreateTableStmt)
        assert isinstance(stmt, CreateTableStmt)
        self.assertEqual(stmt.name, "users")
        self.assertEqual(
            stmt.columns,
            [("id", DataType.INT), ("name", DataType.TEXT), ("active", DataType.BOOL)],
        )

    def test_drop_table(self) -> None:
        self.assertEqual(parse("DROP TABLE users"), DropTableStmt(name="users"))

    def test_show_tables(self) -> None:
        self.assertEqual(parse("SHOW TABLES"), ShowTablesStmt())

    def test_insert(self) -> None:
        stmt = parse("INSERT INTO users VALUES (1, 'alice', TRUE)")
        self.assertEqual(stmt, InsertStmt(table="users", values=(1, "alice", True)))

    def test_insert_with_negative_int(self) -> None:
        stmt = parse("INSERT INTO t VALUES (-7)")
        self.assertEqual(stmt, InsertStmt(table="t", values=(-7,)))

    def test_select_star(self) -> None:
        stmt = parse("SELECT * FROM users")
        self.assertEqual(stmt, SelectStmt(table="users", columns=None, where={}))

    def test_select_projection(self) -> None:
        stmt = parse("SELECT id, name FROM users")
        self.assertEqual(
            stmt, SelectStmt(table="users", columns=["id", "name"], where={})
        )

    def test_select_with_where_single(self) -> None:
        stmt = parse("SELECT * FROM users WHERE id = 1")
        self.assertEqual(stmt, SelectStmt(table="users", columns=None, where={"id": 1}))

    def test_select_with_where_multiple_and(self) -> None:
        stmt = parse("SELECT * FROM users WHERE id = 1 AND active = TRUE")
        self.assertEqual(
            stmt,
            SelectStmt(table="users", columns=None, where={"id": 1, "active": True}),
        )

    def test_update(self) -> None:
        stmt = parse("UPDATE users SET name = 'X', active = FALSE WHERE id = 1")
        self.assertEqual(
            stmt,
            UpdateStmt(
                table="users",
                set_values={"name": "X", "active": False},
                where={"id": 1},
            ),
        )

    def test_delete(self) -> None:
        stmt = parse("DELETE FROM users WHERE id = 1")
        self.assertEqual(stmt, DeleteStmt(table="users", where={"id": 1}))

    def test_optional_semicolon(self) -> None:
        self.assertEqual(parse("SELECT * FROM users;"), parse("SELECT * FROM users"))

    def test_exit_and_help(self) -> None:
        self.assertIsInstance(parse("EXIT"), ExitStmt)
        self.assertIsInstance(parse("HELP"), HelpStmt)

    def test_raises_on_trailing_garbage(self) -> None:
        with self.assertRaises(ParseError):
            parse("SELECT * FROM users foo")

    def test_raises_on_missing_keyword(self) -> None:
        with self.assertRaises(ParseError):
            parse("INSERT users VALUES (1)")  # missing INTO

    def test_raises_on_invalid_type_keyword(self) -> None:
        with self.assertRaises(ParseError):
            parse("CREATE TABLE t (x BLOB)")

    def test_raises_on_empty_input(self) -> None:
        with self.assertRaises(ParseError):
            parse("")


class ExecutorTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._tmp.name, "test.db")
        self.db = Database(self.path)
        self.addCleanup(self.db.close)
        self.addCleanup(self._tmp.cleanup)

    def test_create_then_insert_then_select(self) -> None:
        execute(parse("CREATE TABLE users (id INT, name TEXT)"), self.db)
        execute(parse("INSERT INTO users VALUES (1, 'alice')"), self.db)
        execute(parse("INSERT INTO users VALUES (2, 'bob')"), self.db)
        result = execute(parse("SELECT * FROM users"), self.db)
        self.assertIsInstance(result, SelectResult)
        assert isinstance(result, SelectResult)
        self.assertEqual(result.columns, ["id", "name"])
        self.assertEqual(result.rows, [(1, "alice"), (2, "bob")])

    def test_select_star_resolves_columns(self) -> None:
        execute(
            parse("CREATE TABLE t (a INT, b TEXT, c BOOL)"), self.db
        )
        result = execute(parse("SELECT * FROM t"), self.db)
        assert isinstance(result, SelectResult)
        self.assertEqual(result.columns, ["a", "b", "c"])
        self.assertEqual(result.rows, [])

    def test_select_projection_uses_listed_columns(self) -> None:
        execute(parse("CREATE TABLE users (id INT, name TEXT)"), self.db)
        execute(parse("INSERT INTO users VALUES (1, 'alice')"), self.db)
        result = execute(parse("SELECT name, id FROM users"), self.db)
        assert isinstance(result, SelectResult)
        self.assertEqual(result.columns, ["name", "id"])
        self.assertEqual(result.rows, [("alice", 1)])

    def test_select_with_where_filters(self) -> None:
        execute(parse("CREATE TABLE t (id INT)"), self.db)
        for i in range(3):
            execute(parse(f"INSERT INTO t VALUES ({i})"), self.db)
        result = execute(parse("SELECT * FROM t WHERE id = 1"), self.db)
        assert isinstance(result, SelectResult)
        self.assertEqual(result.rows, [(1,)])

    def test_update_returns_count(self) -> None:
        execute(parse("CREATE TABLE t (id INT, name TEXT)"), self.db)
        execute(parse("INSERT INTO t VALUES (1, 'alice')"), self.db)
        result = execute(parse("UPDATE t SET name = 'A' WHERE id = 1"), self.db)
        self.assertEqual(result, CountResult("updated", 1))

    def test_delete_returns_count(self) -> None:
        execute(parse("CREATE TABLE t (id INT)"), self.db)
        execute(parse("INSERT INTO t VALUES (1)"), self.db)
        execute(parse("INSERT INTO t VALUES (2)"), self.db)
        result = execute(parse("DELETE FROM t WHERE id = 1"), self.db)
        self.assertEqual(result, CountResult("deleted", 1))

    def test_show_tables(self) -> None:
        execute(parse("CREATE TABLE a (x INT)"), self.db)
        execute(parse("CREATE TABLE b (y INT)"), self.db)
        result = execute(parse("SHOW TABLES"), self.db)
        assert isinstance(result, SelectResult)
        self.assertEqual(result.columns, ["table"])
        self.assertEqual(result.rows, [("a",), ("b",)])

    def test_drop_table_found_and_missing(self) -> None:
        execute(parse("CREATE TABLE t (x INT)"), self.db)
        self.assertEqual(
            execute(parse("DROP TABLE t"), self.db),
            StatusResult("Table 't' dropped"),
        )
        self.assertEqual(
            execute(parse("DROP TABLE ghost"), self.db),
            StatusResult("Table 'ghost' not found"),
        )


if __name__ == "__main__":
    unittest.main()
