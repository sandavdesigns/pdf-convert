const form = document.getElementById("convert-form");
const input = document.getElementById("files");
const dropzone = document.getElementById("dropzone");
const list = document.getElementById("file-list");
const error = document.getElementById("error");
const success = document.getElementById("success");
const progress = document.getElementById("progress");
const button = document.getElementById("submit-button");
const exportAttachments = form.elements.export_attachments;
const fileBundleMime = "application/vnd.msg-pdf-files";

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const download = document.createElement("a");
  download.href = url;
  download.download = filename;
  document.body.appendChild(download);
  download.click();
  download.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 60000);
}

async function unpackFileBundle(blob) {
  const bytes = new Uint8Array(await blob.arrayBuffer());
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const decoder = new TextDecoder("utf-8", { fatal: true });
  const magic = decoder.decode(bytes.slice(0, 8));
  if (magic !== "MSGPDF01" || bytes.length < 12) {
    throw new Error("Das Dateipaket ist beschädigt.");
  }

  let offset = 8;
  const fileCount = view.getUint32(offset);
  offset += 4;
  const files = [];
  for (let index = 0; index < fileCount; index += 1) {
    if (offset + 12 > bytes.length) throw new Error("Das Dateipaket ist unvollständig.");
    const nameLength = view.getUint32(offset);
    const fileLength = Number(view.getBigUint64(offset + 4));
    offset += 12;
    if (!Number.isSafeInteger(fileLength) || offset + nameLength + fileLength > bytes.length) {
      throw new Error("Das Dateipaket ist unvollständig.");
    }
    const name = decoder.decode(bytes.slice(offset, offset + nameLength));
    offset += nameLength;
    files.push({ name, blob: new Blob([bytes.slice(offset, offset + fileLength)]) });
    offset += fileLength;
  }
  if (offset !== bytes.length) throw new Error("Das Dateipaket enthält ungültige Daten.");
  return files;
}

function renderFiles() {
  const files = Array.from(input.files);
  list.hidden = files.length === 0;
  list.innerHTML = files.map((file) => `
    <div class="file-row">
      <span class="file-name">${escapeHtml(file.name)}</span>
      <span>${formatBytes(file.size)}</span>
    </div>
  `).join("");
}

function escapeHtml(value) {
  const node = document.createElement("span");
  node.textContent = value;
  return node.innerHTML;
}

function formatBytes(bytes) {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

input.addEventListener("change", renderFiles);

["dragenter", "dragover"].forEach((eventName) => {
  dropzone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropzone.classList.add("dragging");
  });
});

dropzone.addEventListener("dragleave", () => dropzone.classList.remove("dragging"));
dropzone.addEventListener("drop", (event) => {
  event.preventDefault();
  dropzone.classList.remove("dragging");
  if (event.dataTransfer.files.length) {
    input.files = event.dataTransfer.files;
    renderFiles();
  }
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  error.hidden = true;
  success.hidden = true;
  if (!input.files.length) {
    error.textContent = "Bitte mindestens eine MSG-Datei auswählen.";
    error.hidden = false;
    return;
  }

  progress.hidden = false;
  button.disabled = true;
  const separateDownloads = exportAttachments.checked;
  try {
    const response = await fetch(form.action, { method: "POST", body: new FormData(form) });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.error || "Die Konvertierung ist fehlgeschlagen.");
    }

    const blob = await response.blob();
    const attachmentCount = Number.parseInt(response.headers.get("X-Mail-Attachment-Count") || "0", 10);
    const contentType = (response.headers.get("Content-Type") || "").split(";", 1)[0];
    if (contentType === fileBundleMime) {
      const files = await unpackFileBundle(blob);
      files.forEach((file) => downloadBlob(file.blob, file.name));
    } else {
      const disposition = response.headers.get("Content-Disposition") || "";
      const encoded = disposition.match(/filename\*=UTF-8''([^;]+)/i);
      const plain = disposition.match(/filename="?([^";]+)"?/i);
      const filename = encoded ? decodeURIComponent(encoded[1]) : (plain ? plain[1] : "konvertiert.pdf");
      downloadBlob(blob, filename);
    }
    if (separateDownloads) {
      success.textContent = attachmentCount === 1
        ? "Downloads gestartet: PDF und 1 Mail-Anlage werden einzeln gespeichert."
        : `Downloads gestartet: PDF-Datei(en) und ${attachmentCount} Mail-Anlagen werden einzeln gespeichert.`;
    } else {
      success.textContent = attachmentCount === 1
        ? "PDF erstellt: 1 Mail-Anlage wurde eingebettet."
        : `PDF erstellt: ${attachmentCount} Mail-Anlagen wurden eingebettet.`;
    }
    success.hidden = false;
  } catch (exception) {
    error.textContent = exception.message;
    error.hidden = false;
  } finally {
    progress.hidden = true;
    button.disabled = false;
  }
});
