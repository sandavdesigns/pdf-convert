import io
import zipfile

import pikepdf
import pytest

from app.converter import (
    Attachment,
    ConversionError,
    MailData,
    build_document_html,
    convert_many,
    embed_attachments,
    is_msg_file,
    render_pdf,
    safe_filename,
    sanitize_email_html,
    unique_filename,
)


def sample_mail():
    return MailData(
        subject="Test & Prüfung",
        sender="Absender <sender@example.org>",
        recipients="Empfänger <receiver@example.org>",
        cc="",
        date="23.07.2026, 12:30",
        body_html="<p>Hallo <strong>Welt</strong>.</p>",
        attachments=(
            Attachment("daten.txt", b"eins,zwei,drei", "text/plain"),
            Attachment("bild.png", b"not-a-real-png", "image/png"),
        ),
    )


def test_msg_signature_detection():
    assert is_msg_file(bytes.fromhex("D0CF11E0A1B11AE1") + b"payload")
    assert not is_msg_file(b"not a msg")


def test_safe_and_unique_filenames():
    assert safe_filename("../../rechnung?.xlsx", "file") == "rechnung.xlsx"
    used = set()
    assert unique_filename("anlage.pdf", used) == "anlage.pdf"
    assert unique_filename("Anlage.pdf", used) == "Anlage (2).pdf"


def test_email_html_removes_active_and_remote_content():
    dirty = """
    <html><body onload="bad()">
      <script>alert(1)</script>
      <img src="https://tracker.example/pixel" onerror="bad()">
      <a href="https://example.org">Link</a>
      <p style="background:url(https://example.org/x)">Text</p>
    </body></html>
    """
    clean = sanitize_email_html(dirty)
    assert "<script" not in clean
    assert "onload" not in clean
    assert "onerror" not in clean
    assert "tracker.example" not in clean
    assert 'href="#"' in clean
    assert "url(" not in clean


def test_render_and_embed_attachments():
    mail = sample_mail()
    base_pdf = render_pdf(mail)
    result = embed_attachments(base_pdf, mail, b"original-msg", "original.msg")

    with pikepdf.Pdf.open(io.BytesIO(result)) as pdf:
        assert len(pdf.pages) >= 1
        assert set(pdf.attachments) == {"daten.txt", "bild.png", "original.msg"}
        assert pdf.attachments["daten.txt"].get_file().read_bytes() == b"eins,zwei,drei"
        assert pdf.attachments["original.msg"].get_file().read_bytes() == b"original-msg"


def test_document_contains_visible_attachment_list():
    document = build_document_html(sample_mail())
    assert "daten.txt" in document
    assert "bild.png" in document
    assert "Anlagen in dieser PDF" in document


def test_convert_many_rejects_invalid_msg():
    with pytest.raises(ConversionError, match="keine gültige"):
        convert_many([("fake.msg", b"invalid")])


def test_convert_many_wraps_multiple_results(monkeypatch):
    monkeypatch.setattr("app.converter.convert_msg_bytes", lambda data, name, include: b"%PDF-" + data)
    payload, name, mime = convert_many(
        [("eins.msg", b"one"), ("zwei.msg", b"two")],
        include_original=False,
    )
    assert name == "konvertierte-mails.zip"
    assert mime == "application/zip"
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        assert archive.namelist() == ["eins.pdf", "zwei.pdf"]

