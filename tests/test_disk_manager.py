import os
import tempfile
import unittest

from simple_dbms.disk_manager import PAGE_SIZE, DiskManager


class DiskManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._tmp.name, "test.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_create_new_file(self) -> None:
        self.assertFalse(os.path.exists(self.path))
        with DiskManager(self.path) as dm:
            self.assertEqual(dm.num_pages, 0)
        self.assertTrue(os.path.exists(self.path))
        self.assertEqual(os.path.getsize(self.path), 0)

    def test_creates_intermediate_directories(self) -> None:
        nested = os.path.join(self._tmp.name, "new_a", "new_b", "test.db")
        self.assertFalse(os.path.exists(os.path.dirname(nested)))
        with DiskManager(nested) as dm:
            self.assertEqual(dm.num_pages, 0)
        self.assertTrue(os.path.exists(nested))
        self.assertEqual(os.path.getsize(nested), 0)

    def test_reject_corrupt_file_size(self) -> None:
        with open(self.path, "wb") as f:
            f.write(b"x" * 100)
        with self.assertRaises(ValueError):
            DiskManager(self.path)

    def test_write_then_read_roundtrip(self) -> None:
        payload = b"hello, page\x00" + b"\xab" * (PAGE_SIZE - len(b"hello, page\x00"))
        with DiskManager(self.path) as dm:
            pid = dm.allocate_page()
            dm.write_page(pid, payload)
            self.assertEqual(dm.read_page(pid), payload)

    def test_multiple_pages_distinct_offsets(self) -> None:
        payloads = [bytes([i]) * PAGE_SIZE for i in (1, 2, 3)]
        with DiskManager(self.path) as dm:
            pids = [dm.allocate_page() for _ in payloads]
            self.assertEqual(pids, [0, 1, 2])
            for pid, payload in zip(pids, payloads):
                dm.write_page(pid, payload)
            for pid, payload in zip(pids, payloads):
                self.assertEqual(dm.read_page(pid), payload)
        self.assertEqual(os.path.getsize(self.path), 3 * PAGE_SIZE)

    def test_reopen_preserves_contents(self) -> None:
        payload_a = b"A" * PAGE_SIZE
        payload_b = b"B" * PAGE_SIZE
        with DiskManager(self.path) as dm:
            pa = dm.allocate_page()
            pb = dm.allocate_page()
            dm.write_page(pa, payload_a)
            dm.write_page(pb, payload_b)

        with DiskManager(self.path) as dm2:
            self.assertEqual(dm2.num_pages, 2)
            self.assertEqual(dm2.read_page(0), payload_a)
            self.assertEqual(dm2.read_page(1), payload_b)

    def test_wrong_size_write_rejected(self) -> None:
        with DiskManager(self.path) as dm:
            dm.allocate_page()
            with self.assertRaises(ValueError):
                dm.write_page(0, b"short")
            with self.assertRaises(ValueError):
                dm.write_page(0, b"\x00" * (PAGE_SIZE + 1))

    def test_read_unallocated_rejected(self) -> None:
        with DiskManager(self.path) as dm:
            with self.assertRaises(ValueError):
                dm.read_page(5)
            with self.assertRaises(ValueError):
                dm.read_page(-1)

    def test_allocate_returns_incrementing_ids(self) -> None:
        with DiskManager(self.path) as dm:
            self.assertEqual(dm.allocate_page(), 0)
            self.assertEqual(dm.allocate_page(), 1)
            self.assertEqual(dm.allocate_page(), 2)
            self.assertEqual(dm.num_pages, 3)


if __name__ == "__main__":
    unittest.main()
