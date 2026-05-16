import os
import tempfile
import unittest

from simple_dbms.database import ColumnDef, Database
from simple_dbms.schema import DataType


class DatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._tmp.name, "test.db")
        self.db = Database(self.path)
        self.addCleanup(self.db.close)
        self.addCleanup(self._tmp.cleanup)

        self.db.create_table(
            "users",
            [
                ColumnDef("id", DataType.INT),
                ColumnDef("name", DataType.TEXT),
                ColumnDef("active", DataType.BOOL),
            ],
        )

    # --- create / list / drop ---

    def test_list_tables_reflects_create_and_drop(self) -> None:
        self.assertEqual(self.db.list_tables(), ["users"])
        self.db.create_table("posts", [ColumnDef("id", DataType.INT)])
        self.assertEqual(self.db.list_tables(), ["users", "posts"])
        self.assertTrue(self.db.drop_table("users"))
        self.assertEqual(self.db.list_tables(), ["posts"])

    def test_drop_table_then_subsequent_ops_raise(self) -> None:
        self.db.insert("users", (1, "alice", True))
        self.assertTrue(self.db.drop_table("users"))
        with self.assertRaises(ValueError):
            list(self.db.select("users"))

    # --- insert + select ---

    def test_create_and_insert_roundtrip(self) -> None:
        self.db.insert("users", (1, "alice", True))
        self.db.insert("users", (2, "bob", False))
        self.assertEqual(
            list(self.db.select("users")),
            [(1, "alice", True), (2, "bob", False)],
        )

    def test_select_star_returns_all_columns(self) -> None:
        self.db.insert("users", (1, "alice", True))
        rows = list(self.db.select("users"))
        self.assertEqual(rows, [(1, "alice", True)])

    def test_select_projection_subset_and_reorder(self) -> None:
        self.db.insert("users", (1, "alice", True))
        self.db.insert("users", (2, "bob", False))
        rows = list(self.db.select("users", columns=["name", "id"]))
        self.assertEqual(rows, [("alice", 1), ("bob", 2)])

    # --- WHERE ---

    def test_select_with_where_exact_match(self) -> None:
        self.db.insert("users", (1, "alice", True))
        self.db.insert("users", (2, "bob", False))
        self.db.insert("users", (3, "carol", True))
        rows = list(self.db.select("users", where={"id": 2}))
        self.assertEqual(rows, [(2, "bob", False)])

    def test_select_where_no_match_returns_empty(self) -> None:
        self.db.insert("users", (1, "alice", True))
        self.assertEqual(list(self.db.select("users", where={"id": 999})), [])

    def test_select_where_type_mismatch_returns_empty(self) -> None:
        # Documents the "no coercion" semantic: "2" != 2 in Python.
        self.db.insert("users", (2, "bob", False))
        self.assertEqual(list(self.db.select("users", where={"id": "2"})), [])

    def test_select_with_multiple_conditions_anded(self) -> None:
        self.db.insert("users", (1, "alice", True))
        self.db.insert("users", (2, "alice", False))
        self.db.insert("users", (3, "bob", True))
        rows = list(self.db.select("users", where={"name": "alice", "active": True}))
        self.assertEqual(rows, [(1, "alice", True)])

    def test_select_with_partial_match_returns_empty(self) -> None:
        # Both conditions must hold: name matches, active doesn't.
        self.db.insert("users", (1, "alice", True))
        rows = list(self.db.select("users", where={"name": "alice", "active": False}))
        self.assertEqual(rows, [])

    def test_empty_where_dict_matches_all(self) -> None:
        self.db.insert("users", (1, "alice", True))
        self.db.insert("users", (2, "bob", False))
        rows = list(self.db.select("users", where={}))
        self.assertEqual(rows, [(1, "alice", True), (2, "bob", False)])

    def test_unknown_column_in_multi_where_raises(self) -> None:
        self.db.insert("users", (1, "alice", True))
        with self.assertRaises(ValueError):
            list(self.db.select("users", where={"id": 1, "ghost": 0}))

    # --- update ---

    def test_update_returns_count_and_changes_rows(self) -> None:
        self.db.insert("users", (1, "alice", True))
        self.db.insert("users", (2, "bob", False))
        self.db.insert("users", (3, "carol", True))
        n = self.db.update("users", {"name": "BOB"}, where={"id": 2})
        self.assertEqual(n, 1)
        self.assertEqual(
            list(self.db.select("users")),
            [(1, "alice", True), (2, "BOB", False), (3, "carol", True)],
        )

    def test_update_partial_columns_leaves_others(self) -> None:
        self.db.insert("users", (1, "alice", True))
        self.db.update("users", {"name": "ALICE"}, where={"id": 1})
        self.assertEqual(list(self.db.select("users")), [(1, "ALICE", True)])

    def test_update_no_match_returns_zero(self) -> None:
        self.db.insert("users", (1, "alice", True))
        before = list(self.db.select("users"))
        n = self.db.update("users", {"name": "X"}, where={"id": 999})
        self.assertEqual(n, 0)
        self.assertEqual(list(self.db.select("users")), before)

    def test_update_without_where_updates_all(self) -> None:
        self.db.insert("users", (1, "alice", True))
        self.db.insert("users", (2, "bob", False))
        n = self.db.update("users", {"active": True})
        self.assertEqual(n, 2)
        self.assertEqual(
            [r[2] for r in self.db.select("users")],
            [True, True],
        )

    def test_update_with_multiple_conditions(self) -> None:
        self.db.insert("users", (1, "alice", True))
        self.db.insert("users", (2, "alice", False))
        self.db.insert("users", (3, "bob", True))
        n = self.db.update(
            "users", {"name": "ALICE"}, where={"name": "alice", "active": True}
        )
        self.assertEqual(n, 1)
        self.assertEqual(
            list(self.db.select("users")),
            [(1, "ALICE", True), (2, "alice", False), (3, "bob", True)],
        )

    def test_update_unknown_column_in_set_raises(self) -> None:
        self.db.insert("users", (1, "alice", True))
        with self.assertRaises(ValueError):
            self.db.update("users", {"nope": 1})

    # --- delete ---

    def test_delete_returns_count_and_removes_rows(self) -> None:
        self.db.insert("users", (1, "alice", True))
        self.db.insert("users", (2, "bob", False))
        self.db.insert("users", (3, "carol", True))
        n = self.db.delete("users", where={"id": 2})
        self.assertEqual(n, 1)
        self.assertEqual(
            list(self.db.select("users")),
            [(1, "alice", True), (3, "carol", True)],
        )

    def test_delete_without_where_removes_all(self) -> None:
        self.db.insert("users", (1, "alice", True))
        self.db.insert("users", (2, "bob", False))
        n = self.db.delete("users")
        self.assertEqual(n, 2)
        self.assertEqual(list(self.db.select("users")), [])

    def test_delete_with_multiple_conditions(self) -> None:
        self.db.insert("users", (1, "alice", True))
        self.db.insert("users", (2, "alice", False))
        self.db.insert("users", (3, "bob", True))
        n = self.db.delete("users", where={"name": "alice", "active": True})
        self.assertEqual(n, 1)
        self.assertEqual(
            [r[0] for r in self.db.select("users")],
            [2, 3],
        )

    def test_delete_no_match_returns_zero(self) -> None:
        self.db.insert("users", (1, "alice", True))
        self.assertEqual(self.db.delete("users", where={"id": 999}), 0)

    # --- errors ---

    def test_insert_propagates_type_error(self) -> None:
        with self.assertRaises(TypeError):
            self.db.insert("users", ("not-int", "alice", True))

    def test_select_unknown_column_raises(self) -> None:
        with self.assertRaises(ValueError):
            list(self.db.select("users", columns=["nope"]))
        with self.assertRaises(ValueError):
            list(self.db.select("users", where={"nope": 1}))

    def test_operations_on_unknown_table_raise(self) -> None:
        with self.assertRaises(ValueError):
            self.db.insert("ghosts", (1,))
        with self.assertRaises(ValueError):
            list(self.db.select("ghosts"))
        with self.assertRaises(ValueError):
            self.db.update("ghosts", {"x": 1})
        with self.assertRaises(ValueError):
            self.db.delete("ghosts")

    # --- multi-table & persistence ---

    def test_multiple_tables_isolated(self) -> None:
        self.db.create_table("posts", [ColumnDef("id", DataType.INT)])
        self.db.insert("users", (1, "alice", True))
        self.db.insert("posts", (10,))
        self.db.delete("users")
        self.assertEqual(list(self.db.select("users")), [])
        self.assertEqual(list(self.db.select("posts")), [(10,)])


class DatabasePersistenceTests(unittest.TestCase):
    def test_persistence_across_reopen(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "test.db")

        with Database(path) as db:
            db.create_table(
                "users",
                [ColumnDef("id", DataType.INT), ColumnDef("name", DataType.TEXT)],
            )
            db.insert("users", (1, "alice"))
            db.insert("users", (2, "bob"))

        with Database(path) as db2:
            self.assertEqual(db2.list_tables(), ["users"])
            self.assertEqual(
                list(db2.select("users")),
                [(1, "alice"), (2, "bob")],
            )


if __name__ == "__main__":
    unittest.main()
