"""SQL tokenizer, parser, and executor for the simple-dbms REPL.

Supported grammar (case-insensitive keywords; optional trailing semicolon):

    create_table  := CREATE TABLE ident '(' col_def (',' col_def)* ')'
    col_def       := ident (INT | TEXT | BOOL)
    drop_table    := DROP TABLE ident
    show_tables   := SHOW TABLES
    insert        := INSERT INTO ident VALUES '(' value (',' value)* ')'
    select        := SELECT ('*' | ident (',' ident)*) FROM ident [where]
    update        := UPDATE ident SET assignment (',' assignment)* [where]
    delete        := DELETE FROM ident [where]
    where         := WHERE cond (AND cond)*
    cond          := ident '=' value
    value         := INT_LIT | '-' INT_LIT | STRING_LIT | TRUE | FALSE
    exit          := EXIT
    help          := HELP

Strings are single-quoted with no escapes. Identifiers are [A-Za-z_][A-Za-z0-9_]*.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple, Union

from Catalog import ColumnDef
from Database import Database
from Schema import DataType


class ParseError(Exception):
    pass


# --------------------------------------------------------------------------
# Tokens
# --------------------------------------------------------------------------


class TokenType(Enum):
    KEYWORD = "KEYWORD"
    IDENT = "IDENT"
    INT_LIT = "INT_LIT"
    STRING_LIT = "STRING_LIT"
    LPAREN = "LPAREN"
    RPAREN = "RPAREN"
    COMMA = "COMMA"
    SEMI = "SEMI"
    STAR = "STAR"
    EQ = "EQ"
    MINUS = "MINUS"
    EOF = "EOF"


@dataclass
class Token:
    type: TokenType
    text: str


KEYWORDS = frozenset({
    "CREATE", "TABLE", "DROP", "SHOW", "TABLES",
    "INSERT", "INTO", "VALUES",
    "SELECT", "FROM", "WHERE", "AND",
    "UPDATE", "SET",
    "DELETE",
    "INT", "TEXT", "BOOL",
    "TRUE", "FALSE",
    "EXIT", "HELP",
})

_TYPE_KEYWORDS: Dict[str, DataType] = {
    "INT": DataType.INT,
    "TEXT": DataType.TEXT,
    "BOOL": DataType.BOOL,
}


def tokenize(source: str) -> List[Token]:
    tokens: List[Token] = []
    i = 0
    n = len(source)
    while i < n:
        ch = source[i]

        if ch.isspace():
            i += 1
            continue

        if ch == "(":
            tokens.append(Token(TokenType.LPAREN, "(")); i += 1; continue
        if ch == ")":
            tokens.append(Token(TokenType.RPAREN, ")")); i += 1; continue
        if ch == ",":
            tokens.append(Token(TokenType.COMMA, ",")); i += 1; continue
        if ch == ";":
            tokens.append(Token(TokenType.SEMI, ";")); i += 1; continue
        if ch == "*":
            tokens.append(Token(TokenType.STAR, "*")); i += 1; continue
        if ch == "=":
            tokens.append(Token(TokenType.EQ, "=")); i += 1; continue
        if ch == "-":
            tokens.append(Token(TokenType.MINUS, "-")); i += 1; continue

        if ch == "'":
            end = source.find("'", i + 1)
            if end == -1:
                raise ParseError(f"unterminated string starting at position {i}")
            tokens.append(Token(TokenType.STRING_LIT, source[i + 1 : end]))
            i = end + 1
            continue

        if ch.isdigit():
            j = i
            while j < n and source[j].isdigit():
                j += 1
            tokens.append(Token(TokenType.INT_LIT, source[i:j]))
            i = j
            continue

        if ch.isalpha() or ch == "_":
            j = i
            while j < n and (source[j].isalnum() or source[j] == "_"):
                j += 1
            word = source[i:j]
            upper = word.upper()
            if upper in KEYWORDS:
                tokens.append(Token(TokenType.KEYWORD, upper))
            else:
                tokens.append(Token(TokenType.IDENT, word))
            i = j
            continue

        raise ParseError(f"unexpected character {ch!r} at position {i}")

    tokens.append(Token(TokenType.EOF, ""))
    return tokens


# --------------------------------------------------------------------------
# AST
# --------------------------------------------------------------------------


@dataclass
class CreateTableStmt:
    name: str
    columns: List[Tuple[str, DataType]]


@dataclass
class DropTableStmt:
    name: str


@dataclass
class ShowTablesStmt:
    pass


@dataclass
class InsertStmt:
    table: str
    values: Tuple[object, ...]


@dataclass
class SelectStmt:
    table: str
    columns: Optional[List[str]]  # None means SELECT *
    where: Dict[str, object] = field(default_factory=dict)


@dataclass
class UpdateStmt:
    table: str
    set_values: Dict[str, object]
    where: Dict[str, object] = field(default_factory=dict)


@dataclass
class DeleteStmt:
    table: str
    where: Dict[str, object] = field(default_factory=dict)


@dataclass
class ExitStmt:
    pass


@dataclass
class HelpStmt:
    pass


Stmt = Union[
    CreateTableStmt, DropTableStmt, ShowTablesStmt,
    InsertStmt, SelectStmt, UpdateStmt, DeleteStmt,
    ExitStmt, HelpStmt,
]


# --------------------------------------------------------------------------
# Parser
# --------------------------------------------------------------------------


class _Parser:
    def __init__(self, tokens: List[Token]) -> None:
        self._tokens = tokens
        self._pos = 0

    def _peek(self) -> Token:
        return self._tokens[self._pos]

    def _advance(self) -> Token:
        t = self._tokens[self._pos]
        self._pos += 1
        return t

    def _expect(self, ttype: TokenType, text: Optional[str] = None) -> Token:
        t = self._peek()
        if t.type != ttype or (text is not None and t.text != text):
            want = text if text is not None else ttype.value
            raise ParseError(f"expected {want}, got {t.type.value} {t.text!r}")
        return self._advance()

    def _accept(self, ttype: TokenType, text: Optional[str] = None) -> bool:
        t = self._peek()
        if t.type == ttype and (text is None or t.text == text):
            self._advance()
            return True
        return False

    def parse(self) -> Stmt:
        t = self._peek()
        if t.type != TokenType.KEYWORD:
            raise ParseError(f"expected keyword at start of statement, got {t.text!r}")

        stmt: Stmt
        if t.text == "CREATE":
            stmt = self._create_table()
        elif t.text == "DROP":
            stmt = self._drop_table()
        elif t.text == "SHOW":
            stmt = self._show_tables()
        elif t.text == "INSERT":
            stmt = self._insert()
        elif t.text == "SELECT":
            stmt = self._select()
        elif t.text == "UPDATE":
            stmt = self._update()
        elif t.text == "DELETE":
            stmt = self._delete()
        elif t.text == "EXIT":
            self._advance()
            stmt = ExitStmt()
        elif t.text == "HELP":
            self._advance()
            stmt = HelpStmt()
        else:
            raise ParseError(f"unsupported statement starting with {t.text!r}")

        # Optional trailing semicolon, then EOF.
        self._accept(TokenType.SEMI)
        if self._peek().type != TokenType.EOF:
            tail = self._peek()
            raise ParseError(f"unexpected trailing token {tail.text!r}")
        return stmt

    # --- statement parsers ---

    def _create_table(self) -> CreateTableStmt:
        self._expect(TokenType.KEYWORD, "CREATE")
        self._expect(TokenType.KEYWORD, "TABLE")
        name = self._expect(TokenType.IDENT).text
        self._expect(TokenType.LPAREN)
        columns: List[Tuple[str, DataType]] = [self._column_def()]
        while self._accept(TokenType.COMMA):
            columns.append(self._column_def())
        self._expect(TokenType.RPAREN)
        return CreateTableStmt(name=name, columns=columns)

    def _column_def(self) -> Tuple[str, DataType]:
        col = self._expect(TokenType.IDENT).text
        type_tok = self._expect(TokenType.KEYWORD)
        if type_tok.text not in _TYPE_KEYWORDS:
            raise ParseError(f"unsupported column type {type_tok.text!r}")
        return col, _TYPE_KEYWORDS[type_tok.text]

    def _drop_table(self) -> DropTableStmt:
        self._expect(TokenType.KEYWORD, "DROP")
        self._expect(TokenType.KEYWORD, "TABLE")
        return DropTableStmt(name=self._expect(TokenType.IDENT).text)

    def _show_tables(self) -> ShowTablesStmt:
        self._expect(TokenType.KEYWORD, "SHOW")
        self._expect(TokenType.KEYWORD, "TABLES")
        return ShowTablesStmt()

    def _insert(self) -> InsertStmt:
        self._expect(TokenType.KEYWORD, "INSERT")
        self._expect(TokenType.KEYWORD, "INTO")
        table = self._expect(TokenType.IDENT).text
        self._expect(TokenType.KEYWORD, "VALUES")
        self._expect(TokenType.LPAREN)
        values: List[object] = [self._value()]
        while self._accept(TokenType.COMMA):
            values.append(self._value())
        self._expect(TokenType.RPAREN)
        return InsertStmt(table=table, values=tuple(values))

    def _select(self) -> SelectStmt:
        self._expect(TokenType.KEYWORD, "SELECT")
        columns: Optional[List[str]]
        if self._accept(TokenType.STAR):
            columns = None
        else:
            columns = [self._expect(TokenType.IDENT).text]
            assert columns is not None
            while self._accept(TokenType.COMMA):
                columns.append(self._expect(TokenType.IDENT).text)
        self._expect(TokenType.KEYWORD, "FROM")
        table = self._expect(TokenType.IDENT).text
        where = self._optional_where()
        return SelectStmt(table=table, columns=columns, where=where)

    def _update(self) -> UpdateStmt:
        self._expect(TokenType.KEYWORD, "UPDATE")
        table = self._expect(TokenType.IDENT).text
        self._expect(TokenType.KEYWORD, "SET")
        set_values: Dict[str, object] = {}
        col, val = self._assignment()
        set_values[col] = val
        while self._accept(TokenType.COMMA):
            col, val = self._assignment()
            set_values[col] = val
        where = self._optional_where()
        return UpdateStmt(table=table, set_values=set_values, where=where)

    def _assignment(self) -> Tuple[str, object]:
        col = self._expect(TokenType.IDENT).text
        self._expect(TokenType.EQ)
        return col, self._value()

    def _delete(self) -> DeleteStmt:
        self._expect(TokenType.KEYWORD, "DELETE")
        self._expect(TokenType.KEYWORD, "FROM")
        table = self._expect(TokenType.IDENT).text
        where = self._optional_where()
        return DeleteStmt(table=table, where=where)

    def _optional_where(self) -> Dict[str, object]:
        if not self._accept(TokenType.KEYWORD, "WHERE"):
            return {}
        out: Dict[str, object] = {}
        col, val = self._condition()
        out[col] = val
        while self._accept(TokenType.KEYWORD, "AND"):
            col, val = self._condition()
            out[col] = val
        return out

    def _condition(self) -> Tuple[str, object]:
        col = self._expect(TokenType.IDENT).text
        self._expect(TokenType.EQ)
        return col, self._value()

    def _value(self) -> object:
        if self._accept(TokenType.MINUS):
            lit = self._expect(TokenType.INT_LIT)
            return -int(lit.text)
        t = self._peek()
        if t.type == TokenType.INT_LIT:
            self._advance()
            return int(t.text)
        if t.type == TokenType.STRING_LIT:
            self._advance()
            return t.text
        if t.type == TokenType.KEYWORD and t.text == "TRUE":
            self._advance()
            return True
        if t.type == TokenType.KEYWORD and t.text == "FALSE":
            self._advance()
            return False
        raise ParseError(f"expected value, got {t.type.value} {t.text!r}")


def parse(source: str) -> Stmt:
    return _Parser(tokenize(source)).parse()


# --------------------------------------------------------------------------
# Results
# --------------------------------------------------------------------------


@dataclass
class SelectResult:
    columns: List[str]
    rows: List[tuple]


@dataclass
class CountResult:
    verb: str  # "inserted" | "updated" | "deleted"
    count: int


@dataclass
class StatusResult:
    message: str


@dataclass
class ExitResult:
    pass


Result = Union[SelectResult, CountResult, StatusResult, ExitResult]


_HELP_TEXT = (
    "Supported statements (keywords case-insensitive, semicolon optional):\n"
    "  CREATE TABLE name (col TYPE, ...)        TYPE = INT | TEXT | BOOL\n"
    "  DROP TABLE name\n"
    "  SHOW TABLES\n"
    "  INSERT INTO name VALUES (v, ...)\n"
    "  SELECT * | col, ... FROM name [WHERE col = v [AND col = v ...]]\n"
    "  UPDATE name SET col = v, ... [WHERE col = v [AND ...]]\n"
    "  DELETE FROM name [WHERE col = v [AND ...]]\n"
    "  EXIT | HELP"
)


# --------------------------------------------------------------------------
# Executor
# --------------------------------------------------------------------------


def execute(stmt: Stmt, db: Database) -> Result:
    if isinstance(stmt, CreateTableStmt):
        db.create_table(stmt.name, [ColumnDef(n, t) for n, t in stmt.columns])
        return StatusResult(f"Table {stmt.name!r} created")

    if isinstance(stmt, DropTableStmt):
        if db.drop_table(stmt.name):
            return StatusResult(f"Table {stmt.name!r} dropped")
        return StatusResult(f"Table {stmt.name!r} not found")

    if isinstance(stmt, ShowTablesStmt):
        names = db.list_tables()
        return SelectResult(columns=["table"], rows=[(n,) for n in names])

    if isinstance(stmt, InsertStmt):
        db.insert(stmt.table, stmt.values)
        return CountResult("inserted", 1)

    if isinstance(stmt, SelectStmt):
        if stmt.columns is None:
            info = db.table_info(stmt.table)
            if info is None:
                raise ValueError(f"table {stmt.table!r} does not exist")
            col_names = [c.name for c in info.columns]
        else:
            col_names = list(stmt.columns)
        rows = list(db.select(stmt.table, columns=stmt.columns, where=stmt.where or None))
        return SelectResult(columns=col_names, rows=rows)

    if isinstance(stmt, UpdateStmt):
        n = db.update(stmt.table, stmt.set_values, where=stmt.where or None)
        return CountResult("updated", n)

    if isinstance(stmt, DeleteStmt):
        n = db.delete(stmt.table, where=stmt.where or None)
        return CountResult("deleted", n)

    if isinstance(stmt, ExitStmt):
        return ExitResult()

    if isinstance(stmt, HelpStmt):
        return StatusResult(_HELP_TEXT)

    raise AssertionError(f"unhandled statement type: {type(stmt).__name__}")
