"""Read-only SQL safety validation using sqlglot AST inspection.

We validate on the parsed AST rather than by naive string matching, so tricks
like comments or casing cannot smuggle a write past us.
"""
from __future__ import annotations

import sqlglot
from sqlglot import exp


class UnsafeQueryError(ValueError):
    pass


# AST node classes that must never appear in a read-only query.
_FORBIDDEN = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Alter,
    exp.Create,
    exp.TruncateTable,
    exp.Command,      # catches PRAGMA, ATTACH, VACUUM, etc. (parsed as Command)
    exp.Transaction,
    exp.Commit,
    exp.Rollback,
    exp.Set,
)

_FORBIDDEN_KEYWORDS = {
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE", "CREATE",
    "ATTACH", "DETACH", "PRAGMA", "VACUUM", "REINDEX", "REPLACE",
    "BEGIN", "COMMIT", "ROLLBACK", "SAVEPOINT", "GRANT", "REVOKE",
}


def validate_readonly(sql: str, dialect: str = "sqlite") -> exp.Expression:
    """Parse `sql`, guarantee it is a single read-only SELECT, return the AST.

    Raises :class:`UnsafeQueryError` on anything that could mutate state.
    """
    if not sql or not sql.strip():
        raise UnsafeQueryError("Empty query.")

    try:
        statements = sqlglot.parse(sql, read=dialect)
    except Exception as e:  # sqlglot ParseError and friends
        raise UnsafeQueryError(f"Could not parse SQL: {e}") from e

    statements = [s for s in statements if s is not None]
    if len(statements) == 0:
        raise UnsafeQueryError("No statement found.")
    if len(statements) > 1:
        raise UnsafeQueryError("Multiple statements are not allowed.")

    root = statements[0]

    # The top-level statement must be a SELECT (optionally wrapped in a WITH/CTE).
    top = root
    if isinstance(top, exp.With):
        top = top.this
    if not isinstance(top, (exp.Select, exp.Union, exp.Subquery)):
        raise UnsafeQueryError(
            f"Only read-only SELECT queries are allowed (got {type(root).__name__})."
        )

    # Walk the whole tree looking for any forbidden node.
    for node in root.walk():
        expr = node[0] if isinstance(node, tuple) else node
        if isinstance(expr, _FORBIDDEN):
            raise UnsafeQueryError(
                f"Statement type '{type(expr).__name__}' is not permitted in read-only mode."
            )
        if isinstance(expr, exp.Command):
            raise UnsafeQueryError("Command statements (e.g. PRAGMA) are not permitted.")

    # Belt-and-braces keyword scan of the *tokens* (defends against parser gaps).
    upper = _strip_string_literals(sql).upper()
    for kw in _FORBIDDEN_KEYWORDS:
        # word-boundary check
        if _contains_word(upper, kw):
            raise UnsafeQueryError(f"Forbidden keyword detected: {kw}")

    return root


def _strip_string_literals(sql: str) -> str:
    """Remove single/double quoted literals so keywords inside them don't trip us."""
    out = []
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        if ch in ("'", '"'):
            quote = ch
            i += 1
            while i < n and sql[i] != quote:
                i += 1
            i += 1  # skip closing quote
            out.append(" ")
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _contains_word(haystack: str, word: str) -> bool:
    import re

    return re.search(rf"\b{re.escape(word)}\b", haystack) is not None
