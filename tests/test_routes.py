import io
import tempfile
import zipfile

import pikepdf

from app import create_app
from app.letterheads import list_letterheads


def client(extra_config=None):
    config = {
        "TESTING": True,
        "DATA_DIR": tempfile.mkdtemp(prefix="pdf-tools-test-"),
        "MAX_CONTENT_LENGTH": 1024 * 1024,
        "MAX_UPLOAD_MB": 1,
        "SECRET_KEY": "test-secret",
    }
    config.update(extra_config or {})
    app = create_app(config)
    return app.test_client()


def pdf_bytes(page_count=1):
    output = io.BytesIO()
    document = pikepdf.Pdf.new()
    for _ in range(page_count):
        document.add_blank_page(page_size=(595, 842))
    document.save(output)
    document.close()
    return output.getvalue()


def test_index_and_health():
    test_client = client()
    response = test_client.get("/")
    assert response.status_code == 200
    assert b"PDF Werkzeuge" in response.data
    assert b"PDF auf Kopfbogen" in response.data
    assert b"PDF trennen" in response.data
    assert b'name="color-scheme" content="light dark"' in response.data
    assert b'data-theme-choice="light"' in response.data
    assert b'data-theme-choice="dark"' in response.data
    assert b'data-theme-choice="auto"' in response.data
    assert b'name="export_attachments"' in response.data
    assert b"brand/logo-mark.svg" in response.data
    assert b"brand/favicon.svg" in response.data
    assert test_client.get("/static/theme.js").status_code == 200
    assert test_client.get("/static/brand/logo-mark.svg").status_code == 200
    assert test_client.get("/static/brand/favicon.svg").status_code == 200
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert test_client.get("/health").json == {"status": "ok"}


def test_pdf_tool_pages_are_available():
    test_client = client()
    letterhead = test_client.get("/werkzeuge/kopfbogen")
    split = test_client.get("/werkzeuge/pdf-trennen")

    assert letterhead.status_code == 200
    assert b"Noch kein Kopfbogen hinterlegt" in letterhead.data
    assert split.status_code == 200
    assert b"Seiten pro Datei" in split.data


def test_letterhead_admin_requires_login_and_configured_password():
    disabled_client = client()
    response = disabled_client.get("/verwaltung/kopfboegen")
    assert response.status_code == 302
    login = disabled_client.get(response.headers["Location"])
    assert b"LETTERHEAD_ADMIN_PASSWORD" in login.data

    test_client = client({"LETTERHEAD_ADMIN_PASSWORD": "intern-geheim"})
    with test_client.session_transaction() as admin_session:
        admin_session["csrf_token"] = "csrf-test"
    wrong = test_client.post(
        "/verwaltung/kopfboegen/anmeldung",
        data={"password": "falsch", "csrf_token": "csrf-test"},
    )
    assert b"nicht korrekt" in wrong.data
    accepted = test_client.post(
        "/verwaltung/kopfboegen/anmeldung",
        data={"password": "intern-geheim", "csrf_token": "csrf-test"},
    )
    assert accepted.status_code == 302
    assert accepted.headers["Location"].endswith("/verwaltung/kopfboegen")


def test_admin_upload_and_letterhead_processing():
    test_client = client({"LETTERHEAD_ADMIN_PASSWORD": "intern-geheim"})
    with test_client.session_transaction() as admin_session:
        admin_session["letterhead_admin"] = True
        admin_session["csrf_token"] = "csrf-test"
    uploaded = test_client.post(
        "/verwaltung/kopfboegen",
        data={
            "csrf_token": "csrf-test",
            "name": "Standard",
            "pdf": (io.BytesIO(pdf_bytes()), "kopfbogen.pdf"),
        },
        content_type="multipart/form-data",
    )
    assert uploaded.status_code == 302
    letterheads = list_letterheads(test_client.application.config["DATA_DIR"])
    assert [item.name for item in letterheads] == ["Standard"]

    result = test_client.post(
        "/werkzeuge/kopfbogen",
        data={
            "pdf": (io.BytesIO(pdf_bytes(3)), "bericht.pdf"),
            "letterhead_id": letterheads[0].id,
            "mode": "interval",
            "interval": "2",
        },
        content_type="multipart/form-data",
    )
    assert result.status_code == 200
    assert result.mimetype == "application/pdf"
    assert "bericht-mit-kopfbogen.pdf" in result.headers["Content-Disposition"]
    with pikepdf.Pdf.open(io.BytesIO(result.data)) as document:
        assert len(document.pages) == 3


def test_split_route_returns_zip_with_pdf_parts():
    response = client().post(
        "/werkzeuge/pdf-trennen",
        data={
            "pdf": (io.BytesIO(pdf_bytes(5)), "bericht.pdf"),
            "pages_per_file": "2",
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    assert response.mimetype == "application/zip"
    with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
        assert archive.namelist() == [
            "bericht-Teil-001-Seiten-1-2.pdf",
            "bericht-Teil-002-Seiten-3-4.pdf",
            "bericht-Teil-003-Seiten-5-5.pdf",
        ]


def test_convert_requires_file():
    response = client().post("/convert")
    assert response.status_code == 400
    assert "mindestens" in response.json["error"]


def test_convert_rejects_wrong_extension():
    response = client().post(
        "/convert",
        data={"files": (io.BytesIO(b"hello"), "mail.eml")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 400
    assert "MSG" in response.json["error"]


def test_convert_reports_invalid_msg():
    response = client().post(
        "/convert",
        data={"files": (io.BytesIO(b"hello"), "mail.msg")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 422
    assert "gültige" in response.json["error"]


def test_convert_returns_generated_pdf(monkeypatch):
    options = {}

    def fake_convert(files, include_original, export_attachments):
        options["include_original"] = include_original
        options["export_attachments"] = export_attachments
        return b"MSGPDF-test", "einzeldateien.msgpdf", "application/vnd.msg-pdf-files", 2

    monkeypatch.setattr(
        "app.routes.convert_many",
        fake_convert,
    )
    response = client().post(
        "/convert",
        data={
            "files": (io.BytesIO(b"valid-for-mock"), "mail.msg"),
            "include_original": "on",
            "export_attachments": "on",
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    assert response.data == b"MSGPDF-test"
    assert response.mimetype == "application/vnd.msg-pdf-files"
    assert "einzeldateien.msgpdf" in response.headers["Content-Disposition"]
    assert response.headers["X-Mail-Attachment-Count"] == "2"
    assert options == {"include_original": True, "export_attachments": True}
