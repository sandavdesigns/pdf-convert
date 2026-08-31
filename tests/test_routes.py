import io

from app import create_app


def client():
    app = create_app({"TESTING": True, "MAX_CONTENT_LENGTH": 1024 * 1024, "MAX_UPLOAD_MB": 1})
    return app.test_client()


def test_index_and_health():
    test_client = client()
    response = test_client.get("/")
    assert response.status_code == 200
    assert b"MSG to PDF Converter" in response.data
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
        return b"%PDF-test", "mail.pdf", "application/pdf", 2

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
    assert response.data == b"%PDF-test"
    assert response.mimetype == "application/pdf"
    assert "mail.pdf" in response.headers["Content-Disposition"]
    assert response.headers["X-Mail-Attachment-Count"] == "2"
    assert options == {"include_original": True, "export_attachments": True}
