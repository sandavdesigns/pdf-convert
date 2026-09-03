import io

import pikepdf
import pytest

from app.letterheads import (
    LetterheadError,
    add_letterhead,
    delete_letterhead,
    init_letterhead_store,
    letterhead_path,
    list_letterheads,
)


def one_page_pdf():
    output = io.BytesIO()
    document = pikepdf.Pdf.new()
    document.add_blank_page(page_size=(595, 842))
    document.save(output)
    document.close()
    return output.getvalue()


def test_letterhead_store_adds_lists_resolves_and_deletes(tmp_path):
    init_letterhead_store(tmp_path)
    pdf_bytes = one_page_pdf()
    stored = add_letterhead(tmp_path, "Stadtwerke / Standard.pdf", pdf_bytes)

    assert stored.name == "Standard"
    assert list_letterheads(tmp_path) == (stored,)
    assert letterhead_path(tmp_path, stored.id).read_bytes() == pdf_bytes
    assert delete_letterhead(tmp_path, stored.id) is True
    assert list_letterheads(tmp_path) == ()
    assert letterhead_path(tmp_path, stored.id) is None


def test_letterhead_store_rejects_invalid_pdf(tmp_path):
    init_letterhead_store(tmp_path)

    with pytest.raises(LetterheadError, match="lesbare"):
        add_letterhead(tmp_path, "Defekt", b"not-pdf")
