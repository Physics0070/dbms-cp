"""Safe handling of uploaded SQLite and DuckDB files.

Files are streamed to a server-generated name (the client filename is never used on disk)
inside a directory that is not served statically, size-capped while streaming, checked for
the SQLite/DuckDB magic bytes (and `PRAGMA quick_check` for SQLite), and opened read-only. A failed upload deletes
its temp file and leaves the current connection untouched.
"""
from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path
from typing import AsyncIterator

from .config import get_settings
from .database.duckdb_adapter import connect_duckdb, sniff_format
from .database.sqlite_adapter import DatabaseUnavailable, connect_database

_DEFAULT_DIR = Path(__file__).resolve().parent.parent / "data" / "uploads"


class UploadError(ValueError):
    """The upload was rejected; the message is safe to show to the user."""


def upload_dir() -> Path:
    s = get_settings()
    d = Path(s.upload_dir).expanduser() if s.upload_dir else _DEFAULT_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


async def save_and_connect(chunks: AsyncIterator[bytes]):
    """Stream, sniff (SQLite or DuckDB), validate and connect. Returns the new adapter."""
    limit_mb = get_settings().max_upload_mb
    part = upload_dir() / f"{uuid.uuid4().hex}.part"
    final = part
    size = 0
    try:
        with open(part, "wb") as fh:
            async for chunk in chunks:
                size += len(chunk)
                if size > limit_mb * 1024 * 1024:
                    raise UploadError(f"File is larger than the {limit_mb} MB upload limit.")
                fh.write(chunk)
        if size == 0:
            raise UploadError("The upload was empty.")
        fmt = sniff_format(str(part))
        if fmt is None:
            raise UploadError("This is not a SQLite or DuckDB database file.")
        final = part.with_suffix(".db" if fmt == "sqlite" else ".duckdb")
        part.rename(final)
        try:
            if fmt == "sqlite":
                _quick_check(final)
                adapter = connect_database(str(final))
            else:
                adapter = connect_duckdb(str(final))
        except DatabaseUnavailable as e:
            raise UploadError(str(e)) from e
    except BaseException:
        part.unlink(missing_ok=True)
        final.unlink(missing_ok=True)
        raise
    _remove_old_uploads(keep=final)
    return adapter


def _quick_check(path: Path) -> None:
    try:
        conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        try:
            result = conn.execute("PRAGMA quick_check").fetchone()
        finally:
            conn.close()
    except sqlite3.Error as e:
        raise UploadError(f"Could not read the database: {e}") from e
    if not result or result[0] != "ok":
        raise UploadError(f"The database failed its integrity check: {result[0] if result else 'unknown'}")


def _remove_old_uploads(keep: Path) -> None:
    """Delete earlier uploads once replaced (only uuid-named .db/.duckdb files this module created)."""
    for f in (*upload_dir().glob("*.db"), *upload_dir().glob("*.duckdb")):
        if f.resolve() != keep.resolve() and len(f.stem) == 32:
            try:
                f.unlink()
            except OSError:
                pass  # still open on Windows; removed on a later upload
