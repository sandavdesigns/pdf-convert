import io
import zipfile
from datetime import datetime

import pikepdf
import pytest

from app.converter import (
    Attachment,
    ConversionError,
    MailData,
    archive_output_filename,
    build_document_html,
    convert_many,
    embed_attachments,
    is_msg_file,
    mail_output_filename,
    render_pdf,
    safe_filename,
    sanitize_email_html,
    unique_filename,
    _extract_attachments,
    _inline_content_ids,
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


def test_mail_output_filename_uses_date_sender_and_shortened_subject():
    mail = MailData(
        subject='Meeting: Netzgebiet West / Abstimmung mit Projektteam',
        sender='Müller, David <david.mueller@example.org>',
        recipients="",
        cc="",
        date="05.02.2026, 09:15 CET",
        body_html="",
        attachments=(),
    )

    assert mail_output_filename(mail) == "2026-02-05 Mueller.David Meeting- Netzgebiet West - Abs.pdf"
    assert len("Meeting- Netzgebiet West - Abs") == 30


def test_mail_output_filename_has_safe_fallbacks():
    mail = MailData(
        subject='<>:"/\\|?*',
        sender="<technik@example.org>",
        recipients="",
        cc="",
        date="",
        body_html="",
        attachments=(),
    )

    assert mail_output_filename(mail) == "ohne-datum technik ---------.pdf"


def test_archive_output_filename_uses_date_and_six_digit_random_number():
    assert archive_output_filename(datetime(2026, 2, 5), 154782) == "2026-02-05-154782.zip"


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


def test_extracts_embedded_outlook_message(tmp_path):
    class EmbeddedMessage:
        def export(self, target, allowBadEmbed=False):
            assert allowBadEmbed is True
            target.write(b"embedded-msg-data")

    class EmbeddedAttachment:
        name = "Weitergeleitete Nachricht.msg"
        mimetype = "application/vnd.ms-outlook"
        cid = None
        data = EmbeddedMessage()

    message = type("Message", (), {"attachments": [EmbeddedAttachment()]})()
    attachments = _extract_attachments(message, tmp_path)

    assert len(attachments) == 1
    assert attachments[0].name == "Weitergeleitete Nachricht.msg"
    assert attachments[0].data == b"embedded-msg-data"


def test_preserves_cloud_attachment_as_url_file(tmp_path):
    class CloudAttachment:
        name = None
        longFilename = None
        shortFilename = None
        displayName = None
        url = "https://sharepoint.example.org/files/Netzplan.pdf?download=1"

        @property
        def data(self):
            raise NotImplementedError

    message = type("Message", (), {"attachments": [CloudAttachment()]})()
    attachments = _extract_attachments(message, tmp_path)

    assert len(attachments) == 1
    assert attachments[0].name == "Netzplan.pdf.url"
    assert b"https://sharepoint.example.org/files/Netzplan.pdf?download=1" in attachments[0].data


def test_excludes_inline_signature_image_but_keeps_real_image_attachment(tmp_path):
    class ImageAttachment:
        mimetype = "image/png"
        hidden = False

        def __init__(self, name, cid, data):
            self.name = name
            self.cid = cid
            self.contentId = cid
            self.data = data

    inline_logo = ImageAttachment("logo.png", "<signature-logo@example>", b"inline-logo")
    real_attachment = ImageAttachment("Lageplan.png", None, b"real-attachment")
    message = type("Message", (), {"attachments": [inline_logo, real_attachment]})()

    attachments = _extract_attachments(
        message,
        tmp_path,
        {"signature-logo@example"},
    )

    assert [attachment.name for attachment in attachments] == ["Lageplan.png"]
    assert attachments[0].data == b"real-attachment"


def test_finds_and_normalizes_inline_content_ids():
    body_html = '<img src="cid:%3CSignature-Logo%40Example%3E">'

    assert _inline_content_ids(body_html) == {"signature-logo@example"}


def test_excludes_hidden_outlook_resource(tmp_path):
    hidden_attachment = type(
        "HiddenAttachment",
        (),
        {
            "name": "image001.png",
            "cid": None,
            "hidden": True,
            "data": b"hidden-resource",
            "mimetype": "image/png",
        },
    )()
    message = type("Message", (), {"attachments": [hidden_attachment]})()

    assert _extract_attachments(message, tmp_path) == ()


def test_convert_many_rejects_invalid_msg():
    with pytest.raises(ConversionError, match="keine gültige"):
        convert_many([("fake.msg", b"invalid")])


def test_convert_many_names_single_pdf_from_mail_metadata(monkeypatch):
    mail = MailData(
        subject="Meeting vom Montag",
        sender="Müller, David <david.mueller@example.org>",
        recipients="",
        cc="",
        date="05.02.2026, 09:15 CET",
        body_html="",
        attachments=(),
    )
    monkeypatch.setattr(
        "app.converter._convert_msg_with_metadata",
        lambda data, name, include: (b"%PDF-test", mail),
    )
    monkeypatch.setattr("app.converter._mail_attachment_count", lambda data, name, include: 0)

    payload, name, mime, attachment_count = convert_many([("outlook.msg", b"msg")])

    assert payload == b"%PDF-test"
    assert name == "2026-02-05 Mueller.David Meeting vom Montag.pdf"
    assert mime == "application/pdf"
    assert attachment_count == 0


def test_convert_many_exports_single_pdf_and_attachments_side_by_side(monkeypatch):
    monkeypatch.setattr(
        "app.converter._convert_msg_with_metadata",
        lambda data, name, include: (b"%PDF-test", sample_mail()),
    )
    monkeypatch.setattr("app.converter._mail_attachment_count", lambda data, name, include: 2)
    monkeypatch.setattr("app.converter.archive_output_filename", lambda: "2026-02-05-154782.zip")

    payload, name, mime, attachment_count = convert_many(
        [("outlook.msg", b"msg")],
        export_attachments=True,
    )

    assert name == "2026-02-05-154782.zip"
    assert mime == "application/zip"
    assert attachment_count == 2
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        assert archive.namelist() == [
            "2026-07-23 Absender Test & Prüfung.pdf",
            "daten.txt",
            "bild.png",
        ]
        assert archive.read("daten.txt") == b"eins,zwei,drei"
        assert archive.read("bild.png") == b"not-a-real-png"


def test_convert_many_wraps_multiple_results(monkeypatch):
    monkeypatch.setattr(
        "app.converter._convert_msg_with_metadata",
        lambda data, name, include: (b"%PDF-" + data, sample_mail()),
    )
    monkeypatch.setattr("app.converter._mail_attachment_count", lambda data, name, include: 0)
    monkeypatch.setattr("app.converter.archive_output_filename", lambda: "2026-02-05-154782.zip")
    payload, name, mime, attachment_count = convert_many(
        [("eins.msg", b"one"), ("zwei.msg", b"two")],
        include_original=False,
    )
    assert name == "2026-02-05-154782.zip"
    assert mime == "application/zip"
    assert attachment_count == 0
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        assert archive.namelist() == ["eins.pdf", "zwei.pdf"]


def test_convert_many_groups_separate_attachments_by_mail(monkeypatch):
    monkeypatch.setattr(
        "app.converter._convert_msg_with_metadata",
        lambda data, name, include: (b"%PDF-" + data, sample_mail()),
    )
    monkeypatch.setattr("app.converter._mail_attachment_count", lambda data, name, include: 2)
    monkeypatch.setattr("app.converter.archive_output_filename", lambda: "2026-02-05-154782.zip")

    payload, _, _, _ = convert_many(
        [("eins.msg", b"one"), ("zwei.msg", b"two")],
        export_attachments=True,
    )

    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        assert archive.namelist() == [
            "eins/eins.pdf",
            "eins/daten.txt",
            "eins/bild.png",
            "zwei/zwei.pdf",
            "zwei/daten.txt",
            "zwei/bild.png",
        ]
