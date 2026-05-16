import os
from typing import BinaryIO

PAGE_SIZE = 4096


class DiskManager:
    def __init__(self, path: str) -> None:
        self._path: str = path

        if not os.path.exists(path):
            parent = os.path.dirname(path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            open(path, "wb").close()

        size = os.path.getsize(path)
        if size % PAGE_SIZE != 0:
            raise ValueError(
                f"file {path!r} has size {size} which is not a multiple of "
                f"PAGE_SIZE ({PAGE_SIZE}); refusing to open"
            )

        self._f: BinaryIO = open(path, "r+b")
        self._num_pages: int = size // PAGE_SIZE

    @property
    def num_pages(self) -> int:
        return self._num_pages

    def read_page(self, page_id: int) -> bytes:
        if page_id < 0:
            raise ValueError(f"page_id must be non-negative, got {page_id}")
        if page_id >= self._num_pages:
            raise ValueError(
                f"page_id {page_id} is out of range (num_pages={self._num_pages})"
            )

        self._f.seek(page_id * PAGE_SIZE)
        data = self._f.read(PAGE_SIZE)
        if len(data) != PAGE_SIZE:
            raise IOError(
                f"short read for page {page_id}: got {len(data)} bytes, "
                f"expected {PAGE_SIZE}"
            )
        return data

    def write_page(self, page_id: int, data: bytes) -> None:
        if page_id < 0:
            raise ValueError(f"page_id must be non-negative, got {page_id}")
        if len(data) != PAGE_SIZE:
            raise ValueError(
                f"page data must be exactly {PAGE_SIZE} bytes, got {len(data)}"
            )
        if page_id > self._num_pages:
            raise ValueError(
                f"page_id {page_id} would skip past end of file "
                f"(num_pages={self._num_pages}); use allocate_page() to extend"
            )

        self._f.seek(page_id * PAGE_SIZE)
        self._f.write(data)
        self._f.flush()

        if page_id == self._num_pages:
            self._num_pages += 1

    def allocate_page(self) -> int:
        page_id = self._num_pages
        self.write_page(page_id, b"\x00" * PAGE_SIZE)
        return page_id

    def close(self) -> None:
        if not self._f.closed:
            self._f.close()

    def __enter__(self) -> "DiskManager":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
