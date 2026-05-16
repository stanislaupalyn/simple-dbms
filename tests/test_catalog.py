import os
import tempfile
import unittest

from Catalog import Catalog, ColumnDef
from DiskManager import PAGE_SIZE, DiskManager
from Schema import DataType
from SlottedPage import SlottedPage


class CatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._tmp.name, "test.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_fresh_catalog_creates_page_zero(self) -> None:
        with DiskManager(self.path) as dm:
            Catalog(dm)
            self.assertEqual(dm.num_pages, 1)
            raw = dm.read_page(0)
            page = SlottedPage(bytearray(raw))
            self.assertEqual(page.page_id, 0)
            self.assertEqual(page.num_slots, 0)

    def test_create_table_returns_table_info(self) -> None:
        with DiskManager(self.path) as dm:
            cat = Catalog(dm)
            info = cat.create_table("users", [ColumnDef("id", DataType.INT)])
            self.assertEqual(info.name, "users")
            self.assertEqual(info.first_page_id, 1)
            self.assertEqual(info.columns, (ColumnDef("id", DataType.INT),))

    def test_create_table_initializes_data_page(self) -> None:
        with DiskManager(self.path) as dm:
            cat = Catalog(dm)
            info = cat.create_table("users", [ColumnDef("id", DataType.INT)])
            raw = dm.read_page(info.first_page_id)
            data_page = SlottedPage(bytearray(raw))
            self.assertEqual(data_page.page_id, info.first_page_id)
            self.assertEqual(data_page.num_slots, 0)

    def test_get_table_after_create(self) -> None:
        with DiskManager(self.path) as dm:
            cat = Catalog(dm)
            created = cat.create_table(
                "users",
                [ColumnDef("id", DataType.INT), ColumnDef("name", DataType.TEXT)],
            )
            fetched = cat.get_table("users")
            self.assertEqual(fetched, created)

    def test_get_table_missing_returns_none(self) -> None:
        with DiskManager(self.path) as dm:
            cat = Catalog(dm)
            self.assertIsNone(cat.get_table("nope"))

    def test_list_tables_returns_in_insertion_order(self) -> None:
        with DiskManager(self.path) as dm:
            cat = Catalog(dm)
            cat.create_table("a", [ColumnDef("x", DataType.INT)])
            cat.create_table("b", [ColumnDef("y", DataType.TEXT)])
            cat.create_table("c", [ColumnDef("z", DataType.BOOL)])
            self.assertEqual([t.name for t in cat.list_tables()], ["a", "b", "c"])

    def test_create_duplicate_raises(self) -> None:
        with DiskManager(self.path) as dm:
            cat = Catalog(dm)
            cat.create_table("users", [ColumnDef("id", DataType.INT)])
            with self.assertRaises(ValueError):
                cat.create_table("users", [ColumnDef("id", DataType.INT)])

    def test_drop_table_removes_from_catalog(self) -> None:
        with DiskManager(self.path) as dm:
            cat = Catalog(dm)
            cat.create_table("users", [ColumnDef("id", DataType.INT)])
            cat.create_table("posts", [ColumnDef("id", DataType.INT)])
            self.assertTrue(cat.drop_table("users"))
            self.assertIsNone(cat.get_table("users"))
            self.assertEqual([t.name for t in cat.list_tables()], ["posts"])

    def test_drop_unknown_returns_false(self) -> None:
        with DiskManager(self.path) as dm:
            cat = Catalog(dm)
            self.assertFalse(cat.drop_table("nope"))

    def test_reopen_persists_catalog(self) -> None:
        cols_users = [
            ColumnDef("id", DataType.INT),
            ColumnDef("name", DataType.TEXT),
        ]
        cols_posts = [
            ColumnDef("id", DataType.INT),
            ColumnDef("published", DataType.BOOL),
        ]

        with DiskManager(self.path) as dm:
            cat = Catalog(dm)
            users_info = cat.create_table("users", cols_users)
            posts_info = cat.create_table("posts", cols_posts)

        with DiskManager(self.path) as dm2:
            cat2 = Catalog(dm2)
            self.assertEqual(cat2.get_table("users"), users_info)
            self.assertEqual(cat2.get_table("posts"), posts_info)

    def test_roundtrip_many_columns_mixed_types(self) -> None:
        cols = [
            ColumnDef("id", DataType.INT),
            ColumnDef("name", DataType.TEXT),
            ColumnDef("active", DataType.BOOL),
            ColumnDef("héllo", DataType.TEXT),
            ColumnDef("count", DataType.INT),
        ]
        with DiskManager(self.path) as dm:
            cat = Catalog(dm)
            cat.create_table("wide", cols)

        with DiskManager(self.path) as dm2:
            cat2 = Catalog(dm2)
            info = cat2.get_table("wide")
            assert info is not None
            self.assertEqual(list(info.columns), cols)

    def test_rejects_empty_name(self) -> None:
        with DiskManager(self.path) as dm:
            cat = Catalog(dm)
            with self.assertRaises(ValueError):
                cat.create_table("", [ColumnDef("id", DataType.INT)])

    def test_rejects_empty_columns(self) -> None:
        with DiskManager(self.path) as dm:
            cat = Catalog(dm)
            with self.assertRaises(ValueError):
                cat.create_table("users", [])

    def test_rejects_non_catalog_page_zero(self) -> None:
        with DiskManager(self.path) as dm:
            pid = dm.allocate_page()
            self.assertEqual(pid, 0)
            # Write a non-catalog SlottedPage (claims page_id=99) into page 0.
            bogus = SlottedPage.new(page_id=99)
            dm.write_page(0, bogus.buffer)

        with DiskManager(self.path) as dm2:
            with self.assertRaises(ValueError):
                Catalog(dm2)

    def test_full_catalog_does_not_leak_data_page(self) -> None:
        """A failed create_table must not leave an orphan data page in the file.

        DiskManager has no deallocate, so the size check must happen BEFORE
        allocate_page is called.
        """
        with DiskManager(self.path) as dm:
            cat = Catalog(dm)
            i = 0
            while True:
                try:
                    cat.create_table(f"t{i}", [ColumnDef("c", DataType.INT)])
                except RuntimeError:
                    break
                i += 1
                if i > PAGE_SIZE:
                    self.fail("catalog never reported full")

            pages_before = dm.num_pages
            with self.assertRaises(RuntimeError):
                cat.create_table("extra", [ColumnDef("c", DataType.INT)])
            self.assertEqual(
                dm.num_pages,
                pages_before,
                "failed create_table allocated a data page that is now orphaned",
            )

    def test_schema_property_serializes_rows(self) -> None:
        with DiskManager(self.path) as dm:
            cat = Catalog(dm)
            info = cat.create_table(
                "users",
                [ColumnDef("id", DataType.INT), ColumnDef("name", DataType.TEXT)],
            )
            schema = info.schema
            data = schema.serialize((42, "alice"))
            self.assertEqual(schema.deserialize(data), (42, "alice"))


if __name__ == "__main__":
    unittest.main()
