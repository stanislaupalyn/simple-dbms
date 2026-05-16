import os
import tempfile
import unittest
from typing import List, Tuple

from Catalog import Catalog, ColumnDef
from DiskManager import DiskManager
from Schema import DataType
from SlottedPage import NO_NEXT_PAGE, SlottedPage
from TableHeap import MAX_ROW_BYTES, RID, TableHeap


def _make_users_heap(path: str) -> Tuple[DiskManager, TableHeap]:
    dm = DiskManager(path)
    cat = Catalog(dm)
    info = cat.create_table(
        "users",
        [ColumnDef("id", DataType.INT), ColumnDef("name", DataType.TEXT)],
    )
    return dm, TableHeap(dm, info)


class TableHeapTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._tmp.name, "test.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_empty_scan(self) -> None:
        dm, heap = _make_users_heap(self.path)
        try:
            self.assertEqual(list(heap.scan()), [])
        finally:
            dm.close()

    def test_insert_get_scan_single_row(self) -> None:
        dm, heap = _make_users_heap(self.path)
        try:
            rid = heap.insert((1, "alice"))
            self.assertEqual(heap.get(rid), (1, "alice"))
            self.assertEqual(list(heap.scan()), [(rid, (1, "alice"))])
        finally:
            dm.close()

    def test_insert_many_single_page(self) -> None:
        dm, heap = _make_users_heap(self.path)
        try:
            rows = [(i, f"name{i}") for i in range(20)]
            rids = [heap.insert(r) for r in rows]
            # All on the first data page (page 1; page 0 is the catalog).
            self.assertTrue(all(r.page_id == 1 for r in rids))
            scanned = list(heap.scan())
            self.assertEqual([s for _, s in scanned], rows)
            self.assertEqual([r for r, _ in scanned], rids)
        finally:
            dm.close()

    def test_insert_overflows_to_new_page(self) -> None:
        dm, heap = _make_users_heap(self.path)
        try:
            big_name = "x" * 800  # ~806-byte serialized rows; ~5 per page
            rids: List[RID] = []
            values: List[tuple] = []
            for i in range(15):
                v = (i, big_name)
                values.append(v)
                rids.append(heap.insert(v))

            distinct_pages = {r.page_id for r in rids}
            self.assertGreater(len(distinct_pages), 1)

            # Scan returns everything in insertion order.
            scanned = list(heap.scan())
            self.assertEqual([s for _, s in scanned], values)
            self.assertEqual([r for r, _ in scanned], rids)

            # First page's next_page_id points at the second page used.
            first_pid = 1
            first_page = SlottedPage(bytearray(dm.read_page(first_pid)))
            second_pid = sorted(distinct_pages)[1]
            self.assertEqual(first_page.next_page_id, second_pid)
        finally:
            dm.close()

    def test_delete_tombstones_skipped_by_scan(self) -> None:
        dm, heap = _make_users_heap(self.path)
        try:
            r0 = heap.insert((1, "a"))
            r1 = heap.insert((2, "b"))
            r2 = heap.insert((3, "c"))
            self.assertTrue(heap.delete(r1))
            self.assertIsNone(heap.get(r1))
            scanned = list(heap.scan())
            self.assertEqual(scanned, [(r0, (1, "a")), (r2, (3, "c"))])
        finally:
            dm.close()

    def test_delete_returns_false_for_unknown_slot(self) -> None:
        dm, heap = _make_users_heap(self.path)
        try:
            self.assertFalse(heap.delete(RID(1, 999)))
        finally:
            dm.close()

    def test_delete_returns_false_for_already_deleted(self) -> None:
        dm, heap = _make_users_heap(self.path)
        try:
            rid = heap.insert((1, "a"))
            self.assertTrue(heap.delete(rid))
            self.assertFalse(heap.delete(rid))
        finally:
            dm.close()

    def test_reopen_persists_rows(self) -> None:
        rows = [(1, "alice"), (2, "bob"), (3, "carol")]
        with DiskManager(self.path) as dm:
            cat = Catalog(dm)
            info = cat.create_table(
                "users",
                [ColumnDef("id", DataType.INT), ColumnDef("name", DataType.TEXT)],
            )
            heap = TableHeap(dm, info)
            for r in rows:
                heap.insert(r)

        with DiskManager(self.path) as dm2:
            cat2 = Catalog(dm2)
            info2 = cat2.get_table("users")
            assert info2 is not None
            heap2 = TableHeap(dm2, info2)
            self.assertEqual([s for _, s in heap2.scan()], rows)

    def test_rejects_oversized_row(self) -> None:
        with DiskManager(self.path) as dm:
            cat = Catalog(dm)
            info = cat.create_table("blob", [ColumnDef("data", DataType.TEXT)])
            heap = TableHeap(dm, info)
            # MAX_ROW_BYTES = 4080. TEXT overhead = 2 bytes length prefix, so a
            # 4080-byte string exactly fills the row; 4079 chars + 2 prefix = 4081, over.
            with self.assertRaises(ValueError):
                heap.insert(("x" * MAX_ROW_BYTES,))

    def test_schema_validates_insert_values(self) -> None:
        dm, heap = _make_users_heap(self.path)
        try:
            with self.assertRaises(TypeError):
                heap.insert((True, "alice"))  # bool rejected for INT column
            with self.assertRaises(ValueError):
                heap.insert((1,))  # arity mismatch
        finally:
            dm.close()

    def test_get_unknown_returns_none(self) -> None:
        dm, heap = _make_users_heap(self.path)
        try:
            heap.insert((1, "a"))
            self.assertIsNone(heap.get(RID(1, 999)))
        finally:
            dm.close()

    def test_scan_after_delete_then_insert(self) -> None:
        dm, heap = _make_users_heap(self.path)
        try:
            r0 = heap.insert((1, "a"))
            r1 = heap.insert((2, "b"))
            r2 = heap.insert((3, "c"))
            heap.delete(r1)
            r3 = heap.insert((4, "d"))
            scanned = list(heap.scan())
            self.assertEqual(
                scanned,
                [(r0, (1, "a")), (r2, (3, "c")), (r3, (4, "d"))],
            )
            # New insert appended with a fresh slot id (not reusing r1).
            self.assertNotEqual(r3, r1)
        finally:
            dm.close()

    def test_update_in_place_preserves_rid(self) -> None:
        dm, heap = _make_users_heap(self.path)
        try:
            rid = heap.insert((1, "alice"))
            self.assertEqual(heap.update(rid, (1, "ALICE")), rid)
            self.assertEqual(heap.get(rid), (1, "ALICE"))
        finally:
            dm.close()

    def test_update_growing_row_preserves_rid(self) -> None:
        dm, heap = _make_users_heap(self.path)
        try:
            rid = heap.insert((1, "a"))
            self.assertEqual(
                heap.update(rid, (1, "a much longer name than before")),
                rid,
            )
            self.assertEqual(heap.get(rid), (1, "a much longer name than before"))
        finally:
            dm.close()

    def test_update_persists_across_reopen(self) -> None:
        with DiskManager(self.path) as dm:
            cat = Catalog(dm)
            info = cat.create_table(
                "users",
                [ColumnDef("id", DataType.INT), ColumnDef("name", DataType.TEXT)],
            )
            heap = TableHeap(dm, info)
            rid = heap.insert((1, "alice"))
            new_rid = heap.update(rid, (42, "ALICE-updated"))

        with DiskManager(self.path) as dm2:
            cat2 = Catalog(dm2)
            info2 = cat2.get_table("users")
            assert info2 is not None
            heap2 = TableHeap(dm2, info2)
            self.assertEqual(heap2.get(new_rid), (42, "ALICE-updated"))

    def test_update_validates_via_schema(self) -> None:
        dm, heap = _make_users_heap(self.path)
        try:
            rid = heap.insert((1, "a"))
            with self.assertRaises(TypeError):
                heap.update(rid, (True, "b"))  # bool rejected for INT
            with self.assertRaises(ValueError):
                heap.update(rid, (1,))  # arity mismatch
            # Original row untouched after failed updates.
            self.assertEqual(heap.get(rid), (1, "a"))
        finally:
            dm.close()

    def test_update_rejects_oversized_row(self) -> None:
        with DiskManager(self.path) as dm:
            cat = Catalog(dm)
            info = cat.create_table("blob", [ColumnDef("data", DataType.TEXT)])
            heap = TableHeap(dm, info)
            rid = heap.insert(("hi",))
            with self.assertRaises(ValueError):
                heap.update(rid, ("x" * MAX_ROW_BYTES,))

    def test_update_raises_for_invalid_rid(self) -> None:
        dm, heap = _make_users_heap(self.path)
        try:
            with self.assertRaises(ValueError):
                heap.update(RID(1, 999), (1, "a"))
        finally:
            dm.close()

    def test_update_relocates_when_row_does_not_fit_in_page(self) -> None:
        with DiskManager(self.path) as dm:
            cat = Catalog(dm)
            info = cat.create_table("blob", [ColumnDef("data", DataType.TEXT)])
            heap = TableHeap(dm, info)
            rid = heap.insert(("small",))
            # Burn most of the page's free space with another insert.
            heap.insert(("y" * 3500,))
            pages_before = dm.num_pages

            new_rid = heap.update(rid, ("z" * 1000,))

            # RID changed (relocated, likely to a new page).
            self.assertNotEqual(new_rid, rid)
            # Old RID is tombstoned.
            self.assertIsNone(heap.get(rid))
            # New RID holds the updated value.
            self.assertEqual(heap.get(new_rid), ("z" * 1000,))
            # A new page was allocated for the relocation.
            self.assertGreater(dm.num_pages, pages_before)
            # Scan still finds the relocated row.
            scanned_values = [row for _, row in heap.scan()]
            self.assertIn(("z" * 1000,), scanned_values)

    def test_tail_chain_terminator_after_growth(self) -> None:
        # The newly allocated tail page must itself have next_page_id == NO_NEXT_PAGE.
        dm, heap = _make_users_heap(self.path)
        try:
            big = "x" * 800
            for i in range(15):
                heap.insert((i, big))
            # Walk the chain manually and verify the last page terminates.
            page_id = 1
            while True:
                page = SlottedPage(bytearray(dm.read_page(page_id)))
                if page.next_page_id == NO_NEXT_PAGE:
                    break
                page_id = page.next_page_id
            # Found the tail; nothing more to assert beyond the loop terminating.
        finally:
            dm.close()


if __name__ == "__main__":
    unittest.main()
