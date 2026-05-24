"""Append-only key-value store with log replay

All SET and DELETE operations are appended to a text log file. On open, the
log is replayed line-by-line to reconstruct the in-memory state.

Wire format (UTF-8, LF-terminated, one record per line):

    SET<TAB>escaped_key<TAB>escaped_value\n
    DEL<TAB>escaped_key\n

Escaping (applied to keys and values before writing, reversed on replay):

    \\  -> \\\\
    \\t -> \\t   (literal backslash + 't')
    \\n -> \\n
    \\r -> \\r

A line that doesn't begin with ``SET\\t`` or ``DEL\\t``, has the wrong number
of fields, or lacks a trailing newline raises ``ValueError`` during replay.
"""

import os
from typing import Dict, Iterator, Optional, TextIO


_OP_SET = "SET"
_OP_DEL = "DEL"


def _escape(s: str) -> str:
    return (
        s.replace("\\", "\\\\")
        .replace("\t", "\\t")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )


def _unescape(s: str) -> str:
    out: list = []
    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if c == "\\":
            if i + 1 >= n:
                raise ValueError(f"dangling escape in field: {s!r}")
            nxt = s[i + 1]
            if nxt == "\\":
                out.append("\\")
            elif nxt == "t":
                out.append("\t")
            elif nxt == "n":
                out.append("\n")
            elif nxt == "r":
                out.append("\r")
            else:
                seq = "\\" + nxt
                raise ValueError(f"unknown escape {seq!r} in field: {s!r}")
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


class KeyValueStore:
    def __init__(self, log_path: str) -> None:
        self._path: str = log_path

        parent = os.path.dirname(log_path)
        if parent:
            os.makedirs(parent, exist_ok=True)

        self._data: Dict[str, str] = {}
        if os.path.exists(log_path):
            self._replay()

        self._f: TextIO = open(log_path, "a", encoding="utf-8", newline="")

    def _replay(self) -> None:
        with open(self._path, "r", encoding="utf-8", newline="") as f:
            for lineno, raw in enumerate(f, start=1):
                if not raw.endswith("\n"):
                    raise ValueError(
                        f"corrupt log record at line {lineno}: "
                        f"missing trailing newline: {raw!r}"
                    )
                line = raw[:-1]
                if line.startswith(_OP_SET + "\t"):
                    parts = line.split("\t", 2)
                    if len(parts) != 3:
                        raise ValueError(
                            f"corrupt log record at line {lineno}: "
                            f"SET expects 2 fields, got {len(parts) - 1}: {raw!r}"
                        )
                    key = _unescape(parts[1])
                    value = _unescape(parts[2])
                    self._data[key] = value
                elif line.startswith(_OP_DEL + "\t"):
                    parts = line.split("\t", 1)
                    if len(parts) != 2:
                        raise ValueError(
                            f"corrupt log record at line {lineno}: "
                            f"DEL expects 1 field, got {len(parts) - 1}: {raw!r}"
                        )
                    key = _unescape(parts[1])
                    self._data.pop(key, None)
                else:
                    raise ValueError(
                        f"corrupt log record at line {lineno}: "
                        f"unknown op: {raw!r}"
                    )

    def set(self, key: str, value: str) -> None:
        if not isinstance(key, str):
            raise TypeError(f"key must be str, got {type(key).__name__}")
        if not isinstance(value, str):
            raise TypeError(f"value must be str, got {type(value).__name__}")
        self._f.write(f"{_OP_SET}\t{_escape(key)}\t{_escape(value)}\n")
        self._f.flush()
        self._data[key] = value

    def get(self, key: str) -> Optional[str]:
        if not isinstance(key, str):
            raise TypeError(f"key must be str, got {type(key).__name__}")
        return self._data.get(key)

    def delete(self, key: str) -> bool:
        if not isinstance(key, str):
            raise TypeError(f"key must be str, got {type(key).__name__}")
        self._f.write(f"{_OP_DEL}\t{_escape(key)}\n")
        self._f.flush()
        existed = key in self._data
        if existed:
            del self._data[key]
        return existed

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and key in self._data

    def __len__(self) -> int:
        return len(self._data)

    def keys(self) -> Iterator[str]:
        return iter(list(self._data.keys()))

    def close(self) -> None:
        if not self._f.closed:
            self._f.close()

    def __enter__(self) -> "KeyValueStore":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
