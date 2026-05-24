# simple-dbms

A simple database management system. 

Constructor University Bremen Database course homework assignment 

## Running the REPL

Use the following command:

```bash
uv run python3 -m simple_dbms
```

This will start the REPL using the default database path (`data/simple.db`).

To use a specific database file, pass the path as an argument:

```bash
uv run python3 -m simple_dbms <path-to-database>
```

Inside the REPL, you can execute SQL commands. Type `HELP;` for help, and `EXIT;` to quit.

## Append-only key-value store (HW7)

`simple_dbms.kv_store` provides a standalone `KeyValueStore` that appends every `SET` and `DELETE` to a text log file and reconstructs state by replaying the log on open. It is independent of the page-based DBMS above.
It supports only strings.

```python
from simple_dbms.kv_store import KeyValueStore

with KeyValueStore("data/kv.log") as kv:
    kv.set("a", "1")
    kv.set("b", "2")
    kv.delete("a")

with KeyValueStore("data/kv.log") as kv:
    assert kv.get("a") is None
    assert kv.get("b") == "2"
```

The log is human-readable: one record per line, `SET<TAB>key<TAB>value` or `DEL<TAB>key`, with tabs/newlines/backslashes in keys and values backslash-escaped.

## Running Tests

To run the project tests, use the following command:

```bash
uv run python3 -m unittest discover tests
```
