from __future__ import annotations

import io
import hmac
import secrets
from functools import wraps

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from werkzeug.exceptions import RequestEntityTooLarge

from .converter import ConversionError, convert_many
from .letterheads import (
    LetterheadError,
    add_letterhead,
    delete_letterhead,
    letterhead_path,
    list_letterheads,
)
from .pdf_tools import PdfToolError, apply_letterhead, letterhead_output_name, split_pdf


web = Blueprint("web", __name__)


def _csrf_token() -> str:
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(24)
    return session["csrf_token"]


def _valid_csrf() -> bool:
    expected = session.get("csrf_token", "")
    provided = request.form.get("csrf_token", "")
    return bool(expected and provided and hmac.compare_digest(expected, provided))


def _admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("letterhead_admin"):
            return redirect(url_for("web.admin_login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


@web.app_context_processor
def template_helpers():
    return {"csrf_token": _csrf_token}


@web.get("/")
def index():
    return render_template(
        "index.html",
        active_tool="msg",
        max_upload_mb=current_app.config["MAX_UPLOAD_MB"],
    )


@web.get("/werkzeuge/kopfbogen")
def letterhead_tool():
    return render_template(
        "letterhead.html",
        active_tool="letterhead",
        letterheads=list_letterheads(current_app.config["DATA_DIR"]),
        max_upload_mb=current_app.config["MAX_UPLOAD_MB"],
    )


@web.post("/werkzeuge/kopfbogen")
def apply_letterhead_route():
    upload = request.files.get("pdf")
    if not upload or not upload.filename:
        return jsonify(error="Bitte eine PDF-Datei auswählen."), 400
    if not upload.filename.lower().endswith(".pdf"):
        return jsonify(error="Es werden ausschließlich PDF-Dateien unterstützt."), 400

    template_path = letterhead_path(
        current_app.config["DATA_DIR"],
        request.form.get("letterhead_id", ""),
    )
    if template_path is None:
        return jsonify(error="Bitte einen vorhandenen Kopfbogen auswählen."), 400

    mode = request.form.get("mode", "all")
    try:
        interval = int(request.form.get("interval", "1"))
        result = apply_letterhead(upload.read(), template_path.read_bytes(), mode, interval)
    except (ValueError, PdfToolError) as exc:
        message = str(exc) if isinstance(exc, PdfToolError) else "Der Seitenabstand ist ungültig."
        return jsonify(error=message), 422
    return send_file(
        io.BytesIO(result),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=letterhead_output_name(upload.filename),
        max_age=0,
    )


@web.get("/werkzeuge/pdf-trennen")
def split_tool():
    return render_template(
        "split.html",
        active_tool="split",
        max_upload_mb=current_app.config["MAX_UPLOAD_MB"],
    )


@web.post("/werkzeuge/pdf-trennen")
def split_pdf_route():
    upload = request.files.get("pdf")
    if not upload or not upload.filename:
        return jsonify(error="Bitte eine PDF-Datei auswählen."), 400
    if not upload.filename.lower().endswith(".pdf"):
        return jsonify(error="Es werden ausschließlich PDF-Dateien unterstützt."), 400
    try:
        pages_per_file = int(request.form.get("pages_per_file", "0"))
        result, output_name = split_pdf(upload.read(), pages_per_file, upload.filename)
    except (ValueError, PdfToolError) as exc:
        message = str(exc) if isinstance(exc, PdfToolError) else "Die Seitenzahl ist ungültig."
        return jsonify(error=message), 422
    return send_file(
        io.BytesIO(result),
        mimetype="application/zip",
        as_attachment=True,
        download_name=output_name,
        max_age=0,
    )


@web.route("/verwaltung/kopfboegen/anmeldung", methods=["GET", "POST"])
def admin_login():
    configured = bool(current_app.config["LETTERHEAD_ADMIN_PASSWORD"])
    if request.method == "POST":
        if not _valid_csrf():
            abort(400)
        if not configured:
            flash("Die Verwaltung ist noch nicht konfiguriert.", "error")
        elif hmac.compare_digest(
            request.form.get("password", ""),
            current_app.config["LETTERHEAD_ADMIN_PASSWORD"],
        ):
            session["letterhead_admin"] = True
            return redirect(url_for("web.admin_letterheads"))
        else:
            flash("Das Kennwort ist nicht korrekt.", "error")
    return render_template(
        "admin_login.html",
        active_tool=None,
        configured=configured,
    )


@web.get("/verwaltung/kopfboegen")
@_admin_required
def admin_letterheads():
    return render_template(
        "admin_letterheads.html",
        active_tool=None,
        letterheads=list_letterheads(current_app.config["DATA_DIR"]),
    )


@web.post("/verwaltung/kopfboegen")
@_admin_required
def admin_add_letterhead():
    if not _valid_csrf():
        abort(400)
    upload = request.files.get("pdf")
    if not upload or not upload.filename or not upload.filename.lower().endswith(".pdf"):
        flash("Bitte eine PDF-Datei als Kopfbogen auswählen.", "error")
        return redirect(url_for("web.admin_letterheads"))
    try:
        add_letterhead(
            current_app.config["DATA_DIR"],
            request.form.get("name", "") or upload.filename,
            upload.read(),
        )
    except LetterheadError as exc:
        flash(str(exc), "error")
    else:
        flash("Kopfbogen wurde gespeichert.", "success")
    return redirect(url_for("web.admin_letterheads"))


@web.post("/verwaltung/kopfboegen/<identifier>/loeschen")
@_admin_required
def admin_delete_letterhead(identifier):
    if not _valid_csrf():
        abort(400)
    if delete_letterhead(current_app.config["DATA_DIR"], identifier):
        flash("Kopfbogen wurde gelöscht.", "success")
    else:
        flash("Der Kopfbogen wurde nicht gefunden.", "error")
    return redirect(url_for("web.admin_letterheads"))


@web.post("/verwaltung/abmelden")
@_admin_required
def admin_logout():
    if not _valid_csrf():
        abort(400)
    session.pop("letterhead_admin", None)
    return redirect(url_for("web.index"))


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
