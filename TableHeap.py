"""Row-level API for a table: a linked list of slotted pages.

A table's pages are chained via the `next_page_id` field in each SlottedPage
header. The chain head is `TableInfo.first_page_id` (recorded in the catalog);
the tail is the page whose `next_page_id == NO_NEXT_PAGE`.

Strategy: strict tail-insert. New rows always go into the last page; if it's
full, a fresh page is allocated and linked. Space freed by deletes (tombstones)
is not reused by this layer.
"""

from typing import Iterator, NamedTuple, Optional, Tuple

from Catalog import TableInfo
from DiskManager import PAGE_SIZE, DiskManager
from SlottedPage import HEADER_SIZE, NO_NEXT_PAGE, SLOT_SIZE, SlottedPage

MAX_ROW_BYTES = PAGE_SIZE - HEADER_SIZE - SLOT_SIZE


class RID(NamedTuple):
    page_id: int
    slot_id: int


class TableHeap:
    def __init__(self, disk_manager: DiskManager, table_info: TableInfo) -> None:
        self._dm = disk_manager
        self._info = table_info
        self._schema = table_info.schema

    @property
    def info(self) -> TableInfo:
        return self._info

    def insert(self, values: tuple) -> RID:
        data = self._schema.serialize(values)
        if len(data) > MAX_ROW_BYTES:
            raise ValueError(
                f"serialized row is {len(data)} bytes, exceeds max {MAX_ROW_BYTES} "
                f"(overflow pages not supported)"
            )

        tail_page_id, tail_page = self._load_tail()

        slot_id = tail_page.insert(data)
        if slot_id is not None:
            self._dm.write_page(tail_page_id, tail_page.buffer)
            return RID(tail_page_id, slot_id)

        # Tail is full — allocate a new page and link it.
        new_page_id = self._dm.allocate_page()
        new_page = SlottedPage.new(page_id=new_page_id)
        new_slot_id = new_page.insert(data)
        assert new_slot_id is not None  # size was checked above
        self._dm.write_page(new_page_id, new_page.buffer)

        tail_page.next_page_id = new_page_id
        self._dm.write_page(tail_page_id, tail_page.buffer)
        return RID(new_page_id, new_slot_id)

    def get(self, rid: RID) -> Optional[tuple]:
        page = self._load_page(rid.page_id)
        data = page.get(rid.slot_id)
        if data is None:
            return None
        return self._schema.deserialize(data)

    def update(self, rid: RID, new_values: tuple) -> RID:
        """Update the row at `rid`. Returns the row's RID after the update.

        The returned RID equals the original `rid` when the new row fits in
        `rid.page_id` (in-place update). When it doesn't fit, the old slot is
        tombstoned and the row is re-inserted via the normal tail-insert path,
        yielding a NEW RID. Callers tracking RIDs (e.g. indexes) must use the
        returned value going forward.
        """
        data = self._schema.serialize(new_values)
        if len(data) > MAX_ROW_BYTES:
            raise ValueError(
                f"serialized row is {len(data)} bytes, exceeds max {MAX_ROW_BYTES}"
            )

        page = self._load_page(rid.page_id)
        if page.update(rid.slot_id, data):
            self._dm.write_page(rid.page_id, page.buffer)
            return rid

        # No room in the original page — tombstone and re-insert.
        # SlottedPage.update returning False means the slot was valid (it raises
        # for invalid/tombstoned), so this delete must succeed.
        assert page.delete(rid.slot_id)
        self._dm.write_page(rid.page_id, page.buffer)
        return self.insert(new_values)

    def delete(self, rid: RID) -> bool:
        page = self._load_page(rid.page_id)
        if not page.delete(rid.slot_id):
            return False
        self._dm.write_page(rid.page_id, page.buffer)
        return True

    def scan(self) -> Iterator[Tuple[RID, tuple]]:
        page_id = self._info.first_page_id
        while page_id != NO_NEXT_PAGE:
            page = self._load_page(page_id)
            for slot_id, data in page.iter_tuples():
                yield RID(page_id, slot_id), self._schema.deserialize(data)
            page_id = page.next_page_id

    def _load_page(self, page_id: int) -> SlottedPage:
        return SlottedPage(bytearray(self._dm.read_page(page_id)))

    def _load_tail(self) -> Tuple[int, SlottedPage]:
        page_id = self._info.first_page_id
        page = self._load_page(page_id)
        while page.next_page_id != NO_NEXT_PAGE:
            page_id = page.next_page_id
            page = self._load_page(page_id)
        return page_id, page
