"""System catalog stored on page 0.

Page 0 of the database file is a SlottedPage; each slot holds one table's
metadata serialized in the format below.

Catalog tuple wire format (little-endian):

    [name_len: u16][name: utf-8 bytes]
    [first_page_id: u32]
    [num_columns: u16]
      repeated num_columns times:
        [col_name_len: u16][col_name: utf-8 bytes]
        [col_type: u8]                  # DataType.value
"""

import struct
from dataclasses import dataclass
from typing import Iterator, List, Optional, Tuple

from DiskManager import DiskManager
from Schema import DataType, Schema
from SlottedPage import SLOT_SIZE, SlottedPage

_U16_MAX = 0xFFFF
_U32_MAX = 0xFFFFFFFF


@dataclass(frozen=True)
class ColumnDef:
    name: str
    type: DataType


@dataclass(frozen=True)
class TableInfo:
    name: str
    first_page_id: int
    columns: Tuple[ColumnDef, ...]

    @property
    def schema(self) -> Schema:
        return Schema([c.type for c in self.columns])


class Catalog:
    CATALOG_PAGE_ID = 0

    def __init__(self, disk_manager: DiskManager) -> None:
        self._dm = disk_manager

        if self._dm.num_pages == 0:
            pid = self._dm.allocate_page()
            if pid != self.CATALOG_PAGE_ID:
                raise AssertionError(
                    f"first allocated page was {pid}, expected {self.CATALOG_PAGE_ID}"
                )
            page = SlottedPage.new(page_id=self.CATALOG_PAGE_ID)
            self._dm.write_page(self.CATALOG_PAGE_ID, page.buffer)
            return

        page = self._load_page()
        if page.page_id != self.CATALOG_PAGE_ID:
            raise ValueError(
                f"page 0 has page_id={page.page_id}, expected {self.CATALOG_PAGE_ID}"
                f" — file does not look like a catalog database"
            )

    def create_table(self, name: str, columns: List[ColumnDef]) -> TableInfo:
        if not name:
            raise ValueError("table name cannot be empty")
        if not columns:
            raise ValueError("table must have at least one column")
        if self.get_table(name) is not None:
            raise ValueError(f"table {name!r} already exists")

        cols = tuple(columns)
        tuple_bytes = _serialize_table_info(
            TableInfo(name=name, first_page_id=0, columns=cols)
        )

        page = self._load_page()
        if len(tuple_bytes) + SLOT_SIZE > page.free_space:
            raise RuntimeError(
                "catalog page is full — multi-page catalog not implemented"
            )

        first_page_id = self._dm.allocate_page()
        data_page = SlottedPage.new(page_id=first_page_id)
        self._dm.write_page(first_page_id, data_page.buffer)

        info = TableInfo(name=name, first_page_id=first_page_id, columns=cols)
        tuple_bytes = _serialize_table_info(info)
        slot_id = page.insert(tuple_bytes)
        assert slot_id is not None  # capacity was verified above
        self._dm.write_page(self.CATALOG_PAGE_ID, page.buffer)
        return info

    def get_table(self, name: str) -> Optional[TableInfo]:
        for _, info in self._iter_table_infos():
            if info.name == name:
                return info
        return None

    def list_tables(self) -> List[TableInfo]:
        return [info for _, info in self._iter_table_infos()]

    def drop_table(self, name: str) -> bool:
        """Remove `name` from the catalog. Returns True if removed, False if absent.

        TODO: Data pages owned by the dropped table are NOT reclaimed — they stay allocated in the file as dead space.
        """
        page = self._load_page()
        for slot_id, data in page.iter_tuples():
            info = _deserialize_table_info(data)
            if info.name == name:
                page.delete(slot_id)
                self._dm.write_page(self.CATALOG_PAGE_ID, page.buffer)
                return True
        return False

    def _load_page(self) -> SlottedPage:
        raw = self._dm.read_page(self.CATALOG_PAGE_ID)
        return SlottedPage(bytearray(raw))

    def _iter_table_infos(self) -> Iterator[Tuple[int, TableInfo]]:
        page = self._load_page()
        for slot_id, data in page.iter_tuples():
            yield slot_id, _deserialize_table_info(data)


def _serialize_table_info(info: TableInfo) -> bytes:
    name_bytes = info.name.encode("utf-8")
    if len(name_bytes) > _U16_MAX:
        raise ValueError(f"table name encoded length {len(name_bytes)} > {_U16_MAX}")
    if info.first_page_id < 0 or info.first_page_id > _U32_MAX:
        raise ValueError(f"first_page_id {info.first_page_id} out of uint32 range")
    if len(info.columns) > _U16_MAX:
        raise ValueError(f"too many columns ({len(info.columns)} > {_U16_MAX})")

    parts: List[bytes] = [
        struct.pack("<H", len(name_bytes)),
        name_bytes,
        struct.pack("<I", info.first_page_id),
        struct.pack("<H", len(info.columns)),
    ]
    for col in info.columns:
        col_name_bytes = col.name.encode("utf-8")
        if len(col_name_bytes) > _U16_MAX:
            raise ValueError(
                f"column name {col.name!r} encoded length {len(col_name_bytes)} > {_U16_MAX}"
            )
        parts.append(struct.pack("<H", len(col_name_bytes)))
        parts.append(col_name_bytes)
        parts.append(struct.pack("<B", int(col.type)))
    return b"".join(parts)


def _deserialize_table_info(data: bytes) -> TableInfo:
    offset = 0
    n = len(data)

    def need(k: int) -> None:
        if offset + k > n:
            raise ValueError(
                f"truncated catalog tuple at offset {offset}, need {k} bytes, have {n - offset}"
            )

    need(2)
    (name_len,) = struct.unpack_from("<H", data, offset)
    offset += 2
    need(name_len)
    name = data[offset: offset + name_len].decode("utf-8")
    offset += name_len

    need(4)
    (first_page_id,) = struct.unpack_from("<I", data, offset)
    offset += 4

    need(2)
    (num_cols,) = struct.unpack_from("<H", data, offset)
    offset += 2

    columns: List[ColumnDef] = []
    for _ in range(num_cols):
        need(2)
        (cn_len,) = struct.unpack_from("<H", data, offset)
        offset += 2
        need(cn_len)
        col_name = data[offset: offset + cn_len].decode("utf-8")
        offset += cn_len
        need(1)
        type_byte = data[offset]
        offset += 1
        try:
            col_type = DataType(type_byte)
        except ValueError as e:
            raise ValueError(f"unknown DataType value {type_byte}") from e
        columns.append(ColumnDef(name=col_name, type=col_type))

    if offset != n:
        raise ValueError(
            f"trailing bytes in catalog tuple: consumed {offset}, total {n}"
        )

    return TableInfo(
        name=name,
        first_page_id=first_page_id,
        columns=tuple(columns),
    )
