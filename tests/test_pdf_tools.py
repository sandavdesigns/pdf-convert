import io
import zipfile

import pikepdf
import pytest

from app.pdf_tools import PdfToolError, apply_letterhead, letterhead_output_name, split_pdf


def blank_pdf(page_count, width=595, height=842):
    output = io.BytesIO()
    document = pikepdf.Pdf.new()
    for _ in range(page_count):
        document.add_blank_page(page_size=(width, height))
    document.save(output)
    document.close()
    return output.getvalue()


def pages_with_overlay(pdf_bytes):
    with pikepdf.Pdf.open(io.BytesIO(pdf_bytes)) as document:
        return [
            "/Resources" in page.obj and "/XObject" in page.obj.Resources
            for page in document.pages
        ]


def test_applies_letterhead_to_every_page():
    result = apply_letterhead(blank_pdf(3), blank_pdf(1), mode="all")

    assert pages_with_overlay(result) == [True, True, True]


def test_applies_letterhead_to_first_and_interval_pages():
    document = blank_pdf(5)
    template = blank_pdf(1)

    assert pages_with_overlay(apply_letterhead(document, template, mode="first")) == [
        True,
        False,
        False,
        False,
        False,
    ]
    assert pages_with_overlay(
        apply_letterhead(document, template, mode="interval", interval=2)
    ) == [True, False, True, False, True]


def test_letterhead_rejects_invalid_mode_and_pdf():
    with pytest.raises(PdfToolError, match="Seitenauswahl"):
        apply_letterhead(blank_pdf(1), blank_pdf(1), mode="unknown")
    with pytest.raises(PdfToolError, match="beschädigt"):
        apply_letterhead(b"not-pdf", blank_pdf(1))


def test_split_pdf_creates_numbered_page_ranges():
    archive_bytes, archive_name = split_pdf(blank_pdf(7), 3, "Netzplan.pdf")

    assert archive_name == "Netzplan-geteilt.zip"
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        assert archive.namelist() == [
            "Netzplan-Teil-001-Seiten-1-3.pdf",
            "Netzplan-Teil-002-Seiten-4-6.pdf",
            "Netzplan-Teil-003-Seiten-7-7.pdf",
        ]
        page_counts = []
        for name in archive.namelist():
            with pikepdf.Pdf.open(io.BytesIO(archive.read(name))) as part:
                page_counts.append(len(part.pages))
        assert page_counts == [3, 3, 1]


def test_split_pdf_validates_page_count_and_output_name():
    assert letterhead_output_name("Bericht 2026.pdf") == "Bericht 2026-mit-kopfbogen.pdf"
    with pytest.raises(PdfToolError, match="zwischen 1 und 10000"):
        split_pdf(blank_pdf(1), 0, "dokument.pdf")
