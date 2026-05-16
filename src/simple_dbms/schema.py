"""Tuple serializer with a fixed set of primitive types.

Wire format: fields packed back-to-back in schema order. No header, no padding,
no null bits.

    INT  -> 4 bytes, little-endian, signed (int32). struct format '<i'.
    BOOL -> 1 byte: 0x00 = False, 0x01 = True. Other values rejected on read.
    TEXT -> 2-byte length prefix (uint16 LE), then N UTF-8 bytes (N <= 65535).
"""

import struct
from enum import IntEnum
from typing import List, Tuple

_INT32_MIN = -(2 ** 31)
_INT32_MAX = 2 ** 31 - 1
_TEXT_MAX_BYTES = 0xFFFF


class DataType(IntEnum):
    # Integer values are the on-disk encoding used by catalog tuples
    INT = 1
    TEXT = 2
    BOOL = 3


class Schema:
    def __init__(self, columns: List[DataType]) -> None:
        cols = tuple(columns)
        for i, c in enumerate(cols):
            if not isinstance(c, DataType):
                raise TypeError(
                    f"column {i}: expected DataType, got {type(c).__name__}"
                )
        self._columns: Tuple[DataType, ...] = cols

    @property
    def num_columns(self) -> int:
        return len(self._columns)

    @property
    def columns(self) -> Tuple[DataType, ...]:
        return self._columns

    def serialize(self, values: tuple) -> bytes:
        if len(values) != len(self._columns):
            raise ValueError(
                f"expected {len(self._columns)} values, got {len(values)}"
            )

        parts: List[bytes] = []
        for i, (col_type, value) in enumerate(zip(self._columns, values)):
            if col_type is DataType.INT:
                # bool is a subclass of int in Python; reject it for strict typing.
                if isinstance(value, bool) or not isinstance(value, int):
                    raise TypeError(
                        f"column {i} (INT): expected int, got {type(value).__name__}"
                    )
                if value < _INT32_MIN or value > _INT32_MAX:
                    raise ValueError(
                        f"column {i} (INT): value {value} out of int32 range"
                    )
                parts.append(struct.pack("<i", value))

            elif col_type is DataType.BOOL:
                if not isinstance(value, bool):
                    raise TypeError(
                        f"column {i} (BOOL): expected bool, got {type(value).__name__}"
                    )
                parts.append(b"\x01" if value else b"\x00")

            elif col_type is DataType.TEXT:
                if not isinstance(value, str):
                    raise TypeError(
                        f"column {i} (TEXT): expected str, got {type(value).__name__}"
                    )
                encoded = value.encode("utf-8")
                if len(encoded) > _TEXT_MAX_BYTES:
                    raise ValueError(
                        f"column {i} (TEXT): encoded length {len(encoded)} "
                        f"exceeds max {_TEXT_MAX_BYTES}"
                    )
                parts.append(struct.pack("<H", len(encoded)) + encoded)

            else:
                raise AssertionError(f"unhandled DataType: {col_type!r}")

        return b"".join(parts)

    def deserialize(self, data: bytes) -> tuple:
        offset = 0
        n = len(data)
        out: List[object] = []

        for i, col_type in enumerate(self._columns):
            if col_type is DataType.INT:
                if offset + 4 > n:
                    raise ValueError(
                        f"column {i} (INT): truncated, need 4 bytes at offset {offset}"
                    )
                (value,) = struct.unpack_from("<i", data, offset)
                offset += 4
                out.append(value)

            elif col_type is DataType.BOOL:
                if offset + 1 > n:
                    raise ValueError(
                        f"column {i} (BOOL): truncated, need 1 byte at offset {offset}"
                    )
                byte = data[offset]
                offset += 1
                if byte == 0x00:
                    out.append(False)
                elif byte == 0x01:
                    out.append(True)
                else:
                    raise ValueError(
                        f"column {i} (BOOL): invalid byte 0x{byte:02x}"
                    )

            elif col_type is DataType.TEXT:
                if offset + 2 > n:
                    raise ValueError(
                        f"column {i} (TEXT): truncated length prefix at offset {offset}"
                    )
                (length,) = struct.unpack_from("<H", data, offset)
                offset += 2
                if offset + length > n:
                    raise ValueError(
                        f"column {i} (TEXT): truncated body, want {length} bytes "
                        f"at offset {offset}, have {n - offset}"
                    )
                out.append(data[offset : offset + length].decode("utf-8"))
                offset += length

            else:
                raise AssertionError(f"unhandled DataType: {col_type!r}")

        if offset != n:
            raise ValueError(
                f"trailing bytes after deserialization: consumed {offset}, "
                f"total {n}"
            )

        return tuple(out)
