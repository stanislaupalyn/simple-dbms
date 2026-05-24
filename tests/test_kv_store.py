import os
import tempfile
import unittest

from simple_dbms.kv_store import KeyValueStore


class KeyValueStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._tmp.name, "kv.log")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_set_then_get(self) -> None:
        with KeyValueStore(self.path) as kv:
            kv.set("a", "1")
            self.assertEqual(kv.get("a"), "1")

    def test_get_missing_returns_none(self) -> None:
        with KeyValueStore(self.path) as kv:
            self.assertIsNone(kv.get("nope"))

    def test_set_overwrites(self) -> None:
        with KeyValueStore(self.path) as kv:
            kv.set("a", "1")
            kv.set("a", "2")
            self.assertEqual(kv.get("a"), "2")

    def test_delete_existing_returns_true(self) -> None:
        with KeyValueStore(self.path) as kv:
            kv.set("a", "1")
            self.assertTrue(kv.delete("a"))
            self.assertIsNone(kv.get("a"))

    def test_delete_missing_returns_false(self) -> None:
        with KeyValueStore(self.path) as kv:
            self.assertFalse(kv.delete("ghost"))

    def test_contains_and_len_and_keys(self) -> None:
        with KeyValueStore(self.path) as kv:
            kv.set("a", "1")
            kv.set("b", "2")
            self.assertIn("a", kv)
            self.assertNotIn("missing", kv)
            self.assertEqual(len(kv), 2)
            self.assertEqual(set(kv.keys()), {"a", "b"})
            kv.delete("a")
            self.assertNotIn("a", kv)
            self.assertEqual(len(kv), 1)

    def test_empty_string_key_and_value(self) -> None:
        with KeyValueStore(self.path) as kv:
            kv.set("", "")
            self.assertEqual(kv.get(""), "")

    def test_special_chars_roundtrip(self) -> None:
        tricky = "tab\there\nnew\rret\\back"
        with KeyValueStore(self.path) as kv:
            kv.set(tricky, tricky)
            self.assertEqual(kv.get(tricky), tricky)

    def test_unicode_roundtrip(self) -> None:
        with KeyValueStore(self.path) as kv:
            kv.set("ключ", "значение 🗝")
            self.assertEqual(kv.get("ключ"), "значение 🗝")

    def test_non_string_key_rejected(self) -> None:
        with KeyValueStore(self.path) as kv:
            with self.assertRaises(TypeError):
                kv.set(123, "v")  # type: ignore[arg-type]
            with self.assertRaises(TypeError):
                kv.get(123)  # type: ignore[arg-type]
            with self.assertRaises(TypeError):
                kv.delete(123)  # type: ignore[arg-type]

    def test_non_string_value_rejected(self) -> None:
        with KeyValueStore(self.path) as kv:
            with self.assertRaises(TypeError):
                kv.set("k", 5)  # type: ignore[arg-type]


class KeyValueStorePersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._tmp.name, "kv.log")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_state_survives_reopen(self) -> None:
        with KeyValueStore(self.path) as kv:
            kv.set("a", "1")
            kv.set("b", "2")
            kv.set("c", "3")
        with KeyValueStore(self.path) as kv2:
            self.assertEqual(kv2.get("a"), "1")
            self.assertEqual(kv2.get("b"), "2")
            self.assertEqual(kv2.get("c"), "3")
            self.assertEqual(len(kv2), 3)

    def test_delete_survives_reopen(self) -> None:
        with KeyValueStore(self.path) as kv:
            kv.set("a", "1")
            kv.delete("a")
        with KeyValueStore(self.path) as kv2:
            self.assertIsNone(kv2.get("a"))
            self.assertEqual(len(kv2), 0)

    def test_overwrite_survives_reopen(self) -> None:
        with KeyValueStore(self.path) as kv:
            kv.set("a", "first")
            kv.set("a", "second")
            kv.set("a", "third")
        with KeyValueStore(self.path) as kv2:
            self.assertEqual(kv2.get("a"), "third")

    def test_writes_across_two_sessions_persist(self) -> None:
        with KeyValueStore(self.path) as kv:
            kv.set("a", "1")
        with KeyValueStore(self.path) as kv2:
            kv2.set("b", "2")
        with KeyValueStore(self.path) as kv3:
            self.assertEqual(kv3.get("a"), "1")
            self.assertEqual(kv3.get("b"), "2")

    def test_missing_log_file_yields_empty_store(self) -> None:
        self.assertFalse(os.path.exists(self.path))
        with KeyValueStore(self.path) as kv:
            self.assertEqual(len(kv), 0)
            self.assertIsNone(kv.get("anything"))

    def test_creates_intermediate_directories(self) -> None:
        nested = os.path.join(self._tmp.name, "a", "b", "kv.log")
        with KeyValueStore(nested) as kv:
            kv.set("k", "v")
        with KeyValueStore(nested) as kv2:
            self.assertEqual(kv2.get("k"), "v")


class KeyValueStoreLogFormatTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._tmp.name, "kv.log")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _read_log(self) -> str:
        with open(self.path, "r", encoding="utf-8", newline="") as f:
            return f.read()

    def _write_log(self, contents: str) -> None:
        with open(self.path, "w", encoding="utf-8", newline="") as f:
            f.write(contents)

    def test_set_writes_expected_line(self) -> None:
        with KeyValueStore(self.path) as kv:
            kv.set("a", "1")
        self.assertEqual(self._read_log(), "SET\ta\t1\n")

    def test_delete_appends_del_line(self) -> None:
        with KeyValueStore(self.path) as kv:
            kv.set("a", "1")
            kv.delete("a")
        self.assertEqual(self._read_log(), "SET\ta\t1\nDEL\ta\n")

    def test_delete_of_missing_key_still_logged(self) -> None:
        with KeyValueStore(self.path) as kv:
            kv.delete("ghost")
        self.assertEqual(self._read_log(), "DEL\tghost\n")

    def test_escaping_in_log(self) -> None:
        with KeyValueStore(self.path) as kv:
            kv.set("a\tb", "c\nd\\e")
        self.assertEqual(self._read_log(), "SET\ta\\tb\tc\\nd\\\\e\n")

    def test_replay_with_escape_sequences(self) -> None:
        self._write_log("SET\ta\\tb\tc\\nd\\\\e\n")
        with KeyValueStore(self.path) as kv:
            self.assertEqual(kv.get("a\tb"), "c\nd\\e")

    def test_replay_rejects_unknown_op(self) -> None:
        self._write_log("FOO\tk\tv\n")
        with self.assertRaises(ValueError) as cm:
            KeyValueStore(self.path)
        self.assertIn("line 1", str(cm.exception))

    def test_replay_rejects_wrong_field_count_for_set(self) -> None:
        self._write_log("SET\tonlykey\n")
        with self.assertRaises(ValueError) as cm:
            KeyValueStore(self.path)
        self.assertIn("line 1", str(cm.exception))

    def test_replay_rejects_missing_trailing_newline(self) -> None:
        self._write_log("SET\ta\t1\nSET\tb\t2")
        with self.assertRaises(ValueError) as cm:
            KeyValueStore(self.path)
        self.assertIn("line 2", str(cm.exception))

    def test_replay_reports_correct_line_number(self) -> None:
        self._write_log("SET\ta\t1\nSET\tb\t2\nBOGUS\n")
        with self.assertRaises(ValueError) as cm:
            KeyValueStore(self.path)
        self.assertIn("line 3", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
