import hashlib
import os
import tempfile
from pathlib import Path

from flask import Flask, request


def create_app(test_config=None):
    app = Flask(__name__)
    max_upload_mb = int(os.getenv("MAX_UPLOAD_MB", "100"))
    admin_password = os.getenv("LETTERHEAD_ADMIN_PASSWORD", "")
    default_secret = hashlib.sha256(f"pdf-tools:{admin_password}".encode()).hexdigest()
    app.config.from_mapping(
        DATA_DIR=os.getenv("DATA_DIR", str(Path(tempfile.gettempdir()) / "pdf-convert-data")),
        LETTERHEAD_ADMIN_PASSWORD=admin_password,
        MAX_CONTENT_LENGTH=max_upload_mb * 1024 * 1024,
        MAX_UPLOAD_MB=max_upload_mb,
        SECRET_KEY=os.getenv("APP_SECRET_KEY") or default_secret,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )

    if test_config:
        app.config.update(test_config)

    from .letterheads import init_letterhead_store

    init_letterhead_store(app.config["DATA_DIR"])

    from .routes import web

    app.register_blueprint(web)

    @app.after_request
    def security_headers(response):
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "img-src 'self' data:; "
            "style-src 'self'; "
            "script-src 'self'; "
            "connect-src 'self'; "
            "object-src 'none'; "
            "base-uri 'none'; "
            "form-action 'self'; "
            "frame-ancestors 'none'"
        )
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        if request.path.startswith("/verwaltung/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    return app
