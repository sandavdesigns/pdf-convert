from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pikepdf
from pikepdf import Pdf, Rectangle

from .converter import safe_filename


class PdfToolError(Exception):
    """Raised when an uploaded PDF cannot be processed."""


def _page_rectangle(page: pikepdf.Page) -> Rectangle:
    return Rectangle(*(float(value) for value in page.mediabox))


def _uses_letterhead(page_index: int, mode: str, interval: int) -> bool:
    if mode == "all":
        return True
    if mode == "first":
        return page_index == 0
    if mode == "interval":
        return page_index % interval == 0
    raise PdfToolError("Die Seitenauswahl für den Kopfbogen ist ungültig.")


def apply_letterhead(
    document_bytes: bytes,
    letterhead_bytes: bytes,
    mode: str = "all",
    interval: int = 1,
) -> bytes:
    if interval < 1 or interval > 1000:
        raise PdfToolError("Der Seitenabstand muss zwischen 1 und 1000 liegen.")
    output = io.BytesIO()
    try:
        with Pdf.open(io.BytesIO(document_bytes)) as document, Pdf.open(
            io.BytesIO(letterhead_bytes)
        ) as letterhead:
            if not document.pages:
                raise PdfToolError("Die hochgeladene PDF enthält keine Seiten.")
            if not letterhead.pages:
                raise PdfToolError("Der ausgewählte Kopfbogen enthält keine Seite.")
            template = letterhead.pages[0]
            for page_index, page in enumerate(document.pages):
                if _uses_letterhead(page_index, mode, interval):
                    page.add_overlay(template, _page_rectangle(page))
            document.save(output)
    except PdfToolError:
        raise
    except (pikepdf.PdfError, pikepdf.PasswordError, ValueError) as exc:
        raise PdfToolError("Die PDF ist beschädigt, geschützt oder wird nicht unterstützt.") from exc
    return output.getvalue()


def letterhead_output_name(original_name: str) -> str:
    source = safe_filename(original_name, "dokument.pdf")
    stem = Path(source).stem or "dokument"
    return safe_filename(f"{stem}-mit-kopfbogen.pdf", "dokument-mit-kopfbogen.pdf")


def split_pdf(document_bytes: bytes, pages_per_file: int, original_name: str) -> tuple[bytes, str]:
    if pages_per_file < 1 or pages_per_file > 10000:
        raise PdfToolError("Die Seitenzahl muss zwischen 1 und 10000 liegen.")

    archive = io.BytesIO()
    source_name = safe_filename(original_name, "dokument.pdf")
    stem = Path(source_name).stem or "dokument"
    try:
        with Pdf.open(io.BytesIO(document_bytes)) as document:
            page_count = len(document.pages)
            if page_count < 1:
                raise PdfToolError("Die hochgeladene PDF enthält keine Seiten.")
            with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
                part_number = 1
                for start in range(0, page_count, pages_per_file):
                    end = min(start + pages_per_file, page_count)
                    part = Pdf.new()
                    part.pages.extend(document.pages[start:end])
                    part_bytes = io.BytesIO()
                    part.save(part_bytes)
                    part.close()
                    filename = safe_filename(
                        f"{stem}-Teil-{part_number:03d}-Seiten-{start + 1}-{end}.pdf",
                        f"Teil-{part_number:03d}.pdf",
                    )
                    bundle.writestr(filename, part_bytes.getvalue())
                    part_number += 1
    except PdfToolError:
        raise
    except (pikepdf.PdfError, pikepdf.PasswordError, ValueError) as exc:
        raise PdfToolError("Die PDF ist beschädigt, geschützt oder wird nicht unterstützt.") from exc
    return archive.getvalue(), safe_filename(f"{stem}-geteilt.zip", "pdf-teile.zip")
