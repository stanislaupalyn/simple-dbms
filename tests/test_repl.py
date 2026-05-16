import io
import os
import tempfile
import unittest

from Database import Database
from Repl import run_repl


def _run(input_text: str, db: Database) -> str:
    out = io.StringIO()
    run_repl(db, in_stream=io.StringIO(input_text), out_stream=out)
    return out.getvalue()


class ReplTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._tmp.name, "test.db")
        self.db = Database(self.path)
        self.addCleanup(self.db.close)
        self.addCleanup(self._tmp.cleanup)

    def test_create_insert_select_flow(self) -> None:
        out = _run(
            "CREATE TABLE users (id INT, name TEXT);\n"
            "INSERT INTO users VALUES (1, 'alice');\n"
            "SELECT * FROM users;\n",
            self.db,
        )
        self.assertIn("Table 'users' created", out)
        self.assertIn("1 row inserted", out)
        self.assertIn("alice", out)
        self.assertIn("(1 row)", out)

    def test_select_renders_aligned_table(self) -> None:
        out = _run(
            "CREATE TABLE t (id INT, name TEXT);\n"
            "INSERT INTO t VALUES (1, 'alice');\n"
            "INSERT INTO t VALUES (2, 'bob');\n"
            "SELECT * FROM t;\n",
            self.db,
        )
        # Header line and separator line should both appear.
        self.assertIn("id | name", out)
        self.assertIn("---+", out)
        self.assertIn("(2 rows)", out)

    def test_parse_error_prints_and_continues(self) -> None:
        out = _run(
            "garbage statement;\n"
            "CREATE TABLE t (x INT);\n",
            self.db,
        )
        self.assertIn("Parse error", out)
        self.assertIn("Table 't' created", out)

    def test_execute_error_prints_and_continues(self) -> None:
        out = _run(
            "SELECT * FROM ghosts;\n"
            "CREATE TABLE t (x INT);\n",
            self.db,
        )
        self.assertIn("Error:", out)
        self.assertIn("Table 't' created", out)

    def test_exit_statement_breaks_loop(self) -> None:
        out = _run(
            "CREATE TABLE t (x INT);\n"
            "EXIT;\n"
            "CREATE TABLE never (x INT);\n",   # not reached
            self.db,
        )
        self.assertIn("Table 't' created", out)
        self.assertNotIn("never", out)
        self.assertTrue(out.rstrip().endswith("Goodbye."))

    def test_eof_breaks_loop(self) -> None:
        out = _run("CREATE TABLE t (x INT);\n", self.db)
        # After the single line, the StringIO returns "" → EOF → loop breaks.
        self.assertTrue(out.rstrip().endswith("Goodbye."))

    def test_help_prints_help_text(self) -> None:
        out = _run("HELP;\n", self.db)
        self.assertIn("Supported statements", out)


if __name__ == "__main__":
    unittest.main()
