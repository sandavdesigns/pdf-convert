from __future__ import annotations

import html
import io
import mimetypes
import re
import tempfile
import urllib.parse
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
CID_URL_RE = re.compile(r"cid:([^\s\"'<>\)]+)", re.IGNORECASE)
WINDOWS_INVALID_FILENAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
GERMAN_FILENAME_TRANSLATION = str.maketrans(
    {"Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}
)


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


def _filename_date(value: str) -> str:
    german_date = re.search(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b", value)
    if german_date:
        day, month, year = german_date.groups()
        return f"{year}-{int(month):02d}-{int(day):02d}"

    iso_date = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", value)
    if iso_date:
        year, month, day = iso_date.groups()
        return f"{year}-{int(month):02d}-{int(day):02d}"
    return "ohne-datum"


def _filename_sender(value: str) -> str:
    display_name = re.sub(r"\s*<[^>]*>\s*$", "", value).strip().strip("'\"")
    if not display_name:
        address = re.search(r"<([^>]+)>", value)
        display_name = address.group(1).split("@", 1)[0] if address else "Unbekannt"
    display_name = display_name.translate(GERMAN_FILENAME_TRANSLATION)
    display_name = WINDOWS_INVALID_FILENAME_RE.sub(".", display_name)
    display_name = re.sub(r"[^\w.-]+", ".", display_name, flags=re.UNICODE)
    display_name = re.sub(r"\.{2,}", ".", display_name).strip(" .")
    return display_name or "Unbekannt"


def mail_output_filename(mail: MailData) -> str:
    subject = WINDOWS_INVALID_FILENAME_RE.sub("-", mail.subject)
    subject = re.sub(r"\s+", " ", subject).strip(" .")
    subject = subject[:30].rstrip(" .") or "Ohne Betreff"
    filename = f"{_filename_date(mail.date)} {_filename_sender(mail.sender)} {subject}.pdf"
    return safe_filename(filename, "nachricht.pdf")


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
    if isinstance(data, memoryview):
        return data.tobytes()

    # Embedded Outlook messages expose an MSG object instead of raw bytes.
    # Export it directly and allow the parser to repair malformed embedded
    # storage trees produced by some Outlook versions.
    if data is not None and hasattr(data, "export"):
        exported = io.BytesIO()
        try:
            data.export(exported, allowBadEmbed=True)
        except TypeError:
            data.export(exported)
        except Exception as exc:
            raise ConversionError(f'Anlage "{name}" konnte nicht gelesen werden.') from exc
        return exported.getvalue()

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


def _attachment_name(raw_attachment, index: int) -> str:
    for attribute in ("name", "longFilename", "shortFilename", "displayName"):
        try:
            value = getattr(raw_attachment, attribute, None)
        except (AttributeError, NotImplementedError):
            value = None
        if value:
            return str(value)

    try:
        value = raw_attachment.getFilename()
    except (AttributeError, NotImplementedError):
        value = None
    return str(value or f"anlage-{index}")


def _web_attachment(raw_attachment, index: int) -> Attachment | None:
    """Preserve Outlook cloud attachments as Internet shortcuts.

    Web reference attachments do not contain the remote file bytes in the MSG,
    so downloading them server-side would require the user's Microsoft login.
    Keeping the URL is the only complete, local and credential-free option.
    """
    try:
        url = getattr(raw_attachment, "url", None)
    except (AttributeError, NotImplementedError):
        url = None
    if not url:
        return None

    path_name = Path(str(url).split("?", 1)[0]).name
    base_name = safe_filename(path_name, f"cloud-anlage-{index}")
    name = f"{base_name}.url" if not base_name.lower().endswith(".url") else base_name
    shortcut = f"[InternetShortcut]\r\nURL={url}\r\n".encode("utf-8")
    return Attachment(name, shortcut, "application/internet-shortcut")


def _normalize_content_id(value: str | None) -> str:
    return urllib.parse.unquote(str(value or "")).strip().strip("<>").casefold()


def _inline_content_ids(raw_html: str) -> set[str]:
    return {
        normalized
        for value in CID_URL_RE.findall(raw_html)
        if (normalized := _normalize_content_id(value))
    }


def _is_inline_attachment(raw_attachment, inline_content_ids: set[str]) -> bool:
    try:
        if bool(getattr(raw_attachment, "hidden", False)):
            return True
    except (AttributeError, NotImplementedError):
        pass

    try:
        content_id = getattr(raw_attachment, "cid", None) or getattr(raw_attachment, "contentId", None)
    except (AttributeError, NotImplementedError):
        content_id = None
    return bool(content_id and _normalize_content_id(content_id) in inline_content_ids)


def _extract_attachments(
    message, temp_dir: Path, inline_content_ids: set[str] | None = None
) -> tuple[Attachment, ...]:
    attachments: list[Attachment] = []
    used: set[str] = set()
    inline_content_ids = inline_content_ids or set()
    temp_dir.mkdir(parents=True, exist_ok=True)

    for index, raw in enumerate(message.attachments, start=1):
        if _is_inline_attachment(raw, inline_content_ids):
            continue

        web_attachment = _web_attachment(raw, index)
        if web_attachment is not None:
            name = unique_filename(web_attachment.name, used)
            attachments.append(
                Attachment(name, web_attachment.data, web_attachment.mime_type, web_attachment.content_id)
            )
            continue

        original_name = _attachment_name(raw, index)
        name = unique_filename(safe_filename(original_name, f"anlage-{index}"), used)
        if hasattr(getattr(raw, "data", None), "export") and not Path(name).suffix:
            name = unique_filename(f"{name}.msg", used)
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
            source_html = _decode_html(getattr(message, "htmlBody", None))
            attachments = _extract_attachments(
                message,
                temp_dir,
                _inline_content_ids(source_html),
            )
            prepared_html = getattr(message, "htmlBodyPrepared", None)
            body_html = _decode_html(prepared_html) or source_html
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


def _convert_msg_with_metadata(
    data: bytes, original_name: str, include_original: bool = True
) -> tuple[bytes, MailData]:
    if not is_msg_file(data):
        raise ConversionError("Die hochgeladene Datei ist keine gültige Outlook-MSG-Datei.")

    with tempfile.TemporaryDirectory(prefix="msg-pdf-") as directory:
        temp_dir = Path(directory)
        msg_path = temp_dir / "source.msg"
        msg_path.write_bytes(data)
        mail = read_msg(msg_path, temp_dir / "attachments")
        base_pdf = render_pdf(mail)
        pdf_bytes = embed_attachments(
            base_pdf,
            mail,
            data if include_original else None,
            original_name,
        )
        return pdf_bytes, mail


def convert_msg_bytes(data: bytes, original_name: str, include_original: bool = True) -> bytes:
    pdf_bytes, _ = _convert_msg_with_metadata(data, original_name, include_original)
    return pdf_bytes


def _mail_attachment_count(pdf_bytes: bytes, original_name: str, include_original: bool) -> int:
    with Pdf.open(io.BytesIO(pdf_bytes)) as pdf:
        count = len(pdf.attachments)
        original_key = safe_filename(original_name, "original.msg")
        if include_original and original_key in pdf.attachments:
            count -= 1
        return max(count, 0)


def convert_many(
    files: list[tuple[str, bytes]], include_original: bool = True
) -> tuple[bytes, str, str, int]:
    converted: list[tuple[str, bytes, MailData]] = []
    attachment_count = 0
    used: set[str] = set()
    for name, data in files:
        output_name = unique_filename(f"{safe_filename(name, 'nachricht.msg').rsplit('.', 1)[0]}.pdf", used)
        pdf_bytes, mail = _convert_msg_with_metadata(data, name, include_original)
        attachment_count += _mail_attachment_count(pdf_bytes, name, include_original)
        converted.append((output_name, pdf_bytes, mail))

    if len(converted) == 1:
        _, pdf_bytes, mail = converted[0]
        return pdf_bytes, mail_output_filename(mail), "application/pdf", attachment_count

    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name, pdf_bytes, _ in converted:
            bundle.writestr(name, pdf_bytes)
    return archive.getvalue(), "konvertierte-mails.zip", "application/zip", attachment_count
