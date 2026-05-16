"""Database façade — bundles DiskManager, Catalog, and TableHeap behind a
SQL-shaped programmatic API.

Operations:
    create_table, drop_table, list_tables
    insert(table, values)
    select(table, columns=..., where=...)
    update(table, set_values=..., where=...)
    delete(table, where=...)

"""

from typing import Callable, Dict, Iterator, List, Optional, Tuple

from simple_dbms.catalog import Catalog, ColumnDef, TableInfo
from simple_dbms.disk_manager import DiskManager
from simple_dbms.table_heap import RID, TableHeap

Where = Optional[Dict[str, object]]   # {col_name: expected_value, ...} ANDed


class Database:
    def __init__(self, path: str) -> None:
        self._dm = DiskManager(path)
        self._cat = Catalog(self._dm)

    def close(self) -> None:
        self._dm.close()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # --- DDL ---

    def create_table(self, name: str, columns: List[ColumnDef]) -> None:
        self._cat.create_table(name, columns)

    def drop_table(self, name: str) -> bool:
        return self._cat.drop_table(name)

    def list_tables(self) -> List[str]:
        return [t.name for t in self._cat.list_tables()]

    def table_info(self, name: str) -> Optional[TableInfo]:
        return self._cat.get_table(name)

    # --- DML ---

    def insert(self, table: str, values: tuple) -> RID:
        return self._heap(table).insert(tuple(values))

    def select(
            self,
            table: str,
            columns: Optional[List[str]] = None,
            where: Where = None,
    ) -> Iterator[tuple]:
        heap = self._heap(table)
        proj_indexes = self._resolve_projection(heap.info, columns)
        pred = self._make_predicate(heap.info, where)
        for _rid, row in heap.scan():
            if pred(row):
                yield tuple(row[i] for i in proj_indexes)

    def update(
            self,
            table: str,
            set_values: Dict[str, object],
            where: Where = None,
    ) -> int:
        heap = self._heap(table)
        set_indexes: Dict[int, object] = {
            self._resolve_column(heap.info, col): val
            for col, val in set_values.items()
        }
        pred = self._make_predicate(heap.info, where)

        matched: List[Tuple[RID, tuple]] = [
            (rid, row) for rid, row in heap.scan() if pred(row)
        ]
        for rid, row in matched:
            new_row = list(row)
            for idx, val in set_indexes.items():
                new_row[idx] = val
            heap.update(rid, tuple(new_row))
        return len(matched)

    def delete(self, table: str, where: Where = None) -> int:
        heap = self._heap(table)
        pred = self._make_predicate(heap.info, where)
        matched_rids: List[RID] = [rid for rid, row in heap.scan() if pred(row)]
        for rid in matched_rids:
            heap.delete(rid)
        return len(matched_rids)

    # --- helpers ---

    def _heap(self, table: str) -> TableHeap:
        info = self._cat.get_table(table)
        if info is None:
            raise ValueError(f"table {table!r} does not exist")
        return TableHeap(self._dm, info)

    @staticmethod
    def _resolve_column(info: TableInfo, name: str) -> int:
        for i, c in enumerate(info.columns):
            if c.name == name:
                return i
        raise ValueError(f"column {name!r} not in table {info.name!r}")

    def _resolve_projection(
            self, info: TableInfo, columns: Optional[List[str]]
    ) -> List[int]:
        if columns is None:
            return list(range(len(info.columns)))
        return [self._resolve_column(info, c) for c in columns]

    def _make_predicate(
            self, info: TableInfo, where: Where
    ) -> Callable[[tuple], bool]:
        if not where:                       # None OR empty dict → no filter
            return lambda _row: True
        conditions: List[Tuple[int, object]] = [
            (self._resolve_column(info, col), val) for col, val in where.items()
        ]
        return lambda row: all(row[i] == v for i, v in conditions)
