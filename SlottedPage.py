"""Slotted page layout (PAGE_SIZE = 4096 bytes).

    +---------------------------------------------------+ offset 0
    | HEADER (12 bytes)                                 |
    |   page_id        : uint32   bytes [0..4)          |
    |   next_page_id   : uint32   bytes [4..8)          |
    |   num_slots      : uint16   bytes [8..10)         |
    |   free_space_end : uint16   bytes [10..12)        |
    +---------------------------------------------------+ offset 12
    | SLOT 0 (4 bytes): offset:uint16, length:uint16    |
    | SLOT 1                                            |
    | ...                                (grows down)   |
    +---------------------------------------------------+
    |                                                   |
    |        FREE SPACE                                 |
    |                                                   |
    +---------------------------------------------------+ <- free_space_end
    |                                ...tuple N bytes   |
    |                                   tuple 1 bytes   |   (grows up)
    |                                   tuple 0 bytes   |
    +---------------------------------------------------+ offset PAGE_SIZE

The slot array grows down from the header; tuple bytes grow up from the end of
the page. `free_space_end` is the offset of the lowest live tuple (== PAGE_SIZE
when the page is empty). A slot with length == 0 is a tombstone; slot ids are
never reused or reordered so (page_id, slot_id) is a stable RID.
"""

import struct
from typing import Iterator, Optional, Tuple

from DiskManager import PAGE_SIZE

HEADER_SIZE = 12
SLOT_SIZE = 4
NO_NEXT_PAGE = 0xFFFFFFFF

_HEADER_FMT = "<IIHH"  # page_id, next_page_id, num_slots, free_space_end
_SLOT_FMT = "<HH"  # offset, length


class SlottedPage:
    def __init__(self, buffer: bytearray) -> None:
        if not isinstance(buffer, bytearray):
            raise TypeError("buffer must be a bytearray")
        if len(buffer) != PAGE_SIZE:
            raise ValueError(
                f"buffer must be exactly {PAGE_SIZE} bytes, got {len(buffer)}"
            )
        self._buf: bytearray = buffer

    @classmethod
    def new(cls, page_id: int) -> "SlottedPage":
        buf = bytearray(PAGE_SIZE)
        struct.pack_into(_HEADER_FMT, buf, 0, page_id, NO_NEXT_PAGE, 0, PAGE_SIZE)
        return cls(buf)

    # --- header accessors ---

    @property
    def page_id(self) -> int:
        return struct.unpack_from("<I", self._buf, 0)[0]

    @property
    def next_page_id(self) -> int:
        return struct.unpack_from("<I", self._buf, 4)[0]

    @next_page_id.setter
    def next_page_id(self, value: int) -> None:
        if value < 0 or value > 0xFFFFFFFF:
            raise ValueError(f"next_page_id out of uint32 range: {value}")
        struct.pack_into("<I", self._buf, 4, value)

    @property
    def num_slots(self) -> int:
        return struct.unpack_from("<H", self._buf, 8)[0]

    @property
    def _free_space_end(self) -> int:
        return struct.unpack_from("<H", self._buf, 10)[0]

    @property
    def free_space(self) -> int:
        return self._free_space_end - HEADER_SIZE - self.num_slots * SLOT_SIZE

    # --- tuple ops ---

    def insert(self, data: bytes) -> Optional[int]:
        if len(data) == 0:
            raise ValueError("cannot insert empty tuple")

        required = len(data) + SLOT_SIZE
        if required > self.free_space:
            return None

        num_slots = self.num_slots
        new_tuple_offset = self._free_space_end - len(data)

        self._buf[new_tuple_offset: new_tuple_offset + len(data)] = data

        slot_offset = HEADER_SIZE + num_slots * SLOT_SIZE
        struct.pack_into(_SLOT_FMT, self._buf, slot_offset, new_tuple_offset, len(data))

        struct.pack_into("<H", self._buf, 8, num_slots + 1)
        struct.pack_into("<H", self._buf, 10, new_tuple_offset)

        return num_slots

    def get(self, slot_id: int) -> Optional[bytes]:
        slot = self._read_slot(slot_id)
        if slot is None:
            return None
        offset, length = slot
        if length == 0:
            return None
        return bytes(self._buf[offset: offset + length])

    def update(self, slot_id: int, new_data: bytes) -> bool:
        """Overwrite an existing slot's tuple. Returns True on success, False
        if the new data doesn't fit in this page's free space. Raises for
        caller bugs (empty data, slot out of range, tombstoned slot).

        - new_data length ≤ old length: overwrite in place; trailing old bytes
          become dead.
        - new_data length > old length but fits in page free space: relocate to
          a new offset within the same page; old bytes become dead.
        - Otherwise: return False (page can't hold the larger row).
        """
        if len(new_data) == 0:
            raise ValueError("cannot update to empty tuple")

        slot = self._read_slot(slot_id)
        if slot is None:
            raise ValueError(f"slot {slot_id} out of range (num_slots={self.num_slots})")
        old_offset, old_length = slot
        if old_length == 0:
            raise ValueError(f"slot {slot_id} is tombstoned")

        slot_offset = HEADER_SIZE + slot_id * SLOT_SIZE

        if len(new_data) <= old_length:
            self._buf[old_offset : old_offset + len(new_data)] = new_data
            struct.pack_into(_SLOT_FMT, self._buf, slot_offset, old_offset, len(new_data))
            return True

        if len(new_data) > self.free_space:
            return False

        new_offset = self._free_space_end - len(new_data)
        self._buf[new_offset : new_offset + len(new_data)] = new_data
        struct.pack_into(_SLOT_FMT, self._buf, slot_offset, new_offset, len(new_data))
        struct.pack_into("<H", self._buf, 10, new_offset)
        return True

    def delete(self, slot_id: int) -> bool:
        slot = self._read_slot(slot_id)
        if slot is None:
            return False
        offset, length = slot
        if length == 0:
            return False
        slot_offset = HEADER_SIZE + slot_id * SLOT_SIZE
        struct.pack_into(_SLOT_FMT, self._buf, slot_offset, offset, 0)
        return True

    def iter_tuples(self) -> Iterator[Tuple[int, bytes]]:
        for slot_id in range(self.num_slots):
            data = self.get(slot_id)
            if data is not None:
                yield slot_id, data

    # --- raw buffer ---

    @property
    def buffer(self) -> bytes:
        return bytes(self._buf)

    # --- internals ---

    def _read_slot(self, slot_id: int) -> Optional[Tuple[int, int]]:
        if slot_id < 0 or slot_id >= self.num_slots:
            return None
        slot_offset = HEADER_SIZE + slot_id * SLOT_SIZE
        offset, length = struct.unpack_from(_SLOT_FMT, self._buf, slot_offset)
        return offset, length
