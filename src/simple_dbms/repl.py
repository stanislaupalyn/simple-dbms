"""Interactive REPL for simple-dbms.

Reads one SQL statement per line from `in_stream`, executes it against the
provided `Database`, and writes the rendered result to `out_stream`. Parse and
runtime errors are printed and the loop continues. EOF on stdin or an EXIT
statement breaks the loop.
"""

import sys
from typing import IO, List

from simple_dbms.database import Database
from simple_dbms.sql import (
    CountResult,
    ExitResult,
    ParseError,
    Result,
    SelectResult,
    StatusResult,
    execute,
    parse,
)

_PROMPT = "sql> "
_BANNER = "simple-dbms REPL. Type HELP; for help, EXIT; to quit."
_FAREWELL = "Goodbye."


def run_repl(
    db: Database,
    in_stream: IO[str] = sys.stdin,
    out_stream: IO[str] = sys.stdout,
) -> None:
    out_stream.write(_BANNER + "\n")
    while True:
        out_stream.write(_PROMPT)
        out_stream.flush()
        line = in_stream.readline()
        if not line:                 # EOF
            out_stream.write("\n")
            break
        line = line.strip()
        if not line:
            continue

        try:
            stmt = parse(line)
        except ParseError as e:
            out_stream.write(f"Parse error: {e}\n")
            continue

        try:
            result = execute(stmt, db)
        except (ValueError, TypeError) as e:
            out_stream.write(f"Error: {e}\n")
            continue

        if isinstance(result, ExitResult):
            break
        out_stream.write(format_result(result) + "\n")

    out_stream.write(_FAREWELL + "\n")


def format_result(result: Result) -> str:
    if isinstance(result, SelectResult):
        return format_table(result.columns, result.rows)
    if isinstance(result, CountResult):
        suffix = "" if result.count == 1 else "s"
        return f"{result.count} row{suffix} {result.verb}"
    if isinstance(result, StatusResult):
        return result.message
    raise AssertionError(f"unhandled result type: {type(result).__name__}")


def format_table(columns: List[str], rows: List[tuple]) -> str:
    widths = [len(c) for c in columns]
    str_rows = [tuple(str(v) for v in row) for row in rows]
    for row in str_rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    header = " | ".join(c.ljust(w) for c, w in zip(columns, widths))
    separator = "-+-".join("-" * w for w in widths)
    body = [
        " | ".join(cell.ljust(w) for cell, w in zip(row, widths))
        for row in str_rows
    ]
    count_line = f"({len(rows)} row{'' if len(rows) == 1 else 's'})"
    return "\n".join([header, separator, *body, count_line])
