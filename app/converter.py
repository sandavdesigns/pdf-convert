from __future__ import annotations

import html
import io
import mimetypes
import re
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

import extract_msg
import pikepdf
from bs4 import BeautifulSoup
from pikepdf import AttachedFileSpec, Name, Pdf
from weasyprint import CSS, HTML, default_url_fetcher


OLE_HEADER = bytes.fromhex("D0CF11E0A1B11AE1")
BLOCKED_TAGS = ("script", "iframe", "object", "embed", "form", "input", "button", "base")
REMOTE_URL_RE = re.compile(r"^(?:https?|ftp|file):", re.IGNORECASE)
CSS_URL_RE = re.compile(r"(?:@import\s+[^;]+;?|url\s*\([^)]*\))", re.IGNORECASE)


class ConversionError(Exception):
    """Raised when an MSG file cannot be converted safely."""


@dataclass(frozen=True)
class Attachment:
    name: str
    data: bytes
    mime_type: str
    content_id: str | None = None


@dataclass(frozen=True)
class MailData:
    subject: str
    sender: str
    recipients: str
    cc: str
    date: str
    body_html: str
    attachments: tuple[Attachment, ...]


def is_msg_file(data: bytes) -> bool:
    return data.startswith(OLE_HEADER)


def safe_filename(value: str | None, fallback: str) -> str:
    name = Path((value or fallback).replace("\\", "/")).name
    name = "".join(character for character in name if character >= " " and character not in '<>:"/\\|?*')
    name = name.strip(" .")
    return name[:180] or fallback


def unique_filename(name: str, used: set[str]) -> str:
    candidate = name
    stem = Path(name).stem
    suffix = Path(name).suffix
    index = 2
    while candidate.casefold() in used:
        candidate = f"{stem} ({index}){suffix}"
        index += 1
    used.add(candidate.casefold())
    return candidate


def _format_date(value) -> str:
    if not value:
        return ""
    if isinstance(value, datetime):
        timezone = value.strftime(" %Z") if value.tzinfo else ""
        return value.strftime("%d.%m.%Y, %H:%M") + timezone
    return str(value)


def _attachment_bytes(raw_attachment, name: str, temp_dir: Path) -> bytes:
    try:
        data = raw_attachment.data
    except (AttributeError, NotImplementedError):
        data = None

    if isinstance(data, bytes):
        return data
    if isinstance(data, bytearray):
        return bytes(data)

    try:
        result = raw_attachment.save(
            customPath=temp_dir,
            customFilename=name,
            extractEmbedded=True,
            skipNotImplemented=False,
        )
    except Exception as exc:
        raise ConversionError(f'Anlage "{name}" konnte nicht gelesen werden.') from exc

    expected = temp_dir / name
    if expected.is_file():
        return expected.read_bytes()

    saved = result[1] if isinstance(result, tuple) and len(result) > 1 else None
    candidates = saved if isinstance(saved, list) else [saved]
    for candidate in candidates:
        if candidate:
            path = Path(candidate)
            if not path.is_absolute():
                path = temp_dir / path
            if path.is_file():
                return path.read_bytes()

    raise ConversionError(f'Anlage "{name}" konnte nicht gespeichert werden.')


def _extract_attachments(message, temp_dir: Path) -> tuple[Attachment, ...]:
    attachments: list[Attachment] = []
    used: set[str] = set()
    temp_dir.mkdir(parents=True, exist_ok=True)

    for index, raw in enumerate(message.attachments, start=1):
        original_name = getattr(raw, "name", None) or getattr(raw, "longFilename", None)
        name = unique_filename(safe_filename(original_name, f"anlage-{index}"), used)
        data = _attachment_bytes(raw, name, temp_dir)
        mime_type = (
            getattr(raw, "mimetype", None)
            or mimetypes.guess_type(name)[0]
            or "application/octet-stream"
        )
        content_id = getattr(raw, "cid", None)
        attachments.append(Attachment(name, data, mime_type, content_id))

    return tuple(attachments)


def _decode_html(value: bytes | str | None) -> str:
    if not value:
        return ""
    if isinstance(value, str):
        return value
    for encoding in ("utf-8", "utf-16", "windows-1252"):
        try:
            return value.decode(encoding)
        except UnicodeDecodeError:
            continue
    return value.decode("utf-8", errors="replace")


def sanitize_email_html(raw_html: str) -> str:
    soup = BeautifulSoup(raw_html, "html.parser")

    for tag in soup.find_all(BLOCKED_TAGS):
        tag.decompose()

    for tag in soup.find_all(True):
        for attribute in list(tag.attrs):
            lower = attribute.lower()
            if lower.startswith("on"):
                del tag.attrs[attribute]
                continue
            value = tag.attrs.get(attribute)
            value_text = " ".join(value) if isinstance(value, list) else str(value or "")
            if lower in {"src", "href", "action", "poster"} and REMOTE_URL_RE.match(value_text.strip()):
                if lower == "href":
                    tag.attrs[attribute] = "#"
                else:
                    del tag.attrs[attribute]
            elif lower == "style":
                tag.attrs[attribute] = CSS_URL_RE.sub("", value_text)

    for style in soup.find_all("style"):
        style.string = CSS_URL_RE.sub("", style.get_text())

    body = soup.body
    return "".join(str(item) for item in body.contents) if body else str(soup)


def read_msg(source: Path, temp_dir: Path) -> MailData:
    try:
        with extract_msg.openMsg(source) as message:
            attachments = _extract_attachments(message, temp_dir)
            prepared_html = getattr(message, "htmlBodyPrepared", None)
            body_html = _decode_html(prepared_html or getattr(message, "htmlBody", None))
            if not body_html:
                plain_body = getattr(message, "body", None) or "(Kein Nachrichtentext vorhanden)"
                body_html = f"<pre>{html.escape(str(plain_body))}</pre>"

            return MailData(
                subject=str(getattr(message, "subject", None) or "(Ohne Betreff)"),
                sender=str(getattr(message, "sender", None) or ""),
                recipients=str(getattr(message, "to", None) or ""),
                cc=str(getattr(message, "cc", None) or ""),
                date=_format_date(getattr(message, "date", None)),
                body_html=sanitize_email_html(body_html),
                attachments=attachments,
            )
    except ConversionError:
        raise
    except Exception as exc:
        raise ConversionError("Die MSG-Datei ist beschädigt oder wird nicht unterstützt.") from exc


def _attachment_list(attachments: Iterable[Attachment]) -> str:
    items = "".join(
        f"<li>{html.escape(item.name)} <span>({len(item.data) / 1024:.1f} KB)</span></li>"
        for item in attachments
    )
    return f"<ul>{items}</ul>" if items else "<p>Keine Anlagen</p>"


def build_document_html(mail: MailData) -> str:
    fields = (
        ("Von", mail.sender),
        ("An", mail.recipients),
        ("CC", mail.cc),
        ("Datum", mail.date),
        ("Betreff", mail.subject),
    )
    rows = "".join(
        f"<dt>{html.escape(label)}</dt><dd>{html.escape(value)}</dd>"
        for label, value in fields
        if value
    )
    return f"""<!doctype html>
<html lang="de">
<head><meta charset="utf-8"><title>{html.escape(mail.subject)}</title></head>
<body>
  <header class="mail-header">
    <div class="eyebrow">E-Mail</div>
    <h1>{html.escape(mail.subject)}</h1>
    <dl>{rows}</dl>
  </header>
  <main class="mail-body">{mail.body_html}</main>
  <section class="attachments">
    <h2>Anlagen in dieser PDF</h2>
    {_attachment_list(mail.attachments)}
    <p class="hint">Die Originaldateien befinden sich im Anlagenbereich Ihres PDF-Programms.</p>
  </section>
</body>
</html>"""


PDF_CSS = """
@page {
  size: A4;
  margin: 18mm 17mm 19mm;
  @bottom-right {
    content: "Seite " counter(page) " von " counter(pages);
    color: #6b7280;
    font-size: 8pt;
  }
}
* { box-sizing: border-box; }
html { font-family: "DejaVu Sans", Arial, sans-serif; color: #172033; font-size: 9.5pt; }
body { margin: 0; overflow-wrap: anywhere; }
.mail-header { border-bottom: 2px solid #1f6feb; padding-bottom: 7mm; margin-bottom: 8mm; }
.eyebrow { color: #1f6feb; font-size: 8pt; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; }
h1 { font-size: 19pt; line-height: 1.2; margin: 2mm 0 5mm; }
dl { display: grid; grid-template-columns: 25mm 1fr; gap: 1.4mm 3mm; margin: 0; }
dt { color: #667085; font-weight: 700; }
dd { margin: 0; }
.mail-body { line-height: 1.48; min-height: 40mm; }
.mail-body img { max-width: 100%; height: auto; }
.mail-body table { max-width: 100%; border-collapse: collapse; }
.mail-body pre { font-family: "DejaVu Sans Mono", monospace; white-space: pre-wrap; }
.attachments { border-top: 1px solid #d9dee8; margin-top: 10mm; padding-top: 5mm; break-inside: avoid; }
.attachments h2 { font-size: 11pt; margin: 0 0 3mm; }
.attachments ul { margin: 0; padding-left: 5mm; }
.attachments li { margin: 1mm 0; }
.attachments li span, .hint { color: #667085; }
.hint { font-size: 8pt; margin: 3mm 0 0; }
a { color: #1f6feb; }
"""


def _offline_url_fetcher(url: str, *args, **kwargs):
    if url.startswith("data:"):
        return default_url_fetcher(url, *args, **kwargs)
    raise ValueError("External resources are disabled")


def render_pdf(mail: MailData) -> bytes:
    try:
        return HTML(
            string=build_document_html(mail),
            url_fetcher=_offline_url_fetcher,
        ).write_pdf(stylesheets=[CSS(string=PDF_CSS)])
    except Exception as exc:
        raise ConversionError("Der E-Mail-Inhalt konnte nicht als PDF gerendert werden.") from exc


def embed_attachments(pdf_bytes: bytes, mail: MailData, original_msg: bytes | None, original_name: str) -> bytes:
    output = io.BytesIO()
    try:
        with Pdf.open(io.BytesIO(pdf_bytes)) as pdf:
            for attachment in mail.attachments:
                file_spec = AttachedFileSpec(
                    pdf,
                    attachment.data,
                    filename=attachment.name,
                    mime_type=attachment.mime_type,
                    description="Originalanlage der E-Mail",
                )
                pdf.attachments[attachment.name] = file_spec

            if original_msg is not None:
                msg_name = safe_filename(original_name, "original.msg")
                pdf.attachments[msg_name] = AttachedFileSpec(
                    pdf,
                    original_msg,
                    filename=msg_name,
                    mime_type="application/vnd.ms-outlook",
                    description="Ursprüngliche Outlook-Nachricht",
                )

            pdf.Root.PageMode = Name.UseAttachments
            with pdf.open_metadata(set_pikepdf_as_editor=False) as metadata:
                metadata["dc:title"] = mail.subject
                metadata["dc:creator"] = [mail.sender] if mail.sender else ["MSG to PDF Converter"]
                metadata["pdf:Producer"] = "MSG to PDF Converter"
            pdf.save(output)
    except (pikepdf.PdfError, ValueError, TypeError) as exc:
        raise ConversionError("Die Anlagen konnten nicht in die PDF eingebettet werden.") from exc
    return output.getvalue()


def convert_msg_bytes(data: bytes, original_name: str, include_original: bool = True) -> bytes:
    if not is_msg_file(data):
        raise ConversionError("Die hochgeladene Datei ist keine gültige Outlook-MSG-Datei.")

    with tempfile.TemporaryDirectory(prefix="msg-pdf-") as directory:
        temp_dir = Path(directory)
        msg_path = temp_dir / "source.msg"
        msg_path.write_bytes(data)
        mail = read_msg(msg_path, temp_dir / "attachments")
        base_pdf = render_pdf(mail)
        return embed_attachments(
            base_pdf,
            mail,
            data if include_original else None,
            original_name,
        )


def convert_many(files: list[tuple[str, bytes]], include_original: bool = True) -> tuple[bytes, str, str]:
    converted: list[tuple[str, bytes]] = []
    used: set[str] = set()
    for name, data in files:
        output_name = unique_filename(f"{safe_filename(name, 'nachricht.msg').rsplit('.', 1)[0]}.pdf", used)
        converted.append((output_name, convert_msg_bytes(data, name, include_original)))

    if len(converted) == 1:
        return converted[0][1], converted[0][0], "application/pdf"

    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name, pdf_bytes in converted:
            bundle.writestr(name, pdf_bytes)
    return archive.getvalue(), "konvertierte-mails.zip", "application/zip"
