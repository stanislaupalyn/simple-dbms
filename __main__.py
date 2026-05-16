import sys

from Database import Database
from Repl import run_repl

_DEFAULT_DB_PATH = "data/simple.db"

def main() -> None:
    if len(sys.argv) > 2:
        print("Usage: python3 __main__.py <path-to-database>", file=sys.stderr)
        sys.exit(2)

    path = sys.argv[1] if len(sys.argv) == 2 else _DEFAULT_DB_PATH

    with Database(path) as db:
        run_repl(db)


if __name__ == "__main__":
    main()
