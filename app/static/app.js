const form = document.getElementById("convert-form");
const input = document.getElementById("files");
const dropzone = document.getElementById("dropzone");
const list = document.getElementById("file-list");
const error = document.getElementById("error");
const progress = document.getElementById("progress");
const button = document.getElementById("submit-button");

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
  if (!input.files.length) {
    error.textContent = "Bitte mindestens eine MSG-Datei auswählen.";
    error.hidden = false;
    return;
  }

  progress.hidden = false;
  button.disabled = true;
  try {
    const response = await fetch(form.action, { method: "POST", body: new FormData(form) });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.error || "Die Konvertierung ist fehlgeschlagen.");
    }

    const blob = await response.blob();
    const disposition = response.headers.get("Content-Disposition") || "";
    const encoded = disposition.match(/filename\*=UTF-8''([^;]+)/i);
    const plain = disposition.match(/filename="?([^";]+)"?/i);
    const filename = encoded ? decodeURIComponent(encoded[1]) : (plain ? plain[1] : "konvertiert.pdf");
    const url = URL.createObjectURL(blob);
    const download = document.createElement("a");
    download.href = url;
    download.download = filename;
    document.body.appendChild(download);
    download.click();
    download.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 60000);
  } catch (exception) {
    error.textContent = exception.message;
    error.hidden = false;
  } finally {
    progress.hidden = true;
    button.disabled = false;
  }
});

