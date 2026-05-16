import unittest

from simple_dbms.schema import DataType, Schema


class DataTypeEnumTests(unittest.TestCase):
    def test_values_stable(self) -> None:
        self.assertEqual(int(DataType.INT), 1)
        self.assertEqual(int(DataType.TEXT), 2)
        self.assertEqual(int(DataType.BOOL), 3)


class RoundtripTests(unittest.TestCase):
    def _roundtrip(self, schema: Schema, values: tuple) -> None:
        data = schema.serialize(values)
        self.assertEqual(schema.deserialize(data), values)

    def test_int_min_max_zero_negative(self) -> None:
        s = Schema([DataType.INT])
        for v in (-(2 ** 31), -1, 0, 1, 2 ** 31 - 1):
            self._roundtrip(s, (v,))

    def test_bool(self) -> None:
        s = Schema([DataType.BOOL])
        self._roundtrip(s, (True,))
        self._roundtrip(s, (False,))

    def test_text_basic_empty_unicode(self) -> None:
        s = Schema([DataType.TEXT])
        for v in ("", "hello", "héllo "):
            self._roundtrip(s, (v,))

    def test_mixed_schema(self) -> None:
        s = Schema([DataType.INT, DataType.TEXT, DataType.BOOL])
        self._roundtrip(s, (7, "users", True))
        self._roundtrip(s, (-1, "", False))


class SerializeValidationTests(unittest.TestCase):
    def test_rejects_arity_mismatch(self) -> None:
        s = Schema([DataType.INT, DataType.TEXT])
        with self.assertRaises(ValueError):
            s.serialize((1,))
        with self.assertRaises(ValueError):
            s.serialize((1, "a", "extra"))

    def test_rejects_wrong_python_type(self) -> None:
        with self.assertRaises(TypeError):
            Schema([DataType.INT]).serialize(("not an int",))
        with self.assertRaises(TypeError):
            Schema([DataType.TEXT]).serialize((123,))
        with self.assertRaises(TypeError):
            Schema([DataType.BOOL]).serialize((1,))

    def test_rejects_bool_for_int(self) -> None:
        with self.assertRaises(TypeError):
            Schema([DataType.INT]).serialize((True,))

    def test_rejects_int_out_of_range(self) -> None:
        s = Schema([DataType.INT])
        with self.assertRaises(ValueError):
            s.serialize((2 ** 31,))
        with self.assertRaises(ValueError):
            s.serialize((-(2 ** 31) - 1,))

    def test_rejects_text_too_long(self) -> None:
        with self.assertRaises(ValueError):
            Schema([DataType.TEXT]).serialize(("x" * 65536,))

    def test_schema_rejects_non_datatype(self) -> None:
        with self.assertRaises(TypeError):
            Schema(["INT"])  # type: ignore[list-item]


class DeserializeValidationTests(unittest.TestCase):
    def test_rejects_trailing_bytes(self) -> None:
        with self.assertRaises(ValueError):
            Schema([DataType.INT]).deserialize(b"\x01\x00\x00\x00\xff")

    def test_rejects_truncated_int(self) -> None:
        with self.assertRaises(ValueError):
            Schema([DataType.INT]).deserialize(b"")
        with self.assertRaises(ValueError):
            Schema([DataType.INT]).deserialize(b"\x00\x00\x00")

    def test_rejects_truncated_text_length(self) -> None:
        with self.assertRaises(ValueError):
            Schema([DataType.TEXT]).deserialize(b"\x05")

    def test_rejects_truncated_text_body(self) -> None:
        # Says length=5 but only provides 2 bytes of body.
        with self.assertRaises(ValueError):
            Schema([DataType.TEXT]).deserialize(b"\x05\x00hi")

    def test_rejects_invalid_bool_byte(self) -> None:
        with self.assertRaises(ValueError):
            Schema([DataType.BOOL]).deserialize(b"\x02")


if __name__ == "__main__":
    unittest.main()
