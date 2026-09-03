from __future__ import annotations

import io
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pikepdf

from .converter import safe_filename


class LetterheadError(Exception):
    """Raised when a letterhead cannot be stored or read."""


@dataclass(frozen=True)
class Letterhead:
    id: str
    name: str
    created_at: str


def init_letterhead_store(data_dir: str | Path) -> None:
    root = Path(data_dir)
    (root / "letterheads").mkdir(parents=True, exist_ok=True)
    with _connect(root) as database:
        database.execute(
            """
            CREATE TABLE IF NOT EXISTS letterheads (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )


def _connect(data_dir: str | Path) -> sqlite3.Connection:
    database = sqlite3.connect(Path(data_dir) / "letterheads.sqlite3")
    database.row_factory = sqlite3.Row
    return database


def list_letterheads(data_dir: str | Path) -> tuple[Letterhead, ...]:
    with _connect(data_dir) as database:
        rows = database.execute(
            "SELECT id, name, created_at FROM letterheads ORDER BY name COLLATE NOCASE"
        ).fetchall()
    return tuple(Letterhead(row["id"], row["name"], row["created_at"]) for row in rows)


def add_letterhead(data_dir: str | Path, name: str, pdf_bytes: bytes) -> Letterhead:
    clean_name = safe_filename(name.removesuffix(".pdf"), "Kopfbogen")[:80]
    try:
        with pikepdf.Pdf.open(io.BytesIO(pdf_bytes)) as document:
            if len(document.pages) < 1:
                raise LetterheadError("Der Kopfbogen enthält keine Seite.")
    except (pikepdf.PdfError, pikepdf.PasswordError) as exc:
        raise LetterheadError("Der Kopfbogen ist keine lesbare, ungeschützte PDF-Datei.") from exc

    root = Path(data_dir)
    identifier = secrets.token_hex(12)
    target = root / "letterheads" / f"{identifier}.pdf"
    temporary = target.with_suffix(".tmp")
    temporary.write_bytes(pdf_bytes)
    temporary.replace(target)
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        with _connect(root) as database:
            database.execute(
                "INSERT INTO letterheads (id, name, created_at) VALUES (?, ?, ?)",
                (identifier, clean_name, created_at),
            )
    except sqlite3.Error:
        target.unlink(missing_ok=True)
        raise
    return Letterhead(identifier, clean_name, created_at)


def letterhead_path(data_dir: str | Path, identifier: str) -> Path | None:
    if not identifier or any(character not in "0123456789abcdef" for character in identifier):
        return None
    with _connect(data_dir) as database:
        row = database.execute("SELECT id FROM letterheads WHERE id = ?", (identifier,)).fetchone()
    if row is None:
        return None
    path = Path(data_dir) / "letterheads" / f"{identifier}.pdf"
    return path if path.is_file() else None


def delete_letterhead(data_dir: str | Path, identifier: str) -> bool:
    path = letterhead_path(data_dir, identifier)
    if path is None:
        return False
    with _connect(data_dir) as database:
        cursor = database.execute("DELETE FROM letterheads WHERE id = ?", (identifier,))
    if cursor.rowcount:
        path.unlink(missing_ok=True)
        return True
    return False
