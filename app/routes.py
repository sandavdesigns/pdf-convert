from __future__ import annotations

import io

from flask import Blueprint, current_app, jsonify, render_template, request, send_file
from werkzeug.exceptions import RequestEntityTooLarge

from .converter import ConversionError, convert_many


web = Blueprint("web", __name__)


@web.get("/")
def index():
    return render_template("index.html", max_upload_mb=current_app.config["MAX_UPLOAD_MB"])


@web.get("/health")
def health():
    return jsonify(status="ok")


@web.post("/convert")
def convert():
    uploads = [item for item in request.files.getlist("files") if item and item.filename]
    if not uploads:
        return jsonify(error="Bitte mindestens eine MSG-Datei auswählen."), 400

    invalid = [item.filename for item in uploads if not item.filename.lower().endswith(".msg")]
    if invalid:
        return jsonify(error="Es werden ausschließlich Outlook-MSG-Dateien unterstützt."), 400

    files = [(item.filename, item.read()) for item in uploads]
    include_original = request.form.get("include_original") == "on"
    export_attachments = request.form.get("export_attachments") == "on"
    try:
        output, name, mime_type, attachment_count = convert_many(
            files,
            include_original,
            export_attachments,
        )
    except ConversionError as exc:
        return jsonify(error=str(exc)), 422

    response = send_file(
        io.BytesIO(output),
        mimetype=mime_type,
        as_attachment=True,
        download_name=name,
        max_age=0,
    )
    response.headers["X-Mail-Attachment-Count"] = str(attachment_count)
    return response


@web.app_errorhandler(RequestEntityTooLarge)
def file_too_large(_error):
    limit = current_app.config["MAX_UPLOAD_MB"]
    return jsonify(error=f"Der Upload ist größer als das konfigurierte Limit von {limit} MB."), 413


@web.app_errorhandler(500)
def internal_error(_error):
    return jsonify(error="Die Konvertierung ist unerwartet fehlgeschlagen."), 500
