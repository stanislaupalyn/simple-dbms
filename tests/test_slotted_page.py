import os
import struct
import tempfile
import unittest

from DiskManager import PAGE_SIZE, DiskManager
from SlottedPage import HEADER_SIZE, NO_NEXT_PAGE, SlottedPage


class SlottedPageTests(unittest.TestCase):
    def test_fresh_page_state(self) -> None:
        page = SlottedPage.new(page_id=42)
        self.assertEqual(page.page_id, 42)
        self.assertEqual(page.next_page_id, NO_NEXT_PAGE)
        self.assertEqual(page.num_slots, 0)
        self.assertEqual(page.free_space, PAGE_SIZE - HEADER_SIZE)

    def test_insert_get_roundtrip(self) -> None:
        page = SlottedPage.new(page_id=1)
        sid = page.insert(b"hello")
        self.assertEqual(sid, 0)
        self.assertEqual(page.num_slots, 1)
        self.assertEqual(page.get(0), b"hello")

    def test_multiple_inserts_increment_ids(self) -> None:
        page = SlottedPage.new(page_id=1)
        payloads = [b"first", b"second tuple", b"third!"]
        sids = [page.insert(p) for p in payloads]
        self.assertEqual(sids, [0, 1, 2])
        for sid, payload in zip(sids, payloads):
            assert sid is not None
            self.assertEqual(page.get(sid), payload)

    def test_delete_tombstones(self) -> None:
        page = SlottedPage.new(page_id=1)
        page.insert(b"alpha")
        page.insert(b"beta")
        self.assertTrue(page.delete(0))
        self.assertIsNone(page.get(0))
        self.assertEqual(page.get(1), b"beta")
        self.assertEqual(page.num_slots, 2)
        # Second delete of the same slot reports False.
        self.assertFalse(page.delete(0))

    def test_iter_tuples_skips_deleted(self) -> None:
        page = SlottedPage.new(page_id=1)
        page.insert(b"a")
        page.insert(b"b")
        page.insert(b"c")
        page.delete(1)
        self.assertEqual(list(page.iter_tuples()), [(0, b"a"), (2, b"c")])

    def test_insert_returns_none_when_full(self) -> None:
        page = SlottedPage.new(page_id=1)
        chunk = b"x" * 100
        inserted = 0
        while page.insert(chunk) is not None:
            inserted += 1
            if inserted > PAGE_SIZE:
                self.fail("insert never returned None")

        # Capture state, attempt one more insert, confirm unchanged.
        before = (page.num_slots, page.free_space, bytes(page.buffer))
        self.assertIsNone(page.insert(chunk))
        after = (page.num_slots, page.free_space, bytes(page.buffer))
        self.assertEqual(before, after)

    def test_reject_empty_tuple(self) -> None:
        page = SlottedPage.new(page_id=1)
        with self.assertRaises(ValueError):
            page.insert(b"")

    def test_next_page_id_roundtrip(self) -> None:
        page = SlottedPage.new(page_id=1)
        page.next_page_id = 7
        self.assertEqual(page.next_page_id, 7)
        self.assertEqual(page.buffer[4:8], struct.pack("<I", 7))

    def test_out_of_range_get_and_delete(self) -> None:
        page = SlottedPage.new(page_id=1)
        page.insert(b"only")
        self.assertIsNone(page.get(5))
        self.assertIsNone(page.get(-1))
        self.assertFalse(page.delete(5))
        self.assertFalse(page.delete(-1))


class SlottedPageUpdateTests(unittest.TestCase):
    def test_update_in_place_same_size(self) -> None:
        page = SlottedPage.new(page_id=1)
        sid = page.insert(b"hello")
        free_before = page.free_space
        assert sid is not None
        self.assertTrue(page.update(sid, b"WORLD"))
        self.assertEqual(page.get(sid), b"WORLD")
        self.assertEqual(page.free_space, free_before)  # no relocation

    def test_update_in_place_smaller(self) -> None:
        page = SlottedPage.new(page_id=1)
        sid = page.insert(b"hello")
        free_before = page.free_space
        assert sid is not None
        self.assertTrue(page.update(sid, b"hi"))
        self.assertEqual(page.get(sid), b"hi")
        # Smaller in-place update doesn't reclaim space — the gap is dead.
        self.assertEqual(page.free_space, free_before)

    def test_update_relocates_when_larger_and_fits(self) -> None:
        page = SlottedPage.new(page_id=1)
        sid = page.insert(b"hi")
        page.insert(b"sibling")  # so growing slot 0 must relocate, not just extend
        free_before = page.free_space
        assert sid is not None
        self.assertTrue(page.update(sid, b"a much larger payload"))
        self.assertEqual(page.get(sid), b"a much larger payload")
        # New bytes consumed from free space; old bytes are dead.
        self.assertEqual(page.free_space, free_before - len(b"a much larger payload"))

    def test_update_preserves_other_slots(self) -> None:
        page = SlottedPage.new(page_id=1)
        a = page.insert(b"alpha")
        b = page.insert(b"beta")
        c = page.insert(b"gamma")
        assert a is not None and b is not None and c is not None
        self.assertTrue(page.update(b, b"BETA-much-longer-now"))
        self.assertEqual(page.get(a), b"alpha")
        self.assertEqual(page.get(b), b"BETA-much-longer-now")
        self.assertEqual(page.get(c), b"gamma")

    def test_update_returns_false_when_no_room(self) -> None:
        page = SlottedPage.new(page_id=1)
        sid = page.insert(b"hi")
        assert sid is not None
        before_buf = bytes(page.buffer)
        before_free = page.free_space
        self.assertFalse(page.update(sid, b"x" * (PAGE_SIZE + 1)))
        # Page state unchanged when update reports no room.
        self.assertEqual(bytes(page.buffer), before_buf)
        self.assertEqual(page.free_space, before_free)
        # Original tuple still readable.
        self.assertEqual(page.get(sid), b"hi")

    def test_update_rejects_empty(self) -> None:
        page = SlottedPage.new(page_id=1)
        sid = page.insert(b"hi")
        with self.assertRaises(ValueError):
            assert sid is not None
            page.update(sid, b"")

    def test_update_rejects_invalid_slot(self) -> None:
        page = SlottedPage.new(page_id=1)
        page.insert(b"hi")
        with self.assertRaises(ValueError):
            page.update(5, b"x")
        with self.assertRaises(ValueError):
            page.update(-1, b"x")

    def test_update_rejects_tombstoned_slot(self) -> None:
        page = SlottedPage.new(page_id=1)
        sid = page.insert(b"hi")
        assert sid is not None
        page.delete(sid)
        with self.assertRaises(ValueError):
            page.update(sid, b"new")


class SlottedPageDiskRoundtripTests(unittest.TestCase):
    def test_buffer_roundtrip_via_diskmanager(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.db")
            payloads = [b"row-one", b"row-two", b"row-three"]

            with DiskManager(path) as dm:
                pid = dm.allocate_page()
                page = SlottedPage.new(page_id=pid)
                page.next_page_id = 99
                for p in payloads:
                    page.insert(p)
                dm.write_page(pid, page.buffer)

            with DiskManager(path) as dm2:
                raw = dm2.read_page(pid)
                reloaded = SlottedPage(bytearray(raw))
                self.assertEqual(reloaded.page_id, pid)
                self.assertEqual(reloaded.next_page_id, 99)
                self.assertEqual(reloaded.num_slots, len(payloads))
                self.assertEqual(
                    list(reloaded.iter_tuples()),
                    list(enumerate(payloads)),
                )


if __name__ == "__main__":
    unittest.main()
